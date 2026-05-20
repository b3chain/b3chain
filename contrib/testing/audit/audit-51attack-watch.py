#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[A-2] Verify the runbook-§0 alerting completion in
``contrib/monitoring/51attack-watch.py``.

This audit is pure-function: it imports the watcher module by file
path (the script has a hyphen in its name so a normal `import` won't
work) and exercises the new detectors plus the new `_LogTailer`
class against synthetic fixtures.  No b3chaind is required.

Verifies the four runbook §0 detection triggers map 1:1 to alert
kinds and that each detector's threshold semantics match the runbook
table in
[`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](../../../doc/security/RESPONSE-RUNBOOK-51ATTACK.md):

  Trigger #1 (long deep reorg, depth > 50) -> detect_long_reorg
  Trigger #2 (deep-reorg-attempt rejections, any)
                                            -> detect_deep_reorg_log
  Trigger #3 (b3pow-budget-exceeded > 100/h)
                                            -> detect_pow_budget_storm
  Trigger #4 (hashrate drop > 30% sustained > 1h)
                                            -> detect_hashrate_sustained_drop

Also exercises the inode-rotation path on `_LogTailer` to catch the
specific failure mode where logrotate would silently drop events.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
from collections import deque
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WATCHER_PATH = REPO_ROOT / "contrib" / "monitoring" / "51attack-watch.py"


def _load_watcher_module():
    """Load contrib/monitoring/51attack-watch.py by file path.

    The script has a hyphen + digit-leading name, so `import` cannot
    find it.  We compile + exec into a fresh module namespace and
    register it in sys.modules so `dataclasses.dataclass` can
    introspect `sys.modules[cls.__module__]` (Python 3.14 needs this
    for `_is_type` lookups inside the dataclass decorator).
    """
    import types  # local import to keep top-level deps minimal
    module_name = "watcher_under_test"
    src = WATCHER_PATH.read_text(encoding="utf-8")
    mod = types.ModuleType(module_name)
    mod.__file__ = str(WATCHER_PATH)
    mod.__dict__["__name__"] = module_name
    sys.modules[module_name] = mod
    try:
        code = compile(src, str(WATCHER_PATH), "exec")
        exec(code, mod.__dict__)
    except Exception:
        # Roll back the sys.modules registration if anything failed
        # so a re-run sees a clean slate.
        sys.modules.pop(module_name, None)
        raise
    return mod


# ---------- test harness ------------------------------------------------------

_FAILURES: list[str] = []
_PASSES: int = 0


def _ok(name: str) -> None:
    global _PASSES
    _PASSES += 1
    print(f"  [PASS] {name}")


def _fail(name: str, reason: str) -> None:
    _FAILURES.append(f"{name}: {reason}")
    print(f"  [FAIL] {name}: {reason}")


def _check(cond: bool, name: str, reason: str = "") -> None:
    if cond:
        _ok(name)
    else:
        _fail(name, reason or "condition false")


# ---------- tests -------------------------------------------------------------

def test_detect_deep_reorg_log_emits_on_match(mod) -> None:
    """Trigger #2: any line containing `deep-reorg-attempt` -> alert."""
    name = "test_detect_deep_reorg_log_emits_on_match"
    lines = [
        "2026-05-19T20:00:00 UpdateTip: bestblock height=12345",
        "2026-05-19T20:00:01 ERROR: peer=42 Misbehaving: deep-reorg-attempt depth=205",
        "2026-05-19T20:00:02 net: connection accepted",
    ]
    out = mod.detect_deep_reorg_log(lines, now=1_700_000_000.0)
    _check(len(out) == 1, name + "/count", f"got {len(out)} alerts, want 1")
    if out:
        _check(out[0]["kind"] == "deep_reorg_log",
               name + "/kind", f"got {out[0]['kind']}")
        _check(out[0]["severity"] == "critical",
               name + "/severity", f"got {out[0]['severity']}")
        _check("signature" in out[0] and len(out[0]["signature"]) > 0,
               name + "/signature", "missing signature")


def test_detect_deep_reorg_log_ignores_unrelated(mod) -> None:
    """1 kB of noise without the token -> zero alerts."""
    name = "test_detect_deep_reorg_log_ignores_unrelated"
    noise = ["2026-05-19T20:00:00 net: ping/pong"] * 50
    out = mod.detect_deep_reorg_log(noise, now=1_700_000_000.0)
    _check(out == [], name, f"got {len(out)} unexpected alerts")


def test_detect_pow_budget_storm_below_threshold(mod) -> None:
    """99 events / 3600s -> no alert (threshold is > 100)."""
    name = "test_detect_pow_budget_storm_below_threshold"
    now = 1_700_000_000.0
    ts = deque(now - i for i in range(99))
    out = mod.detect_pow_budget_storm(ts, threshold=100,
                                      window_sec=3600.0, now=now)
    _check(out == [], name, f"got {len(out)} unexpected alerts")


def test_detect_pow_budget_storm_above_threshold(mod) -> None:
    """150 events / 3600s -> warning; 401 events -> critical."""
    name_w = "test_detect_pow_budget_storm_above_threshold/warning"
    name_c = "test_detect_pow_budget_storm_above_threshold/critical"
    now = 1_700_000_000.0
    ts = deque(now - i for i in range(150))
    out = mod.detect_pow_budget_storm(ts, threshold=100,
                                      window_sec=3600.0, now=now)
    _check(len(out) == 1, name_w + "/count", f"got {len(out)}")
    if out:
        _check(out[0]["severity"] == "warning",
               name_w + "/severity", f"got {out[0]['severity']}")
        _check(out[0]["kind"] == "pow_budget_storm",
               name_w + "/kind", f"got {out[0]['kind']}")
    ts = deque(now - i for i in range(401))
    out = mod.detect_pow_budget_storm(ts, threshold=100,
                                      window_sec=3600.0, now=now)
    _check(len(out) == 1, name_c + "/count", f"got {len(out)}")
    if out:
        _check(out[0]["severity"] == "critical",
               name_c + "/severity", f"got {out[0]['severity']}")


def test_detect_pow_budget_storm_window_slides(mod) -> None:
    """200 events from 65 min ago -> no alert (outside 1h window)."""
    name = "test_detect_pow_budget_storm_window_slides"
    now = 1_700_000_000.0
    too_old = now - 3601.0  # one second beyond the 3600s window
    ts = deque([too_old - i for i in range(200)])
    out = mod.detect_pow_budget_storm(ts, threshold=100,
                                      window_sec=3600.0, now=now)
    _check(out == [], name + "/count", f"got {len(out)} unexpected alerts")
    _check(len(ts) == 0,
           name + "/trim", f"deque should be drained, len={len(ts)}")


def test_detect_long_reorg_threshold(mod) -> None:
    """branchlen 49 -> none; 50 -> warning; 100 -> critical."""
    name = "test_detect_long_reorg_threshold"
    tips_49 = [{"hash": "a" * 64, "height": 100, "branchlen": 49,
                "status": "valid-fork"}]
    tips_50 = [{"hash": "b" * 64, "height": 100, "branchlen": 50,
                "status": "valid-fork"}]
    tips_100 = [{"hash": "c" * 64, "height": 150, "branchlen": 100,
                 "status": "valid-fork"}]
    tips_active = [{"hash": "d" * 64, "height": 200, "branchlen": 60,
                    "status": "active"}]
    _check(mod.detect_long_reorg(tips_49, threshold=50) == [],
           name + "/below", "branchlen=49 should not alert")
    out_50 = mod.detect_long_reorg(tips_50, threshold=50)
    _check(len(out_50) == 1 and out_50[0]["severity"] == "warning",
           name + "/at-threshold", f"got {out_50}")
    out_100 = mod.detect_long_reorg(tips_100, threshold=50)
    _check(len(out_100) == 1 and out_100[0]["severity"] == "critical",
           name + "/2x-threshold", f"got {out_100}")
    _check(mod.detect_long_reorg(tips_active, threshold=50) == [],
           name + "/active-tip-ignored", "active tip should be skipped")


def test_detect_hashrate_sustained_drop_short_dip(mod) -> None:
    """A 30-min dip should NOT fire the 1h sustained-drop alert."""
    name = "test_detect_hashrate_sustained_drop_short_dip"
    now = 1_700_000_000.0
    samples: deque = deque()
    # 24h of healthy samples at 100 H/s, then 30 min of 20 H/s.
    for i in range(24 * 60):
        samples.append((now - (24 * 3600) + i * 60, 100.0))
    for i in range(30):
        samples.append((now - (30 * 60) + i * 60, 20.0))
    out = mod.detect_hashrate_sustained_drop(
        samples, drop_frac=0.70, window_sec=3600.0, now=now
    )
    _check(out == [], name, f"got {len(out)} unexpected alerts")


def test_detect_hashrate_sustained_drop_sustained(mod) -> None:
    """A 65-min dip at 25% of peak should fire a critical alert."""
    name = "test_detect_hashrate_sustained_drop_sustained"
    now = 1_700_000_000.0
    samples: deque = deque()
    # 22 h of healthy samples at 100 H/s, then 130 min of 25 H/s
    # (> 2x the 60-min sustained window -> critical).
    for i in range(22 * 60):
        samples.append((now - (24 * 3600) + i * 60, 100.0))
    for i in range(130):
        samples.append((now - (130 * 60) + i * 60, 25.0))
    out = mod.detect_hashrate_sustained_drop(
        samples, drop_frac=0.70, window_sec=3600.0, now=now
    )
    _check(len(out) == 1, name + "/count", f"got {len(out)}")
    if out:
        _check(out[0]["kind"] == "hashrate_sustained_drop",
               name + "/kind", f"got {out[0]['kind']}")
        _check(out[0]["severity"] == "critical",
               name + "/severity", f"got {out[0]['severity']}")


def test_log_tailer_inode_rotation(mod) -> None:
    """Write 3 lines, rotate the file, write 2 more; assert all 5 read.

    Linux-only: relies on POSIX `rename`-on-open semantics that
    logrotate / mv use in production on seed1.  Windows refuses to
    rename a file that another process has open (WinError 32), which
    is a test-environment limitation, not a defect in the tailer.
    """
    name = "test_log_tailer_inode_rotation"
    if os.name == "nt":
        print(f"  [SKIP] {name}: not supported on Windows "
              "(POSIX rename-on-open; production target is Linux seed1)")
        return
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "debug.log"
        # Pre-populate with a line that should NOT be replayed
        # (the tailer seeks to EOF on startup).
        path.write_text("OLD line, should be skipped\n", encoding="utf-8")
        tailer = mod._LogTailer(path)

        with path.open("a", encoding="utf-8") as f:
            f.write("line A: deep-reorg-attempt depth=205\n")
            f.write("line B: regular\n")
            f.write("line C: b3pow-budget-exceeded peer=7\n")
        first_batch = tailer.iter_new_lines()
        _check(len(first_batch) == 3,
               name + "/pre-rotate", f"got {len(first_batch)} lines, want 3")
        # Simulate logrotate: rename + create new empty file at the
        # same path.  inode of the new file is different.
        rotated = Path(td) / "debug.log.1"
        os.rename(path, rotated)
        # Create the new (empty) file in place; this is what
        # `copytruncate`-style or `create`-style logrotate produces.
        path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write("post-rotate line 1: deep-reorg-attempt depth=300\n")
            f.write("post-rotate line 2: regular\n")
        second_batch = tailer.iter_new_lines()
        _check(len(second_batch) == 2,
               name + "/post-rotate",
               f"got {len(second_batch)} lines, want 2")
        all_lines = first_batch + second_batch
        deep_count = sum(1 for ln in all_lines
                         if "deep-reorg-attempt" in ln)
        _check(deep_count == 2,
               name + "/markers",
               f"got {deep_count} 'deep-reorg-attempt' lines, want 2")
        tailer.close()


def test_log_tailer_partial_line_buffer(mod) -> None:
    """A line written in two halves across two polls is read as one line."""
    name = "test_log_tailer_partial_line_buffer"
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "debug.log"
        path.write_text("", encoding="utf-8")
        tailer = mod._LogTailer(path)
        with path.open("a", encoding="utf-8") as f:
            f.write("partial line head, ")  # no newline yet
            f.flush()
        first = tailer.iter_new_lines()
        _check(first == [], name + "/no-line-yet",
               f"got {first}, want []")
        with path.open("a", encoding="utf-8") as f:
            f.write("tail: deep-reorg-attempt depth=210\n")
        second = tailer.iter_new_lines()
        _check(len(second) == 1, name + "/joined",
               f"got {len(second)} lines, want 1")
        _check("deep-reorg-attempt" in (second[0] if second else ""),
               name + "/marker-present",
               "expected marker not present in joined line")
        tailer.close()


def test_detect_pow_budget_storm_dedup_bucket_stable(mod) -> None:
    """Two calls inside the same window with same count -> same bucket."""
    name = "test_detect_pow_budget_storm_dedup_bucket_stable"
    now = 1_700_000_000.0
    ts = deque(now - i for i in range(180))
    out1 = mod.detect_pow_budget_storm(ts, threshold=100,
                                       window_sec=3600.0, now=now)
    ts = deque(now - i for i in range(185))
    out2 = mod.detect_pow_budget_storm(ts, threshold=100,
                                       window_sec=3600.0, now=now)
    if out1 and out2:
        _check(out1[0]["bucket"] == out2[0]["bucket"],
               name + "/same-bucket",
               f"buckets diverged: {out1[0]['bucket']} vs "
               f"{out2[0]['bucket']}")
    else:
        _fail(name, "expected at least one alert from each call")


# ---------- driver ------------------------------------------------------------

def main() -> int:
    print("[audit-51attack-watch] loading watcher module ...")
    try:
        mod = _load_watcher_module()
    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"  [FAIL] could not load {WATCHER_PATH}: {e}")
        traceback.print_exc()
        return 1
    print("  [OK]")
    print()

    tests = [
        test_detect_deep_reorg_log_emits_on_match,
        test_detect_deep_reorg_log_ignores_unrelated,
        test_detect_pow_budget_storm_below_threshold,
        test_detect_pow_budget_storm_above_threshold,
        test_detect_pow_budget_storm_window_slides,
        test_detect_long_reorg_threshold,
        test_detect_hashrate_sustained_drop_short_dip,
        test_detect_hashrate_sustained_drop_sustained,
        test_log_tailer_inode_rotation,
        test_log_tailer_partial_line_buffer,
        test_detect_pow_budget_storm_dedup_bucket_stable,
    ]
    for fn in tests:
        print(f"[audit-51attack-watch] {fn.__name__}")
        try:
            fn(mod)
        except Exception as e:  # noqa: BLE001
            _fail(fn.__name__, f"raised {type(e).__name__}: {e}")
        print()

    print("=" * 72)
    print(f"audit-51attack-watch: {_PASSES} checks passed, "
          f"{len(_FAILURES)} failures")
    if _FAILURES:
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
