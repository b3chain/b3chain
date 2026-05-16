# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
b3chain CPU miner -- Windows test UI (PyQt6).

Entry point: launched via run_tests_ui.bat which creates a venv on first
run and `pythonw.exe`'s this file.

Architecture:
  CapabilityProbe   -- environment detection (capability_check.py)
  TestRegistry      -- ordered list of TestCase objects (test_definitions.py)
  TestRunner        -- runs the test queue serially via QProcess / QThread
  MainWindow        -- ties it all together with table / live output / footer

The whole queue is serial because tests 7 and 9 grab ports the others care
about, and running them in parallel would spuriously fail.
"""

from __future__ import annotations

import collections
import os
import re
import sys
import time
from typing import Callable, Deque, Dict, List, Optional, Tuple

# When run as `python test_ui.py` (not `python -m b3chain.contrib.miner.tests.test_ui`),
# we need to make sure the parent directory is on sys.path so the relative imports
# work. Also handle the case where the user double-clicks the .bat.
if __name__ == "__main__" and __package__ in (None, ""):
    _here = os.path.dirname(os.path.abspath(__file__))
    _parent = os.path.dirname(_here)
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    __package__ = "tests"

try:
    from PyQt6.QtCore import (
        QObject, QProcess, QProcessEnvironment, Qt, QThread, QTimer,
        pyqtSignal, pyqtSlot,
    )
    from PyQt6.QtGui import QAction, QFont, QIcon, QPalette, QColor
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout,
        QHeaderView, QLabel, QMainWindow, QMessageBox, QProgressBar,
        QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
        QTextEdit, QToolButton, QVBoxLayout, QWidget,
    )
except ImportError as e:  # pragma: no cover -- launcher should pip-install this
    print("ERROR: PyQt6 is not installed. Did you launch via run_tests_ui.bat?",
          file=sys.stderr)
    print(f"       (import failure: {e})", file=sys.stderr)
    sys.exit(1)

from .capability_check import Capability, CapabilityProbe
from .report_writer import write_report
from .test_definitions import (
    BuiltinTest, ERROR, FAIL, PASS, PENDING, RUNNING, SKIP, SubprocessTest,
    TestCase, TestRegistry, TestResult,
)


THIS_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Status -> color mapping (used in table cells and capability dots)
# ---------------------------------------------------------------------------

_STATUS_COLORS: Dict[str, str] = {
    PASS:    "#1f8a3b",   # green
    FAIL:    "#c0383d",   # red
    SKIP:    "#888888",   # gray
    ERROR:   "#d18b00",   # orange
    RUNNING: "#1c6ca4",   # blue
    PENDING: "#444444",
}


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes so output stays readable in a QTextEdit."""
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


# ---------------------------------------------------------------------------
# Builtin worker -- runs a Python callable in a QThread
# ---------------------------------------------------------------------------


class _BuiltinWorker(QObject):
    line = pyqtSignal(str)
    done = pyqtSignal(object)   # carries (passed: bool, metric: str, captured: str)

    def __init__(self, runner: Callable[[Callable[[str], None]], Tuple[bool, str]]):
        super().__init__()
        self._runner = runner
        self._captured: List[str] = []

    @pyqtSlot()
    def run(self):
        def emit(line: str):
            self._captured.append(line)
            self.line.emit(line)
        ok = False
        metric = ""
        try:
            ok, metric = self._runner(emit)
        except Exception as e:
            self.line.emit(f"ERROR: builtin raised: {e}")
            metric = f"exception: {e}"
        captured = "\n".join(self._captured[-200:])
        self.done.emit((ok, metric, captured))


# ---------------------------------------------------------------------------
# TestRunner -- runs ONE test at a time, but in a queue (run all)
# ---------------------------------------------------------------------------


