# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Live mining dashboard for the b3chain CPU miner.

The dashboard is a separate QMainWindow opened from a "Mine" button in
the test UI. It drives EITHER `b3chain-cpuminer.py` (Python, CPU,
default) OR `b3chain-gpuminer` (Rust, NVIDIA CUDA, opt-in via the
"Backend" combo) as a QProcess against a configurable Stratum V1 pool,
parses the chosen miner's --json-log file in real time, and shows live
hashrate, share counters, per-thread stats, recent shares, last-share
details, a polyline hashrate chart, and the raw + JSONL output streams
in tabs. Both miners share the same JSONL schema so the rest of this
file does not care which backend produced the file. A Save Session
button writes a complete session report.
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Deque, Dict, List, Optional

from PyQt6.QtCore import (
    QObject, QProcess, QProcessEnvironment, Qt, QTimer,
    pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import QColor, QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .capability_check import MINER_SCRIPT, gpu_miner_binary_path
from .hashrate_chart import HashrateChart, _fmt_rate
from .mining_parsers import (
    AuthorizedEvent, BlockFoundEvent, ConnectEvent, DisconnectEvent,
    JSONLTail, NotifyEvent, ProgressEvent, RawEvent, SetDifficultyEvent,
    ShareEvent, SubscribedEvent, SummaryEvent,
)
from .mining_state import MiningSession, RECENT_SHARES_CAP


# ---------------------------------------------------------------------------
# Config + paths
# ---------------------------------------------------------------------------


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(THIS_DIR, ".miner_settings.json")
DEFAULT_POOL_URL = "stratum+tcp://pool.b3chain.org:3333"
DEFAULT_USER = "anonymous@b3chain.org.cpu1"
DEFAULT_USERAGENT = "b3chain-cpuminer/1.0"
STDOUT_BUFFER_LINES = 20_000   # cap for in-memory stdout buffer
JSONL_RAW_TAIL_LINES = 5_000   # cap for the JSONL events tab text


def _default_thread_count() -> int:
    """Sensible default thread count for a Python BLAKE3 miner.

    Each worker holds the Python GIL for the per-iteration overhead
    (header serialise, int compares, target check) and only releases
    it during the BLAKE3 C call. On a hyperthreaded box, scheduling
    one worker per LOGICAL core (cpu_count - 1) over-subscribes the
    GIL and starves half the workers, producing skewed per-thread
    rates. Capping at roughly the physical core count gives a much
    more uniform per-thread hashrate and a HIGHER aggregate. We
    approximate physical cores as logical/2 (true on every Intel /
    AMD desktop SKU since Nehalem; false only on non-SMT CPUs, where
    logical/2 just leaves one core spare for the dispatcher + UI).
    """
    logical = os.cpu_count() or 2
    return max(1, logical // 2)


BACKEND_CPU = "cpu"
BACKEND_GPU = "gpu"


@dataclasses.dataclass
class MiningConfig:
    pool_url: str = DEFAULT_POOL_URL
    user: str = DEFAULT_USER
    password: str = "x"
    threads: int = dataclasses.field(default_factory=_default_thread_count)
    useragent: str = DEFAULT_USERAGENT
    # "cpu" -> spawn b3chain-cpuminer.py (Python). "gpu" -> spawn the
    # Rust b3chain-gpuminer binary (CUDA). The dashboard only offers
    # "gpu" when capability_check.gpu_miner_binary_path() resolves.
    backend: str = BACKEND_CPU


def _load_settings() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _save_settings(d: dict) -> None:
    try:
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except OSError:
        pass


def _python_console_executable() -> str:
    """Return the console-mode Python interpreter to use for subprocesses.

    On Windows the launcher hosts the dashboard under pythonw.exe (so it
    has no console window). If we spawn the miner with sys.executable
    we'd inherit pythonw, where any thread that touches sys.stdout/stderr
    can hit None and silently die. Resolve to python.exe in the same
    directory; QProcess pipe redirection prevents a second console window
    from popping up. Fall back to sys.executable on every other platform.
    """
    exe = sys.executable
    if sys.platform == "win32":
        base = os.path.basename(exe).lower()
        if base == "pythonw.exe":
            console = os.path.join(os.path.dirname(exe), "python.exe")
            if os.path.exists(console):
                return console
    return exe


# ---------------------------------------------------------------------------
# MiningRunner -- owns the QProcess + JSONLTail + signals
# ---------------------------------------------------------------------------


class MiningRunner(QObject):
    """Drives the miner subprocess and emits typed signals for the UI.

    All slots run on the GUI thread; QProcess + QTimer integrate cleanly
    with Qt's event loop. The runner owns the temp JSONL file lifecycle.
    """

    # Lifecycle
    started = pyqtSignal()
    stopped = pyqtSignal()
    failed_to_start = pyqtSignal(str)

    # Stream signals
    stdout_line = pyqtSignal(str)
    raw_event = pyqtSignal(object)        # RawEvent or any unwrapped dict-ish

    # Typed parsed events
    connected = pyqtSignal(object)        # ConnectEvent
    subscribed = pyqtSignal(object)       # SubscribedEvent
    authorized = pyqtSignal(object)       # AuthorizedEvent
    set_difficulty = pyqtSignal(object)   # SetDifficultyEvent
    notify = pyqtSignal(object)           # NotifyEvent
    progress = pyqtSignal(object)         # ProgressEvent
    share = pyqtSignal(object)            # ShareEvent
    block_found = pyqtSignal(object)      # BlockFoundEvent
    disconnected = pyqtSignal(object)     # DisconnectEvent
    summary = pyqtSignal(object)          # SummaryEvent

    POLL_INTERVAL_MS = 250

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._proc: Optional[QProcess] = None
        self._tail: Optional[JSONLTail] = None
        self._tail_timer = QTimer(self)
        self._tail_timer.setInterval(self.POLL_INTERVAL_MS)
        self._tail_timer.timeout.connect(self._on_tail_tick)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.setInterval(3000)
        self._kill_timer.timeout.connect(self._on_kill_timeout)

        self._jsonl_path: Optional[str] = None
        self._stdout_buffer: Deque[str] = collections.deque(
            maxlen=STDOUT_BUFFER_LINES)
        self._raw_jsonl_lines: Deque[str] = collections.deque(
            maxlen=JSONL_RAW_TAIL_LINES)
        self._stopping = False
        self._cfg: Optional[MiningConfig] = None

    # ------------------------------------------------------------ properties
    @property
    def is_running(self) -> bool:
        return (self._proc is not None
                and self._proc.state() != QProcess.ProcessState.NotRunning)

    @property
    def jsonl_path(self) -> Optional[str]:
        return self._jsonl_path

    @property
    def config(self) -> Optional[MiningConfig]:
        return self._cfg

    def stdout_text(self) -> str:
        return "\n".join(self._stdout_buffer)

    def jsonl_text(self) -> str:
        return "".join(self._raw_jsonl_lines)

    # ------------------------------------------------------------ start/stop

    def start(self, cfg: MiningConfig) -> None:
        if self.is_running:
            return
        if cfg.backend == BACKEND_GPU:
            gpu_bin = gpu_miner_binary_path()
            if not gpu_bin:
                self.failed_to_start.emit(
                    "GPU backend selected but b3chain-gpuminer binary not "
                    "found. Build it with `cargo build --release` in "
                    "contrib/miner/b3chain-gpuminer/."
                )
                return
        elif not os.path.exists(MINER_SCRIPT):
            self.failed_to_start.emit(f"miner script missing: {MINER_SCRIPT}")
            return

        self._cfg = cfg
        self._stopping = False
        self._stdout_buffer.clear()
        self._raw_jsonl_lines.clear()

        fd, jsonl_path = tempfile.mkstemp(prefix="b3chain-mining-",
                                          suffix=".jsonl")
        os.close(fd)
        # Truncate so we start clean.
        try:
            open(jsonl_path, "w", encoding="utf-8").close()
        except OSError as e:
            self.failed_to_start.emit(f"could not create JSONL: {e}")
            return
        self._jsonl_path = jsonl_path
        self._tail = JSONLTail(jsonl_path)

        argv = self._build_argv(cfg, jsonl_path)
        program = argv[0]
        args = argv[1:]
        self._stdout_buffer.append(f"$ {program} {' '.join(args)}")
        self.stdout_line.emit(f"$ {program} {' '.join(args)}")

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(self._on_proc_stdout)
        proc.finished.connect(self._on_proc_finished)
        proc.errorOccurred.connect(self._on_proc_error)
        self._proc = proc

        proc.start(program, args)
        if not proc.waitForStarted(5000):
            self.failed_to_start.emit("miner subprocess failed to start")
            self._teardown_jsonl()
            self._proc = None
            return

        # Step 1 of the runner contract: open JSONL path BEFORE starting timer.
        # Step 2: start the 250 ms polling timer.
        self._tail_timer.start()
        self.started.emit()

    def stop(self) -> None:
        """Ask the miner to stop. Terminates, then kills after 3s."""
        if not self.is_running:
            self._cleanup_after_exit()
            return
        self._stopping = True
        try:
            self._proc.terminate()
        except OSError:
            pass
        self._kill_timer.start()

    def _on_kill_timeout(self) -> None:
        if self.is_running:
            try:
                self._proc.kill()
            except OSError:
                pass

    # -------------------------------------------------------- argv builder

    @staticmethod
    def _build_argv(cfg: MiningConfig, jsonl_path: str) -> List[str]:
        if cfg.backend == BACKEND_GPU:
            return MiningRunner._build_argv_gpu(cfg, jsonl_path)
        return MiningRunner._build_argv_cpu(cfg, jsonl_path)

    @staticmethod
    def _build_argv_cpu(cfg: MiningConfig, jsonl_path: str) -> List[str]:
        # Use a smaller --progress-interval than the miner CLI default
        # (1_000_000) so the dashboard's hashrate ticks fast even on
        # slower boxes. The miner also has a wall-clock floor of ~1s, so
        # progress lands at most 1s after start regardless of interval.
        # Use the console interpreter (python.exe) on Windows even when
        # the dashboard itself is hosted by pythonw.exe -- the miner
        # threads call print() and we want stdout captured normally.
        return [
            _python_console_executable(), MINER_SCRIPT,
            "--stratum", cfg.pool_url,
            "--user", cfg.user,
            "--pass", cfg.password,
            "--threads", str(cfg.threads),
            "--useragent", cfg.useragent,
            "--json-log", jsonl_path,
            "--progress-interval", "100000",
        ]

    @staticmethod
    def _build_argv_gpu(cfg: MiningConfig, jsonl_path: str) -> List[str]:
        # The CUDA miner binary speaks the same JSONL schema as the
        # Python miner (share_pre_submit, share_submit, progress, ...)
        # so the rest of this dashboard does not care which backend
        # produced the file. The argv shape is intentionally a strict
        # subset of the CPU miner's: --threads becomes irrelevant on
        # the GPU (one driver task instead of N worker threads), so we
        # drop it.
        gpu_bin = gpu_miner_binary_path()
        if not gpu_bin:
            # Should not happen -- the UI greys out the GPU radio when
            # the binary is missing -- but keep a useful fallback so
            # the error surfaced to the user is "binary missing" not
            # "type error".
            gpu_bin = "b3chain-gpuminer"
        return [
            gpu_bin,
            "--stratum", cfg.pool_url,
            "--user", cfg.user,
            "--pass", cfg.password,
            "--useragent", cfg.useragent,
            "--json-log", jsonl_path,
        ]

    # ---------------------------------------------------------- subprocess

    @pyqtSlot()
    def _on_proc_stdout(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardOutput())
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        for raw in text.splitlines():
            line = raw.rstrip("\r")
            self._stdout_buffer.append(line)
            self.stdout_line.emit(line)

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_proc_finished(self, rc: int, status: QProcess.ExitStatus) -> None:
        # Drain anything that arrived after the last readyRead.
        self._on_proc_stdout()
        # One final JSONL drain so the miner's own `summary` event lands.
        self._drain_jsonl(final=True)
        self._kill_timer.stop()
        self._tail_timer.stop()
        self._stdout_buffer.append(f"-- miner exited rc={rc} --")
        self.stdout_line.emit(f"-- miner exited rc={rc} --")
        self._cleanup_after_exit()

    @pyqtSlot(QProcess.ProcessError)
    def _on_proc_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self.failed_to_start.emit("miner subprocess failed to start")

    def _cleanup_after_exit(self) -> None:
        if self._proc is not None:
            self._proc.deleteLater()
            self._proc = None
        self.stopped.emit()

    def _teardown_jsonl(self) -> None:
        path = self._jsonl_path
        self._jsonl_path = None
        self._tail = None
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    def discard_jsonl(self) -> None:
        """Caller should invoke this once the dashboard no longer needs the
        JSONL file (e.g. after Save Session has copied it out, or on close)."""
        self._teardown_jsonl()

    # ----------------------------------------------------------- JSONL pump

    @pyqtSlot()
    def _on_tail_tick(self) -> None:
        self._drain_jsonl(final=False)

    def _drain_jsonl(self, final: bool) -> None:
        if not self._tail:
            return
        # Append newly-arrived raw lines to the JSONL events tab buffer.
        try:
            size = os.path.getsize(self._tail.path) if os.path.exists(self._tail.path) else 0
        except OSError:
            size = 0
        prev_offset = self._tail.offset
        events = self._tail.drain_remaining() if final else self._tail.poll()
        # We re-read the chunk we just consumed for the raw text view.
        # This double-read keeps the tab buffer simple (no offset tracking
        # in two places) and it's only the small N kB of new data anyway.
        try:
            if size > prev_offset and os.path.exists(self._tail.path):
                with open(self._tail.path, "rb") as f:
                    f.seek(prev_offset)
                    chunk = f.read(size - prev_offset)
                txt = chunk.decode("utf-8", errors="replace")
                # Emit per-line, capped.
                for raw in txt.splitlines():
                    if raw.strip():
                        self._raw_jsonl_lines.append(raw + "\n")
        except OSError:
            pass

        for ev in events:
            self._dispatch_event(ev)

    def _dispatch_event(self, ev) -> None:
        if isinstance(ev, ShareEvent):
            self.share.emit(ev)
        elif isinstance(ev, ProgressEvent):
            self.progress.emit(ev)
        elif isinstance(ev, NotifyEvent):
            self.notify.emit(ev)
        elif isinstance(ev, SetDifficultyEvent):
            self.set_difficulty.emit(ev)
        elif isinstance(ev, SubscribedEvent):
            self.subscribed.emit(ev)
        elif isinstance(ev, ConnectEvent):
            self.connected.emit(ev)
        elif isinstance(ev, AuthorizedEvent):
            self.authorized.emit(ev)
        elif isinstance(ev, DisconnectEvent):
            self.disconnected.emit(ev)
        elif isinstance(ev, BlockFoundEvent):
            self.block_found.emit(ev)
        elif isinstance(ev, SummaryEvent):
            self.summary.emit(ev)
        elif isinstance(ev, RawEvent):
            self.raw_event.emit(ev)


# ---------------------------------------------------------------------------
# Save Session helpers
# ---------------------------------------------------------------------------


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _save_session(out_dir: str, runner: MiningRunner,
                  session: MiningSession) -> None:
    """Copy stdout + JSONL into out_dir and write summary.{json,md}."""
    os.makedirs(out_dir, exist_ok=True)

    # 1. stdout log (always written, even if empty)
    stdout_log = os.path.join(out_dir, "miner-stdout.log")
    with open(stdout_log, "w", encoding="utf-8") as f:
        f.write(runner.stdout_text())
        if not runner.stdout_text().endswith("\n"):
            f.write("\n")

    # 2. shares.jsonl (preserved as-is from the temp file)
    if runner.jsonl_path and os.path.exists(runner.jsonl_path):
        shutil.copyfile(runner.jsonl_path,
                        os.path.join(out_dir, "shares.jsonl"))
    else:
        open(os.path.join(out_dir, "shares.jsonl"), "w").close()

    # 3. session-summary.json
    summary = _build_summary(session)
    with open(os.path.join(out_dir, "session-summary.json"),
              "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # 4. session-summary.md
    md = _render_markdown(summary, session)
    with open(os.path.join(out_dir, "session-summary.md"),
              "w", encoding="utf-8") as f:
        f.write(md)


def _build_summary(session: MiningSession) -> dict:
    snap = session.snapshot()
    return {
        "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": {
            "os": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        **snap,
    }


def _render_markdown(summary: dict, session: MiningSession) -> str:
    out: List[str] = []
    out.append("# b3chain CPU miner -- session summary")
    out.append("")
    out.append(f"- Captured: {summary['ts']}")
    out.append(f"- OS: {summary['host']['os']}  ({summary['host']['machine']})")
    out.append(f"- Python: {summary['host']['python']}")
    cfg = summary.get("config", {})
    out.append(f"- Pool: {cfg.get('host')}:{cfg.get('port')} "
               f"(tls={cfg.get('use_tls')})")
    out.append(f"- User: {cfg.get('user')}")
    out.append(f"- Useragent: {cfg.get('useragent')}")
    out.append(f"- Runtime: {summary['runtime_s']}s")
    out.append("")
    t = summary["totals"]
    out.append("## Totals")
    out.append("")
    out.append(f"- Submitted: {t['submitted']}")
    out.append(f"- Accepted: {t['accepted']} ({t['accept_rate']*100:.1f}%)")
    out.append(f"- Rejected: {t['rejected']}")
    out.append(f"- Blocks: {t['blocks']}")
    out.append(f"- Attempts: {_fmt_int(t['attempts'])}")
    out.append(f"- Current hashrate: {_fmt_rate(t['current_hashrate_hps'])}")
    out.append(f"- Avg hashrate: {_fmt_rate(t['avg_hashrate_hps'])}")
    out.append(f"- Best PoW (BE): `{t['best_pow_be'] or '-'}`")
    out.append("")

    out.append("## Difficulty")
    out.append("")
    out.append(f"- Network difficulty: {summary['network']['difficulty']:g}")
    out.append(f"- Network target (BE): `{summary['network']['target_be']}`")
    out.append(f"- Share difficulty:   {summary['share']['difficulty']:g}")
    out.append(f"- Share target (BE):   `{summary['share']['target_be']}`")
    out.append(f"- Current job: `{summary['current_job']}`")
    out.append("")

    pt = summary.get("per_thread") or []
    if pt:
        out.append("## Per-thread")
        out.append("")
        out.append("| Thread | Rate | Attempts | Best PoW (BE) | Job |")
        out.append("|---|---|---|---|---|")
        for s in pt:
            out.append(
                f"| {s['id']} | {_fmt_rate(s['rate_hps'])} | "
                f"{_fmt_int(s['attempts'])} | `{s['best_pow_be'] or '-'}` | "
                f"`{s['job_id']}` |"
            )
        out.append("")

    last = summary.get("last_share")
    if last:
        out.append("## Last share")
        out.append("")
        out.append(f"- Seq: {last['seq']}")
        out.append(f"- Status: {'ACCEPTED' if last['accepted'] else 'REJECTED'}"
                   + (f"  (block!)" if last.get('is_block') else ""))
        out.append(f"- Job: `{last['job_id']}`")
        out.append(f"- ntime: {last['ntime']}")
        out.append(f"- nonce: 0x{last['nonce']:08x}")
        out.append(f"- PoW (BE): `{last['pow_hash_be']}`")
        out.append(f"- Share target (BE): `{last['share_target_be']}`")
        out.append(f"- RTT: {last['rtt_ms']:.1f} ms")
        if last.get("error"):
            out.append(f"- Error: `{last['error']}`")
        out.append("")

    if session.last_disconnect_reason:
        out.append(f"## Last disconnect")
        out.append("")
        out.append(f"- Reason: {session.last_disconnect_reason}")
        out.append("")

    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Status banner
# ---------------------------------------------------------------------------


STATUS_IDLE = "IDLE"
STATUS_STARTING = "STARTING"
STATUS_CONNECTED = "CONNECTED"
STATUS_MINING = "MINING"
STATUS_STOPPED = "STOPPED"
STATUS_ERROR = "ERROR"

_STATUS_COLORS = {
    STATUS_IDLE: "#888888",
    STATUS_STARTING: "#1c6ca4",
    STATUS_CONNECTED: "#1c6ca4",
    STATUS_MINING: "#1f8a3b",
    STATUS_STOPPED: "#888888",
    STATUS_ERROR: "#c0383d",
}


# ---------------------------------------------------------------------------
# MiningDashboard
# ---------------------------------------------------------------------------


class MiningDashboard(QMainWindow):
    """Live mining dashboard window."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("b3chain CPU miner -- Live Mining")
        self.resize(1400, 900)

        self._session = MiningSession()
        self._runner = MiningRunner(self)
        self._wire_runner()

        self._chart_timer = QTimer(self)
        self._chart_timer.setInterval(1000)
        self._chart_timer.timeout.connect(self._refresh_periodic)

        self._build_ui()
        self._load_settings_into_ui()
        self._set_status(STATUS_IDLE, "Idle")

    # ------------------------------------------------------------ UI build

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addWidget(self._build_top_bar())
        layout.addWidget(self._build_status_strip())
        layout.addWidget(self._build_stats_cards())

        # Middle splitter: chart (left) + last-share details (right)
        mid = QSplitter(Qt.Orientation.Horizontal)
        mid.addWidget(self._build_chart_panel())
        mid.addWidget(self._build_last_share_panel())
        mid.setStretchFactor(0, 3)
        mid.setStretchFactor(1, 2)
        layout.addWidget(mid, 2)

        # Lower splitter: per-thread (left) + recent shares (right)
        lower = QSplitter(Qt.Orientation.Horizontal)
        lower.addWidget(self._build_threads_panel())
        lower.addWidget(self._build_recent_panel())
        lower.setStretchFactor(0, 1)
        lower.setStretchFactor(1, 2)
        layout.addWidget(lower, 2)

        layout.addWidget(self._build_tabs(), 3)
        layout.addWidget(self._build_footer())

        self.setCentralWidget(central)

    def _build_top_bar(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        h = QHBoxLayout(box)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(8)

        h.addWidget(QLabel("Pool:"))
        self._pool_combo = QComboBox()
        self._pool_combo.setEditable(True)
        self._pool_combo.setMinimumWidth(360)
        self._pool_combo.addItem(DEFAULT_POOL_URL)
        h.addWidget(self._pool_combo, 2)

        h.addWidget(QLabel("User:"))
        self._user_edit = QLineEdit(DEFAULT_USER)
        self._user_edit.setMinimumWidth(220)
        h.addWidget(self._user_edit, 2)

        h.addWidget(QLabel("Pass:"))
        self._pass_edit = QLineEdit("x")
        self._pass_edit.setMinimumWidth(80)
        h.addWidget(self._pass_edit)

        h.addWidget(QLabel("Backend:"))
        self._backend_combo = QComboBox()
        self._backend_combo.addItem("CPU (Python)", BACKEND_CPU)
        # Only offer GPU when the binary actually exists on disk; we
        # leave the entry visible-but-disabled either way so the user
        # discovers the feature even when they haven't built it yet.
        self._backend_combo.addItem("GPU (CUDA)", BACKEND_GPU)
        gpu_present = gpu_miner_binary_path() is not None
        # QComboBox doesn't support per-item enable directly; if GPU is
        # missing we still let the user pick it, then surface a clear
        # error on Start. The tooltip explains the requirement.
        gpu_tip = (
            "Choose CPU (b3chain-cpuminer.py, Python) or GPU\n"
            "(b3chain-gpuminer, Rust + CUDA). The GPU backend\n"
            "needs a build of contrib/miner/b3chain-gpuminer/\n"
            "(see its README for prerequisites)."
        )
        if not gpu_present:
            gpu_tip += (
                "\n\nGPU binary is NOT detected at the expected path; "
                "choosing GPU here will fail on Start until you build it."
            )
        self._backend_combo.setToolTip(gpu_tip)
        h.addWidget(self._backend_combo)

        h.addWidget(QLabel("Threads:"))
        self._threads_spin = QSpinBox()
        self._threads_spin.setRange(1, 64)
        self._threads_spin.setValue(_default_thread_count())
        self._threads_spin.setToolTip(
            "Number of mining worker threads (CPU backend only -- ignored\n"
            "for GPU). Default is half the logical core count, which\n"
            "approximates physical cores on hyperthreaded CPUs. Going\n"
            "higher usually REDUCES aggregate hashrate because Python's\n"
            "GIL serialises the per-iteration overhead and extra threads\n"
            "just starve each other."
        )
        h.addWidget(self._threads_spin)
        # Disable the threads spinbox when GPU is selected, since the
        # GPU backend uses a single dispatcher task.
        self._backend_combo.currentIndexChanged.connect(
            lambda _i: self._threads_spin.setEnabled(
                self._backend_combo.currentData() != BACKEND_GPU
            )
        )

        h.addWidget(QLabel("UA:"))
        self._ua_edit = QLineEdit(DEFAULT_USERAGENT)
        self._ua_edit.setMinimumWidth(160)
        h.addWidget(self._ua_edit)

        self._start_btn = QPushButton("Start")
        self._start_btn.clicked.connect(self._on_start_clicked)
        h.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        h.addWidget(self._stop_btn)

        return box

    def _build_status_strip(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        h = QHBoxLayout(box)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(14)
        self._status_dot = QLabel("\u25CF")
        self._status_dot.setStyleSheet("font-size: 16px; color: #888;")
        h.addWidget(self._status_dot)
        self._status_label = QLabel("Idle")
        self._status_label.setStyleSheet("font-weight: 600;")
        h.addWidget(self._status_label)
        h.addWidget(self._sep_line())
        self._ext1_label = QLabel("ext1: -")
        h.addWidget(self._ext1_label)
        self._ext2_label = QLabel("ext2_size: -")
        h.addWidget(self._ext2_label)
        h.addWidget(self._sep_line())
        self._net_diff_label = QLabel("net_diff: -")
        h.addWidget(self._net_diff_label)
        self._share_diff_label = QLabel("share_diff: -")
        h.addWidget(self._share_diff_label)
        h.addStretch(1)
        self._job_label = QLabel("job: -")
        self._job_label.setStyleSheet("font-family: Consolas, monospace;")
        h.addWidget(self._job_label)
        return box

    def _sep_line(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep

    def _build_stats_cards(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        g = QGridLayout(box)
        g.setContentsMargins(8, 8, 8, 8)
        g.setHorizontalSpacing(20)
        g.setVerticalSpacing(2)

        self._card_hashrate = self._make_card("Hashrate", "0 H/s", big=True)
        self._card_submitted = self._make_card("Submitted", "0")
        self._card_accepted = self._make_card("Accepted", "0  (-%)")
        self._card_rejected = self._make_card("Rejected", "0")
        self._card_attempts = self._make_card("Attempts", "0")
        self._card_blocks = self._make_card("Blocks", "0")

        g.addWidget(self._card_hashrate, 0, 0, 2, 1)
        g.addWidget(self._card_submitted, 0, 1)
        g.addWidget(self._card_accepted, 0, 2)
        g.addWidget(self._card_rejected, 0, 3)
        g.addWidget(self._card_attempts, 1, 1, 1, 2)
        g.addWidget(self._card_blocks, 1, 3)
        return box

    def _make_card(self, title: str, value: str, big: bool = False) -> QWidget:
        w = QFrame()
        w.setFrameShape(QFrame.Shape.NoFrame)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        value_lbl = QLabel(value)
        font = QFont(value_lbl.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * (2.0 if big else 1.4))
        value_lbl.setFont(font)
        v.addWidget(title_lbl)
        v.addWidget(value_lbl)
        w._title = title_lbl
        w._value = value_lbl
        return w

    def _build_chart_panel(self) -> QWidget:
        box = QGroupBox("Hashrate (last 5 min)")
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 6, 6, 6)
        self._chart = HashrateChart()
        v.addWidget(self._chart, 1)
        return box

    def _build_last_share_panel(self) -> QWidget:
        box = QGroupBox("Last share")
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 6)
        self._last_share_text = QTextEdit()
        self._last_share_text.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self._last_share_text.setFont(font)
        self._last_share_text.setPlaceholderText("Waiting for first share...")
        self._last_share_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        v.addWidget(self._last_share_text, 1)
        return box

    def _build_threads_panel(self) -> QWidget:
        box = QGroupBox("Per-thread")
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 6, 6, 6)
        self._thread_table = QTableWidget(0, 4)
        self._thread_table.setHorizontalHeaderLabels(
            ["Thread", "Rate", "Attempts", "Best PoW (BE)"])
        self._thread_table.verticalHeader().setVisible(False)
        self._thread_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        h = self._thread_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self._thread_table, 1)
        return box

    def _build_recent_panel(self) -> QWidget:
        box = QGroupBox(f"Recent shares (last {RECENT_SHARES_CAP})")
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 6, 6, 6)
        self._recent_table = QTableWidget(0, 7)
        self._recent_table.setHorizontalHeaderLabels(
            ["#", "Job", "Status", "RTT (ms)", "Share diff", "Time", "Block?"])
        self._recent_table.verticalHeader().setVisible(False)
        self._recent_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        h = self._recent_table.horizontalHeader()
        for col in range(7):
            h.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self._recent_table, 1)
        return box

    def _build_tabs(self) -> QWidget:
        tabs = QTabWidget()
        # Raw stdout tab
        self._stdout_text = QTextEdit()
        self._stdout_text.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self._stdout_text.setFont(font)
        self._stdout_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._stdout_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #dcdcdc; }")
        tabs.addTab(self._stdout_text, "Raw stdout")

        # JSONL events tab
        self._jsonl_text = QTextEdit()
        self._jsonl_text.setReadOnly(True)
        self._jsonl_text.setFont(font)
        self._jsonl_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._jsonl_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #dcdcdc; }")
        tabs.addTab(self._jsonl_text, "JSONL events")

        return tabs

    def _build_footer(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        h = QHBoxLayout(box)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(14)
        self._runtime_label = QLabel("Runtime: 0.0s")
        h.addWidget(self._runtime_label)
        self._spm_label = QLabel("Shares/min: 0.0")
        h.addWidget(self._spm_label)
        self._avg_rate_label = QLabel("Avg: 0 H/s")
        h.addWidget(self._avg_rate_label)
        self._best_pow_label = QLabel("Best PoW: -")
        self._best_pow_label.setStyleSheet("font-family: Consolas, monospace;")
        h.addWidget(self._best_pow_label, 1)
        self._save_btn = QPushButton("Save Session")
        self._save_btn.clicked.connect(self._on_save_session)
        h.addWidget(self._save_btn)
        self._open_log_btn = QPushButton("Open Log")
        self._open_log_btn.clicked.connect(self._on_open_log)
        h.addWidget(self._open_log_btn)
        return box

    # ------------------------------------------------------ runner wiring

    def _wire_runner(self) -> None:
        r = self._runner
        r.started.connect(self._on_runner_started)
        r.stopped.connect(self._on_runner_stopped)
        r.failed_to_start.connect(self._on_runner_failed)
        r.stdout_line.connect(self._on_stdout_line)
        r.connected.connect(self._on_connected)
        r.subscribed.connect(self._on_subscribed)
        r.authorized.connect(self._on_authorized)
        r.set_difficulty.connect(self._on_set_difficulty)
        r.notify.connect(self._on_notify)
        r.progress.connect(self._on_progress)
        r.share.connect(self._on_share)
        r.block_found.connect(self._on_block_found)
        r.disconnected.connect(self._on_disconnected)
        r.summary.connect(self._on_summary)

    # ----------------------------------------------------- settings persist

    def _load_settings_into_ui(self) -> None:
        s = _load_settings()
        # Pool URLs
        recent = s.get("recent_pools") or []
        if not recent:
            recent = [DEFAULT_POOL_URL]
        self._pool_combo.clear()
        for url in recent:
            self._pool_combo.addItem(url)
        self._pool_combo.setCurrentText(s.get("pool_url", recent[0]))
        self._user_edit.setText(s.get("user", DEFAULT_USER))
        self._pass_edit.setText(s.get("password", "x"))
        self._threads_spin.setValue(int(s.get("threads",
                                              self._threads_spin.value())))
        self._ua_edit.setText(s.get("useragent", DEFAULT_USERAGENT))
        # Restore the backend selection if present.
        backend = s.get("backend", BACKEND_CPU)
        for i in range(self._backend_combo.count()):
            if self._backend_combo.itemData(i) == backend:
                self._backend_combo.setCurrentIndex(i)
                break
        # Sync the threads-spinbox enabled state for the loaded backend.
        self._threads_spin.setEnabled(backend != BACKEND_GPU)

    def _persist_settings(self, cfg: MiningConfig) -> None:
        s = _load_settings()
        recent = s.get("recent_pools") or []
        if cfg.pool_url in recent:
            recent.remove(cfg.pool_url)
        recent.insert(0, cfg.pool_url)
        recent = recent[:8]
        s.update({
            "pool_url": cfg.pool_url,
            "user": cfg.user,
            "password": cfg.password,
            "threads": cfg.threads,
            "useragent": cfg.useragent,
            "backend": cfg.backend,
            "recent_pools": recent,
        })
        _save_settings(s)

    def _read_config_from_ui(self) -> MiningConfig:
        return MiningConfig(
            pool_url=self._pool_combo.currentText().strip(),
            user=self._user_edit.text().strip(),
            password=self._pass_edit.text(),
            threads=self._threads_spin.value(),
            useragent=self._ua_edit.text().strip() or DEFAULT_USERAGENT,
            backend=self._backend_combo.currentData() or BACKEND_CPU,
        )

    # ---------------------------------------------------------- start/stop

    @pyqtSlot()
    def _on_start_clicked(self) -> None:
        if self._runner.is_running:
            return
        cfg = self._read_config_from_ui()
        if not cfg.pool_url or "://" not in cfg.pool_url:
            QMessageBox.warning(self, "Invalid pool URL",
                                "Pool URL must look like "
                                "stratum+tcp://host:port")
            return
        if not cfg.user:
            QMessageBox.warning(self, "Missing user",
                                "User must be non-empty.")
            return
        # Reset session for a fresh run.
        self._session = MiningSession()
        self._session.host = cfg.pool_url  # filled in fully on connect event
        self._session.user = cfg.user
        self._session.useragent = cfg.useragent
        self._session.begin()

        self._reset_widgets()
        self._persist_settings(cfg)
        self._set_status(STATUS_STARTING, f"Starting (threads={cfg.threads})")
        self._set_inputs_enabled(False)
        self._runner.start(cfg)

    @pyqtSlot()
    def _on_stop_clicked(self) -> None:
        if not self._runner.is_running:
            return
        self._set_status(STATUS_STOPPED, "Stopping...")
        self._runner.stop()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for w in (self._pool_combo, self._user_edit, self._pass_edit,
                  self._threads_spin, self._ua_edit, self._backend_combo):
            w.setEnabled(enabled)
        # When re-enabling after a stop, respect the GPU-disables-threads
        # rule. Otherwise the spinbox would unconditionally re-enable.
        if enabled:
            self._threads_spin.setEnabled(
                self._backend_combo.currentData() != BACKEND_GPU
            )
        self._start_btn.setEnabled(enabled)
        self._stop_btn.setEnabled(not enabled)

    def _reset_widgets(self) -> None:
        self._stdout_text.clear()
        self._jsonl_text.clear()
        self._last_share_text.clear()
        self._thread_table.setRowCount(0)
        self._recent_table.setRowCount(0)
        self._chart.set_samples([])
        self._update_stats_cards()
        self._ext1_label.setText("ext1: -")
        self._ext2_label.setText("ext2_size: -")
        self._net_diff_label.setText("net_diff: -")
        self._share_diff_label.setText("share_diff: -")
        self._job_label.setText("job: -")
        self._best_pow_label.setText("Best PoW: -")
        self._runtime_label.setText("Runtime: 0.0s")
        self._spm_label.setText("Shares/min: 0.0")
        self._avg_rate_label.setText("Avg: 0 H/s")

    # ----------------------------------------------------------- runner cb

    @pyqtSlot()
    def _on_runner_started(self) -> None:
        self._chart_timer.start()

    @pyqtSlot()
    def _on_runner_stopped(self) -> None:
        self._chart_timer.stop()
        self._session.end()
        self._set_inputs_enabled(True)
        # Keep status as ERROR if we set it earlier; otherwise STOPPED.
        if self._status_label.text() not in ("Error", "Failed to start"):
            self._set_status(STATUS_STOPPED,
                             f"Stopped after {self._session.runtime_s:.1f}s")
        self._refresh_periodic()  # one final update

    @pyqtSlot(str)
    def _on_runner_failed(self, msg: str) -> None:
        self._set_status(STATUS_ERROR, "Failed to start")
        self._append_stdout(f"-- ERROR: {msg} --")
        QMessageBox.critical(self, "Miner failed to start", msg)
        self._set_inputs_enabled(True)

    @pyqtSlot(str)
    def _on_stdout_line(self, line: str) -> None:
        self._append_stdout(line)

    def _append_stdout(self, line: str) -> None:
        self._stdout_text.append(line)
        sb = self._stdout_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ----- typed event handlers -------------------------------------------

    @pyqtSlot(object)
    def _on_connected(self, ev: ConnectEvent) -> None:
        self._session.host = ev.host
        self._session.port = ev.port
        self._session.use_tls = ev.use_tls
        self._session.connected = True
        self._set_status(STATUS_CONNECTED,
                         f"Connected {ev.host}:{ev.port} "
                         f"({'TLS' if ev.use_tls else 'TCP'})")

    @pyqtSlot(object)
    def _on_subscribed(self, ev: SubscribedEvent) -> None:
        self._session.on_subscribed(ev)
        self._ext1_label.setText(f"ext1: {ev.extranonce1}")
        self._ext2_label.setText(f"ext2_size: {ev.extranonce2_size}")

    @pyqtSlot(object)
    def _on_authorized(self, ev: AuthorizedEvent) -> None:
        if ev.ok:
            self._set_status(STATUS_MINING,
                             f"Mining as {ev.user}")

    @pyqtSlot(object)
    def _on_set_difficulty(self, ev: SetDifficultyEvent) -> None:
        self._session.on_set_difficulty(ev)
        self._share_diff_label.setText(
            f"share_diff: {ev.share_difficulty:g}")

    @pyqtSlot(object)
    def _on_notify(self, ev: NotifyEvent) -> None:
        self._session.on_notify(ev)
        self._net_diff_label.setText(f"net_diff: {ev.network_difficulty:g}")
        self._job_label.setText(f"job: {ev.job_id}")

    @pyqtSlot(object)
    def _on_progress(self, ev: ProgressEvent) -> None:
        self._session.on_progress(ev)
        self._update_thread_table()
        self._update_stats_cards()
        self._best_pow_label.setText(
            f"Best PoW: {self._session.threads.best_pow_be() or '-'}")

    @pyqtSlot(object)
    def _on_share(self, ev: ShareEvent) -> None:
        self._session.on_share(ev)
        if ev.network_difficulty > 0:
            self._net_diff_label.setText(
                f"net_diff: {ev.network_difficulty:g}")
        if ev.share_difficulty > 0:
            self._share_diff_label.setText(
                f"share_diff: {ev.share_difficulty:g}")
        self._prepend_recent_share(ev)
        self._render_last_share(ev)
        self._update_stats_cards()

    @pyqtSlot(object)
    def _on_block_found(self, ev: BlockFoundEvent) -> None:
        self._append_stdout(f"*** BLOCK FOUND *** job={ev.job_id} "
                            f"hash={ev.block_hash_be}")

    @pyqtSlot(object)
    def _on_disconnected(self, ev: DisconnectEvent) -> None:
        self._session.last_disconnect_reason = ev.reason
        self._session.connected = False
        # Don't move to ERROR if we initiated the stop ourselves.
        if self._runner.is_running:
            self._set_status(STATUS_STARTING,
                             f"Reconnecting... ({ev.reason})")

    @pyqtSlot(object)
    def _on_summary(self, ev: SummaryEvent) -> None:
        self._append_stdout(
            f"-- summary: runtime={ev.runtime_s:.1f}s "
            f"submitted={ev.shares_submitted} accepted={ev.shares_accepted} "
            f"rejected={ev.shares_rejected} blocks={ev.blocks_found} "
            f"avg={_fmt_rate(ev.avg_hashrate)} --")

    # ----- table updates --------------------------------------------------

    def _update_thread_table(self) -> None:
        stats = self._session.threads.all()
        self._thread_table.setRowCount(len(stats))
        for row, st in enumerate(stats):
            self._set_cell(self._thread_table, row, 0, str(st.thread))
            self._set_cell(self._thread_table, row, 1, _fmt_rate(st.rate_hps))
            self._set_cell(self._thread_table, row, 2, _fmt_int(st.attempts))
            self._set_cell(self._thread_table, row, 3, st.best_pow_be or "-")

    def _prepend_recent_share(self, ev: ShareEvent) -> None:
        # Insert at top, cap rows
        self._recent_table.insertRow(0)
        status = "ACCEPTED" if ev.accepted else "REJECTED"
        block_mark = "yes" if ev.is_block else "-"
        time_str = datetime.datetime.fromtimestamp(ev.ts).strftime("%H:%M:%S")
        self._set_cell(self._recent_table, 0, 0, str(ev.seq))
        self._set_cell(self._recent_table, 0, 1, ev.job_id, mono=True)
        item = self._set_cell(self._recent_table, 0, 2, status)
        if ev.accepted:
            item.setForeground(QColor("#1f8a3b"))
        else:
            item.setForeground(QColor("#c0383d"))
        self._set_cell(self._recent_table, 0, 3, f"{ev.rtt_ms:.1f}")
        self._set_cell(self._recent_table, 0, 4, f"{ev.share_difficulty:g}")
        self._set_cell(self._recent_table, 0, 5, time_str)
        self._set_cell(self._recent_table, 0, 6, block_mark)
        # Cap rows
        while self._recent_table.rowCount() > RECENT_SHARES_CAP:
            self._recent_table.removeRow(self._recent_table.rowCount() - 1)

    def _set_cell(self, table: QTableWidget, row: int, col: int, text: str,
                  mono: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if mono:
            font = QFont("Consolas")
            font.setStyleHint(QFont.StyleHint.Monospace)
            item.setFont(font)
        table.setItem(row, col, item)
        return item

    def _render_last_share(self, ev: ShareEvent) -> None:
        status = "ACCEPTED" if ev.accepted else "REJECTED"
        if ev.is_block:
            status += " (BLOCK!)"
        ntime_iso = ""
        try:
            ntime_iso = datetime.datetime.utcfromtimestamp(
                ev.ntime).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            ntime_iso = ""
        body = (
            f"#{ev.seq}  thread={ev.thread}  status={status}\n"
            f"job        : {ev.job_id}\n"
            f"ntime      : {ev.ntime}  ({ntime_iso})\n"
            f"nonce      : 0x{ev.nonce:08x}\n"
            f"extranonce : {ev.extranonce1}/{ev.extranonce2}\n"
            f"pow_le     : {ev.pow_hash_le}\n"
            f"pow_be     : {ev.pow_hash_be}\n"
            f"target_be  : {ev.share_target_be}\n"
            f"share_diff : {ev.share_difficulty:g}\n"
            f"net_diff   : {ev.network_difficulty:g}\n"
            f"block_hash : {ev.block_hash_be}\n"
            f"rtt        : {ev.rtt_ms:.1f} ms\n"
            f"attempts_for_job: {ev.attempts_for_job}\n"
            f"header     : {ev.header_hex}"
        )
        if ev.error:
            body += f"\nerror      : {ev.error}"
        self._last_share_text.setPlainText(body)

    def _update_stats_cards(self) -> None:
        rate = self._session.hashrate.current_rate()
        s = self._session.shares
        accept_pct = (s.accept_rate * 100.0) if s.submitted else 0.0
        self._card_hashrate._value.setText(_fmt_rate(rate))
        self._card_submitted._value.setText(_fmt_int(s.submitted))
        self._card_accepted._value.setText(
            f"{_fmt_int(s.accepted)}  ({accept_pct:.1f}%)")
        self._card_rejected._value.setText(_fmt_int(s.rejected))
        self._card_attempts._value.setText(
            _fmt_int(self._session.threads.total_attempts()))
        self._card_blocks._value.setText(_fmt_int(s.blocks))

    @pyqtSlot()
    def _refresh_periodic(self) -> None:
        # Chart + footer (called every 1s while running, plus once on stop).
        self._chart.set_samples(self._session.hashrate.chart_samples())
        runtime = self._session.runtime_s
        self._runtime_label.setText(f"Runtime: {runtime:.1f}s")
        s = self._session.shares
        spm = (s.submitted / runtime * 60.0) if runtime > 1e-3 else 0.0
        self._spm_label.setText(f"Shares/min: {spm:.2f}")
        self._avg_rate_label.setText(
            f"Avg: {_fmt_rate(self._session.hashrate.avg_rate())}")
        # Refresh JSONL events tab in chunks too.
        text = self._runner.jsonl_text()
        if text:
            cur_text = self._jsonl_text.toPlainText()
            if text != cur_text:
                self._jsonl_text.setPlainText(text)
                cur = self._jsonl_text.textCursor()
                cur.movePosition(QTextCursor.MoveOperation.End)
                self._jsonl_text.setTextCursor(cur)

    # ------------------------------------------------------------ status

    def _set_status(self, status: str, text: str) -> None:
        color = _STATUS_COLORS.get(status, "#888")
        self._status_dot.setStyleSheet(
            f"font-size: 16px; color: {color};")
        self._status_label.setText(text)

    # ---------------------------------------------------------- actions

    @pyqtSlot()
    def _on_save_session(self) -> None:
        out_dir = self._suggest_session_dir()
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose a directory to save the session under",
            os.path.dirname(out_dir))
        if not chosen:
            return
        target = os.path.join(chosen, os.path.basename(out_dir))
        try:
            _save_session(target, self._runner, self._session)
        except OSError as e:
            QMessageBox.critical(self, "Save failed",
                                 f"Could not save session: {e}")
            return
        self._append_stdout(f"-- saved session -> {target} --")
        QMessageBox.information(
            self, "Session saved",
            f"Wrote:\n  {target}\\miner-stdout.log\n"
            f"  {target}\\shares.jsonl\n"
            f"  {target}\\session-summary.json\n"
            f"  {target}\\session-summary.md")

    def _suggest_session_dir(self) -> str:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return os.path.join(THIS_DIR, f"mining-session-{stamp}")

    @pyqtSlot()
    def _on_open_log(self) -> None:
        path = self._runner.jsonl_path
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "No log",
                                    "No JSONL log yet. Start mining first.")
            return
        # Open the directory containing the temp file in Explorer (Windows)
        # or the system file manager.
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except OSError as e:
            QMessageBox.warning(self, "Open failed",
                                f"Could not open log: {e}")

    # ---------------------------------------------------------- close

    def closeEvent(self, event):
        if self._runner.is_running:
            self._append_stdout("-- closing dashboard; stopping miner --")
            self._runner.stop()
            # Wait briefly for the QProcess to die so we don't leave orphans.
            t0 = time.time()
            while self._runner.is_running and (time.time() - t0) < 3.5:
                QApplication.processEvents()
                time.sleep(0.05)
        # Drop the temp JSONL file -- the user has had a chance to Save.
        self._runner.discard_jsonl()
        super().closeEvent(event)
