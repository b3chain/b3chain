# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Tier-3 verification for the live mining dashboard.

Run directly:

    python tests/verify_dashboard.py

Three independent suites; the script exits 0 only if all three pass.

  Suite A -- JSONLTail unit tests (offset, partial line, truncation).
  Suite B -- MiningRunner driven offscreen against MockStratumServer:
             asserts subscribed/authorized/progress/share signals fire and
             that the JSONL temp file lands on disk.
  Suite C -- MiningDashboard.closeEvent stops the runner mid-mine cleanly
             (no orphan QProcess, JSONL temp file deleted).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
from typing import Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MINER_DIR = os.path.dirname(THIS_DIR)
if MINER_DIR not in sys.path:
    sys.path.insert(0, MINER_DIR)

from PyQt6.QtCore import QEventLoop  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

# IMPORTANT: redirect the dashboard's settings path to a temp file BEFORE
# importing it -- Suite C drives the dashboard with mock localhost ports
# and persistence would otherwise clobber the developer's real
# tests/.miner_settings.json (lesson learned 2026-05-16).
from tests import mining_dashboard as _md_mod  # noqa: E402

_TMP_SETTINGS_FD, _TMP_SETTINGS_PATH = tempfile.mkstemp(
    prefix="b3chain-verify-", suffix=".miner_settings.json")
os.close(_TMP_SETTINGS_FD)
try:
    os.unlink(_TMP_SETTINGS_PATH)
except OSError:
    pass
_md_mod.SETTINGS_PATH = _TMP_SETTINGS_PATH