class TestRunner(QObject):
    log_line = pyqtSignal(str)
    test_started = pyqtSignal(int)              # test id
    test_done = pyqtSignal(int, object)         # test id, TestResult
    queue_done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: Deque[TestCase] = collections.deque()
        self._current: Optional[TestCase] = None
        self._proc: Optional[QProcess] = None
        self._builtin_thread: Optional[QThread] = None
        self._builtin_worker: Optional[_BuiltinWorker] = None
        self._captured: List[str] = []
        self._started_at: float = 0.0
        self._cancelled: bool = False

    @property
    def current_test_id(self) -> int:
        return self._current.id if self._current else 0

    def is_busy(self) -> bool:
        return self._current is not None

    # ------------------------------------------------------------------ Queue
    def enqueue(self, tests: List[TestCase]) -> None:
        for t in tests:
            self._queue.append(t)
        self._kick_next()

    def cancel_current(self) -> None:
        """User clicked 'cancel' on the running test."""
        if not self._current:
            return
        self._cancelled = True
        self.log_line.emit(f"  >> cancelling test {self._current.id}...")
        if self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
        if self._builtin_thread is not None and self._builtin_thread.isRunning():
            # Builtins can't be hard-killed mid-execution from outside without
            # racy/unsafe APIs. Best-effort: ask the thread to exit on next
            # event-loop turn; the test will run to completion shortly.
            self._builtin_thread.requestInterruption()

    def kill_all(self) -> None:
        """Called on window close: drop the queue, kill the running test."""
        self._queue.clear()
        self.cancel_current()

    # ------------------------------------------------------------------ Inner
    def _kick_next(self) -> None:
        if self._current is not None or not self._queue:
            return
        self._current = self._queue.popleft()
        self._captured = []
        self._cancelled = False
        self._started_at = time.time()
        self.test_started.emit(self._current.id)
        self.log_line.emit(f"========== Test {self._current.id}: {self._current.name} ==========")

        if isinstance(self._current, SubprocessTest):
            self._start_subprocess(self._current)
        elif isinstance(self._current, BuiltinTest):
            self._start_builtin(self._current)
        else:
            self._finish(TestResult(status=ERROR, metric="unknown test type"))

    def _start_subprocess(self, t: SubprocessTest) -> None:
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # Make subprocess output unbuffered so we see lines as they are produced.
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)
        if t.cwd:
            proc.setWorkingDirectory(t.cwd)
        proc.readyReadStandardOutput.connect(self._on_proc_stdout)
        proc.finished.connect(self._on_proc_finished)
        proc.errorOccurred.connect(self._on_proc_error)
        self._proc = proc

        program = t.argv[0]
        args = t.argv[1:]
        self.log_line.emit(f"  $ {program} {' '.join(args)}")
        proc.start(program, args)
        if not proc.waitForStarted(5000):
            self.log_line.emit("  ERROR: process failed to start within 5s")
            self._finish(TestResult(status=ERROR, metric="process didn't start",
                                    detail=program))

    def _start_builtin(self, t: BuiltinTest) -> None:
        thread = QThread(self)
        worker = _BuiltinWorker(t.runner)
        worker.moveToThread(thread)
        worker.line.connect(self._on_builtin_line)
        worker.done.connect(self._on_builtin_done)
        thread.started.connect(worker.run)
        # When `done` is emitted, retire the thread and worker on the GUI thread.
        self._builtin_thread = thread
        self._builtin_worker = worker
        thread.start()

    # ----------------------------------------------------- Subprocess plumbing
    @pyqtSlot()
    def _on_proc_stdout(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardOutput())
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        for raw in text.splitlines():
            stripped = _strip_ansi(raw)
            self._captured.append(stripped)
            self.log_line.emit(stripped)

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_proc_finished(self, rc: int, status: QProcess.ExitStatus) -> None:
        # Drain any remaining output.
        self._on_proc_stdout()

        captured = "\n".join(self._captured)
        if not isinstance(self._current, SubprocessTest):
            return  # pragma: no cover

        if self._cancelled:
            result = TestResult(
                status=ERROR, metric="cancelled",
                detail="killed by user",
                stdout_tail="\n".join(self._captured[-40:]),
            )
        elif status == QProcess.ExitStatus.CrashExit or rc < 0:
            result = TestResult(
                status=ERROR, metric=f"crashed (rc={rc})",
                stdout_tail="\n".join(self._captured[-40:]),
            )
        else:
            try:
                verdict, metric, detail = self._current.result_extractor(rc, captured)
            except Exception as e:
                verdict, metric, detail = ERROR, f"extractor error: {e}", str(e)
            result = TestResult(
                status=verdict, metric=metric, detail=detail,
                stdout_tail="\n".join(self._captured[-40:]),
            )
        self._finish(result)

    @pyqtSlot(QProcess.ProcessError)
    def _on_proc_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self.log_line.emit("  ERROR: failed to start subprocess")

    # -------------------------------------------------------- Builtin plumbing
    @pyqtSlot(str)
    def _on_builtin_line(self, line: str) -> None:
        self._captured.append(line)
        self.log_line.emit(line)

    @pyqtSlot(object)
    def _on_builtin_done(self, payload) -> None:
        ok, metric, _captured = payload
        if not isinstance(self._current, BuiltinTest):
            return  # pragma: no cover

        if self._cancelled:
            status = ERROR
            metric = "cancelled"
        elif metric.startswith("skipped"):
            status = SKIP
        else:
            status = PASS if ok else FAIL

        result = TestResult(
            status=status, metric=metric,
            stdout_tail="\n".join(self._captured[-40:]),
        )
        if self._builtin_thread is not None:
            self._builtin_thread.quit()
            self._builtin_thread.wait(2000)
            self._builtin_thread.deleteLater()
            self._builtin_thread = None
        if self._builtin_worker is not None:
            self._builtin_worker.deleteLater()
            self._builtin_worker = None
        self._finish(result)

    def _finish(self, result: TestResult) -> None:
        if not self._current:
            return
        result.duration_s = time.time() - self._started_at
        result.started_at = self._started_at
        finished_id = self._current.id
        self._current = None
        if self._proc is not None:
            self._proc.deleteLater()
            self._proc = None
        self.test_done.emit(finished_id, result)
        if self._queue:
            # Schedule the next test on the next event-loop iteration so the
            # GUI gets a chance to repaint between tests.
            QTimer.singleShot(0, self._kick_next)
        else:
            self.queue_done.emit()


# ---------------------------------------------------------------------------
# Capability dots row
# ---------------------------------------------------------------------------


class CapabilityRow(QWidget):
    """Displays the current capability set as a grid of [name][status][detail]."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(2)
        self._grid.setContentsMargins(4, 4, 4, 4)

    def update_caps(self, caps: List[Capability]) -> None:
        # Wipe the grid, rebuild.
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        col_count = 3
        for i, cap in enumerate(caps):
            row, col = divmod(i, col_count)
            cell = QWidget()
            h = QHBoxLayout(cell)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)

            dot = QLabel("\u25CF")
            color = _STATUS_COLORS[PASS] if cap.present else _STATUS_COLORS[SKIP]
            dot.setStyleSheet(f"color: {color}; font-size: 14px;")
            label = QLabel(cap.label)
            label.setStyleSheet("font-weight: 600;")
            detail = QLabel(cap.detail or "-")
            detail.setStyleSheet("color: #888; font-family: Consolas, 'Courier New', monospace;")
            detail.setToolTip(cap.detail or "")
            detail.setMinimumWidth(280)
            detail.setMaximumWidth(420)
            detail.setWordWrap(False)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            h.addWidget(dot)
            h.addWidget(label)
            h.addWidget(detail, 1)
            self._grid.addWidget(cell, row, col)


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


COL_ID = 0
COL_NAME = 1
COL_STATUS = 2
COL_METRIC = 3
COL_DURATION = 4
COL_RUN = 5
COL_CANCEL = 6
COL_COUNT = 7

COL_HEADERS = ["#", "Name", "Status", "Metric", "Time", "Run", "Cancel"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("b3chain CPU miner -- Test Suite")
        self.resize(1200, 800)

        self._probe = CapabilityProbe()
        self._registry = TestRegistry()
        self._registry.update_enabled_state(self._probe)

        self._results: Dict[int, TestResult] = {
            t.id: TestResult() for t in self._registry
        }

        self._runner = TestRunner(self)
        self._runner.log_line.connect(self._on_log_line)
        self._runner.test_started.connect(self._on_test_started)
        self._runner.test_done.connect(self._on_test_done)
        self._runner.queue_done.connect(self._on_queue_done)

        self._build_ui()
        self._refresh_caps_view()
        self._populate_table()

    # -------------------------------------------------------------- Build UI
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ---- Top toolbar ----
        toolbar = QHBoxLayout()
        title = QLabel("<b>b3chain CPU miner -- Test Suite</b>")
        title.setStyleSheet("font-size: 14px;")
        toolbar.addWidget(title)
        toolbar.addStretch(1)
        self._include_slow = QCheckBox("Include slow tests (Test 9)")
        self._include_slow.setToolTip(
            "When checked, 'Run All' includes the local Docker pool stack test "
            "(~3 min). Even when unchecked you can still launch it from its row.")
        toolbar.addWidget(self._include_slow)
        self._recheck_btn = QPushButton("Recheck Env")
        self._recheck_btn.clicked.connect(self._on_recheck)
        toolbar.addWidget(self._recheck_btn)
        self._run_all_btn = QPushButton("Run All")
        self._run_all_btn.clicked.connect(self._on_run_all)
        toolbar.addWidget(self._run_all_btn)
        self._save_btn = QPushButton("Save Report")
        self._save_btn.clicked.connect(self._on_save_report)
        toolbar.addWidget(self._save_btn)
        layout.addLayout(toolbar)

        # ---- Capability strip ----
        env_label = QLabel("<b>Environment</b>")
        layout.addWidget(env_label)
        self._caps_row = CapabilityRow()
        layout.addWidget(self._caps_row)

        # ---- Splitter: tests table on top, output on bottom ----
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Table
        self._table = QTableWidget(0, COL_COUNT)
        self._table.setHorizontalHeaderLabels(COL_HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(self._table.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(self._table.EditTrigger.NoEditTriggers)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(COL_ID, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_METRIC, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_DURATION, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_RUN, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_CANCEL, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setMinimumHeight(220)
        splitter.addWidget(self._table)

        # Output pane
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self._output.setFont(font)
        self._output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._output.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #dcdcdc; }")
        splitter.addWidget(self._output)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 540])

        layout.addWidget(splitter, 1)

        # ---- Footer ----
        footer = QHBoxLayout()
        self._summary_label = QLabel("Ready.")
        footer.addWidget(self._summary_label, 1)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate when running
        self._progress.setVisible(False)
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(180)
        footer.addWidget(self._progress)
        layout.addLayout(footer)

        self.setCentralWidget(central)

    # ------------------------------------------------------------ Cap refresh
    def _refresh_caps_view(self) -> None:
        self._caps_row.update_caps(self._probe.all())

    @pyqtSlot()
    def _on_recheck(self) -> None:
        self._append("[Recheck] re-running capability probes...")
        self._probe.refresh()
        self._registry.update_enabled_state(self._probe)
        self._refresh_caps_view()
        self._populate_table()
        self._append("[Recheck] done")

    # ----------------------------------------------------------- Build table
    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        for case in self._registry:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setRowHeight(row, 30)

            id_item = QTableWidgetItem(str(case.id))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, COL_ID, id_item)

            name_item = QTableWidgetItem(case.name)
            name_item.setToolTip(case.description)
            self._table.setItem(row, COL_NAME, name_item)

            res = self._results.get(case.id) or TestResult()
            self._set_status_cell(row, res, case)
            self._set_metric_cell(row, res)
            self._set_duration_cell(row, res)

            run_btn = QPushButton("Run")
            run_btn.setEnabled(case.enabled)
            if not case.enabled:
                run_btn.setToolTip(case.disabled_reason)
            run_btn.clicked.connect(lambda _checked=False, c=case: self._run_one(c))
            self._table.setCellWidget(row, COL_RUN, run_btn)

            cancel_btn = QPushButton("Stop")
            cancel_btn.setEnabled(False)
            cancel_btn.clicked.connect(self._on_cancel_current)
            self._table.setCellWidget(row, COL_CANCEL, cancel_btn)

        self._update_summary()

    def _set_status_cell(self, row: int, res: TestResult, case: TestCase) -> None:
        status = res.status
        if status == PENDING and not case.enabled:
            text = "DISABLED"
            color = _STATUS_COLORS[SKIP]
        else:
            text = status
            color = _STATUS_COLORS.get(status, "#000")
        item = QTableWidgetItem(text)
        item.setForeground(QColor(color))
        font = QFont(self._table.font())
        font.setBold(True)
        item.setFont(font)
        if not case.enabled:
            item.setToolTip(case.disabled_reason)
        self._table.setItem(row, COL_STATUS, item)

    def _set_metric_cell(self, row: int, res: TestResult) -> None:
        item = QTableWidgetItem(res.metric or "-")
        if res.detail:
            item.setToolTip(res.detail)
        self._table.setItem(row, COL_METRIC, item)

    def _set_duration_cell(self, row: int, res: TestResult) -> None:
        text = f"{res.duration_s:.1f}s" if res.duration_s else "-"
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, COL_DURATION, item)

    def _row_for_id(self, test_id: int) -> int:
        for row in range(self._table.rowCount()):
            if int(self._table.item(row, COL_ID).text()) == test_id:
                return row
        return -1

    # --------------------------------------------------- Output / log helpers
    def _append(self, line: str) -> None:
        self._output.append(line)
        # Autoscroll.
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())

    @pyqtSlot(str)
    def _on_log_line(self, line: str) -> None:
        self._append(line)

    # -------------------------------------------------------------- Run flow
    def _run_one(self, case: TestCase) -> None:
        if self._runner.is_busy():
            QMessageBox.information(
                self, "Test in progress",
                "A test is currently running. Wait for it to finish or cancel it.")
            return
        self._results[case.id] = TestResult(status=PENDING)
        self._runner.enqueue([case])

    @pyqtSlot()
    def _on_run_all(self) -> None:
        if self._runner.is_busy():
            QMessageBox.information(
                self, "Already running",
                "The runner is busy. Wait for the current queue to finish.")
            return
        include_slow = self._include_slow.isChecked()
        tests = self._registry.runnable_for_run_all(include_slow=include_slow)
        if not tests:
            QMessageBox.warning(self, "Nothing to run",
                                "All tests are disabled or skipped.")
            return
        for t in tests:
            self._results[t.id] = TestResult(status=PENDING)
        self._populate_table()
        self._append(f"[RunAll] queued {len(tests)} test(s) "
                     f"(slow tests: {'on' if include_slow else 'off'})")
        self._runner.enqueue(tests)

    @pyqtSlot(int)
    def _on_test_started(self, test_id: int) -> None:
        self._results[test_id] = TestResult(status=RUNNING)
        row = self._row_for_id(test_id)
        if row >= 0:
            case = self._registry.get(test_id)
            if case is not None:
                self._set_status_cell(row, self._results[test_id], case)
            self._set_metric_cell(row, TestResult(status=RUNNING, metric="..."))
            self._set_duration_cell(row, TestResult(status=RUNNING))
            cancel_btn = self._table.cellWidget(row, COL_CANCEL)
            if isinstance(cancel_btn, QPushButton):
                cancel_btn.setEnabled(True)
        self._progress.setVisible(True)
        self._summary_label.setText(
            f"Running test {test_id}: "
            f"{self._registry.get(test_id).name if self._registry.get(test_id) else ''}")

    @pyqtSlot(int, object)
    def _on_test_done(self, test_id: int, result: TestResult) -> None:
        if not isinstance(result, TestResult):
            return
        self._results[test_id] = result
        row = self._row_for_id(test_id)
        case = self._registry.get(test_id)
        if row >= 0 and case is not None:
            self._set_status_cell(row, result, case)
            self._set_metric_cell(row, result)
            self._set_duration_cell(row, result)
            cancel_btn = self._table.cellWidget(row, COL_CANCEL)
            if isinstance(cancel_btn, QPushButton):
                cancel_btn.setEnabled(False)
        self._append(f"  -> {result.status} ({result.metric}) [{result.duration_s:.1f}s]")
        self._update_summary()

    @pyqtSlot()
    def _on_queue_done(self) -> None:
        self._progress.setVisible(False)
        self._update_summary(idle=True)

    @pyqtSlot()
    def _on_cancel_current(self) -> None:
        self._append("[Cancel] requesting cancellation of running test")
        self._runner.cancel_current()

    def _update_summary(self, idle: bool = False) -> None:
        passed = failed = skipped = errored = pending = running = 0
        total_s = 0.0
        for r in self._results.values():
            if r.status == PASS: passed += 1
            elif r.status == FAIL: failed += 1
            elif r.status == SKIP: skipped += 1
            elif r.status == ERROR: errored += 1
            elif r.status == RUNNING: running += 1
            else: pending += 1
            total_s += r.duration_s or 0.0
        if running:
            prefix = f"running ({running})"
        elif idle and (passed or failed or skipped or errored):
            prefix = "Idle"
        else:
            prefix = "Idle"
        self._summary_label.setText(
            f"{prefix} | PASS={passed} FAIL={failed} SKIP={skipped} "
            f"ERROR={errored} PENDING={pending} | total {total_s:.1f}s")

    # ----------------------------------------------------------- Save Report
    @pyqtSlot()
    def _on_save_report(self) -> None:
        if self._runner.is_busy():
            ans = QMessageBox.question(
                self, "Test in progress",
                "A test is still running. Save what we have so far?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        rows = [(case, self._results.get(case.id) or TestResult())
                for case in self._registry]
        try:
            json_path, md_path = write_report(THIS_DIR, self._probe, rows)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not save report: {e}")
            return
        self._append(f"[Save] wrote {json_path}")
        self._append(f"[Save] wrote {md_path}")
        QMessageBox.information(
            self, "Report saved",
            f"Wrote:\n  {json_path}\n  {md_path}")

    # --------------------------------------------------------- Window close
    def closeEvent(self, event):
        # Cleanup hook: kill any in-flight test before the window dies.
        if self._runner.is_busy():
            self._append("[Close] killing in-flight test before exit...")
            self._runner.kill_all()
            # Give the kill signal a moment to land.
            QApplication.processEvents()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("b3chain-miner-tests")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