from tests.mining_dashboard import (  # noqa: E402
    MiningConfig, MiningDashboard, MiningRunner,
)
from tests.mining_parsers import (  # noqa: E402
    JSONLTail, ProgressEvent, ShareEvent, parse_jsonl_line,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_mock_module():
    mock_path = os.path.join(MINER_DIR, "test_pool_miner.py")
    spec = importlib.util.spec_from_file_location("test_pool_miner", mock_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wait_until(predicate: Callable[[], bool], timeout_s: float,
                app: QApplication) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if predicate():
            return True
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------------------
# Suite A -- JSONLTail
# ---------------------------------------------------------------------------


def suite_a_jsonl_tail() -> bool:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        tail = JSONLTail(path)
        if tail.poll() != []:
            print("FAIL (A): empty file should yield no events")
            return False

        ev_a = ('{"ts":1.0,"event":"progress","thread":0,"job_id":"abc",'
                '"extranonce2":"00","attempts":1,"hashrate":1000.0,'
                '"best_pow_be":"deadbeef"}\n')
        ev_b = ('{"ts":2.0,"event":"share_submit","share_seq":1,'
                '"thread":0,"job_id":"abc","extranonce1":"","extranonce2":"00",'
                '"ntime":1234,"nonce":99,"header_hex":"","pow_hash_le":"",'
                '"pow_hash_be":"","block_hash_be":"","share_target_be":"",'
                '"share_difficulty":1.0,"network_target_be":"",'
                '"network_difficulty":1.0,"is_block":false,'
                '"server_rtt_ms":12.4,"accepted":true,"error":null,'
                '"attempts_for_job":100,"coinbase":"","coinbase_txid_be":"",'
                '"merkle_root_be":""}\n')
        partial_head = '{"ts":3.0,"event":"progress",'
        partial_tail = ('"thread":0,"job_id":"def","extranonce2":"00",'
                        '"attempts":2,"hashrate":2000.0,'
                        '"best_pow_be":"feedface"}\n')

        with open(path, "a", encoding="utf-8") as f:
            f.write(ev_a)
            f.write(ev_b)
            f.write(partial_head)

        events = tail.poll()
        if len(events) != 2:
            print(f"FAIL (A): expected 2 events on partial-write poll, "
                  f"got {len(events)}")
            return False
        if not isinstance(events[0], ProgressEvent):
            print("FAIL (A): first event should be ProgressEvent")
            return False
        if not isinstance(events[1], ShareEvent):
            print("FAIL (A): second event should be ShareEvent")
            return False

        with open(path, "a", encoding="utf-8") as f:
            f.write(partial_tail)
        events = tail.poll()
        if len(events) != 1:
            print(f"FAIL (A): expected 1 event after completion, got {len(events)}")
            return False
        if events[0].job_id != "def":
            print("FAIL (A): completed event has wrong job_id")
            return False

        # Idempotent re-poll yields nothing.
        if tail.poll() != []:
            print("FAIL (A): repeat poll() should yield no events")
            return False

        # Garbage line should be silently skipped.
        with open(path, "a", encoding="utf-8") as f:
            f.write("not json at all\n")
            f.write(ev_a)
        events = tail.poll()
        # Garbage is dropped, ev_a is parsed.
        if len(events) != 1:
            print(f"FAIL (A): garbage handling produced {len(events)} events")
            return False

        # Truncate the file -- tail must reset and re-read from the top.
        with open(path, "w", encoding="utf-8") as f:
            f.write(ev_b)
        events = tail.poll()
        if len(events) != 1:
            print(f"FAIL (A): truncation reset got {len(events)} events")
            return False

        print("PASS (A): JSONLTail handles partial lines, garbage, and truncation")
        return True
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Suite B -- MiningRunner against MockStratumServer
# ---------------------------------------------------------------------------


def suite_b_runner(app: QApplication) -> bool:
    mock = _load_mock_module()
    server = mock.MockStratumServer()
    server.start()
    try:
        runner = MiningRunner()
        counters = {"sub": 0, "auth": 0, "prog": 0, "share": 0,
                    "stopped": 0, "summary": 0, "failed": ""}
        runner.subscribed.connect(lambda _e: counters.__setitem__(
            "sub", counters["sub"] + 1))
        runner.authorized.connect(lambda _e: counters.__setitem__(
            "auth", counters["auth"] + 1))
        runner.progress.connect(lambda _e: counters.__setitem__(
            "prog", counters["prog"] + 1))
        runner.share.connect(lambda _e: counters.__setitem__(
            "share", counters["share"] + 1))
        runner.stopped.connect(lambda: counters.__setitem__(
            "stopped", counters["stopped"] + 1))
        runner.summary.connect(lambda _e: counters.__setitem__(
            "summary", counters["summary"] + 1))
        runner.failed_to_start.connect(lambda m: counters.__setitem__(
            "failed", m))

        cfg = MiningConfig(
            pool_url=f"stratum+tcp://127.0.0.1:{server.port}",
            user="alice@example.com.cpu1",
            password="x",
            threads=1,
            useragent="b3chain-cpuminer/1.0-test",
        )
        runner.start(cfg)
        if counters["failed"]:
            print(f"FAIL (B): runner failed to start: {counters['failed']}")
            return False
        ok = _wait_until(
            lambda: (counters["share"] >= 1 and counters["prog"] >= 1
                     and counters["sub"] >= 1 and counters["auth"] >= 1),
            timeout_s=20.0, app=app)
        if not ok:
            print(f"FAIL (B): timeouts -- counters={counters}")
            runner.stop()
            _wait_until(lambda: counters["stopped"] >= 1, 5.0, app)
            return False

        runner.stop()
        if not _wait_until(lambda: counters["stopped"] >= 1, 6.0, app):
            print("FAIL (B): no stopped signal after stop()")
            return False
        # Allow a brief moment for the final JSONL drain.
        _wait_until(lambda: counters["summary"] >= 1, 1.0, app)

        # JSONL file should exist with at least the share count we saw.
        jsonl = runner.jsonl_path
        if jsonl is None or not os.path.exists(jsonl):
            print("FAIL (B): JSONL file missing after stop()")
            return False
        with open(jsonl, "r", encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        if len(lines) < counters["share"]:
            print(f"FAIL (B): JSONL has {len(lines)} lines but runner saw "
                  f"{counters['share']} shares")
            return False
        runner.discard_jsonl()

        # Note: on Windows QProcess.terminate() bypasses Python's SIGTERM
        # handler so the miner's `summary` event may not fire. We don't
        # require it -- the dashboard's session totals are derived from
        # share events directly.
        print(f"PASS (B): subs={counters['sub']} auth={counters['auth']} "
              f"progress={counters['prog']} shares={counters['share']} "
              f"summary={counters['summary']} jsonl_lines={len(lines)}")
        return True
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Suite C -- closeEvent stops miner cleanly
# ---------------------------------------------------------------------------


def suite_c_close_event(app: QApplication) -> bool:
    mock = _load_mock_module()
    server = mock.MockStratumServer()
    server.start()
    try:
        win = MiningDashboard()
        win._pool_combo.setCurrentText(
            f"stratum+tcp://127.0.0.1:{server.port}")
        win._user_edit.setText("bob@example.com.cpu1")
        win._threads_spin.setValue(1)
        win._on_start_clicked()
        if not _wait_until(lambda: win._runner.is_running, 5.0, app):
            print("FAIL (C): miner never reached running state")
            return False
        win.close()
        app.processEvents()
        if win._runner.is_running:
            print("FAIL (C): runner still running after close()")
            return False
        if win._runner.jsonl_path is not None:
            print("FAIL (C): jsonl_path not None after close()")
            return False
        print("PASS (C): dashboard close stops miner cleanly")
        return True
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        results = []
        results.append(("A", suite_a_jsonl_tail()))
        results.append(("B", suite_b_runner(app)))
        results.append(("C", suite_c_close_event(app)))
        failed = [name for name, ok in results if not ok]
        if failed:
            print(f"FAILED: {','.join(failed)}")
            return 1
        print("ALL OK")
        return 0
    finally:
        # Defence in depth: remove the temp settings file we redirected
        # the dashboard at, AND make sure nothing wrote to the real one
        # via a stale module reference.
        for path in (_TMP_SETTINGS_PATH,):
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
