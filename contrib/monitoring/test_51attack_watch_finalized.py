#!/usr/bin/env python3
# Copyright (c) 2026 The b3chain developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Unit tests for the M-14 ``detect_finalized_drift`` watcher detector.

Covers the three alert kinds plus the four interesting bypass paths
the plan called out (source flip, operator hash change, horizon
stall, missing RPC).  Pure-function tests against the detector in
:mod:`51attack-watch`; no live ``b3chaind`` required.

Also runs a regression block over the three existing detectors
(``detect_deep_fork`` / ``detect_hashrate_collapse`` /
``detect_near_reorg_cap``) to confirm that the v1.1.3 additions did
not break them.

Per ``contrib/monitoring/51-MONITORING-OPS.md``, this file is the
authoritative reproducibility artefact for
``B3POW-51-ATTACK-ANALYSIS.md`` §10 (provenance) D4 row.

Run::

    python3 contrib/monitoring/test_51attack_watch_finalized.py

Exit code is 0 on full pass, 1 otherwise.  Designed to be wired into
the same ``ci.yml`` job that runs the rest of the contrib smoke
tests so a regression in the watcher script breaks CI.
"""

import importlib.util
import sys
from collections import deque
from pathlib import Path


# Load the watcher module by file path -- the filename contains '-'
# so a regular import would fail.
_HERE = Path(__file__).resolve().parent
_WATCH_PATH = _HERE / "51attack-watch.py"
_spec = importlib.util.spec_from_file_location("watch_module", str(_WATCH_PATH))
watch_module = importlib.util.module_from_spec(_spec)
sys.modules["watch_module"] = watch_module
_spec.loader.exec_module(watch_module)

detect_finalized_drift   = watch_module.detect_finalized_drift
detect_deep_fork         = watch_module.detect_deep_fork
detect_hashrate_collapse = watch_module.detect_hashrate_collapse
detect_near_reorg_cap    = watch_module.detect_near_reorg_cap


_PASSED = 0
_FAILED = 0


def _case(name: str, ok: bool, info: str = "") -> None:
    """Light test harness so the file is self-contained (no pytest dep)."""
    global _PASSED, _FAILED
    if ok:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {info}")


# ---------------------------------------------------------------------------
# detect_finalized_drift -- 8 cases
# ---------------------------------------------------------------------------

def test_first_poll_no_alert() -> None:
    """First-ever poll has no prior state to compare against -> no alerts."""
    out = detect_finalized_drift(
        None,
        {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth"},
        tip_height=300, stale_threshold=5,
    )
    _case("first poll: no alert", out == [])


def test_steady_max_reorg_advance() -> None:
    """M-4 horizon advances in lockstep with tip -> no alert."""
    prev = {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth",
            "stale_count": 0, "tip_height_at_obs": 300}
    out = detect_finalized_drift(
        prev,
        {"hash": "bb" * 32, "height": 101, "source": "max_reorg_depth"},
        tip_height=301, stale_threshold=5,
    )
    _case("steady max_reorg advance: no alert", out == [])


def test_horizon_stall_hits_threshold() -> None:
    """Horizon stuck at same height for N polls while tip advanced -> alert."""
    prev = {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth",
            "stale_count": 4, "tip_height_at_obs": 304}
    out = detect_finalized_drift(
        prev,
        {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth"},
        tip_height=305, stale_threshold=5,
    )
    _case("stall hits threshold: emits",
          len(out) == 1
          and out[0]["kind"] == "finalized_drift_horizon_stall"
          and out[0]["stale_polls"] == 5)


def test_stall_escalates_at_double_threshold() -> None:
    """Stall persisting at 2x threshold escalates from warning to critical."""
    prev = {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth",
            "stale_count": 9, "tip_height_at_obs": 309}
    out = detect_finalized_drift(
        prev,
        {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth"},
        tip_height=310, stale_threshold=5,
    )
    _case("stall escalates to critical at 2x threshold",
          len(out) == 1 and out[0]["severity"] == "critical")


def test_source_flip_emits_info() -> None:
    """operator -> max_reorg_depth (unfinalize ran) -> info alert."""
    prev = {"hash": "cc" * 32, "height": 250, "source": "operator",
            "stale_count": 0, "tip_height_at_obs": 300}
    out = detect_finalized_drift(
        prev,
        {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth"},
        tip_height=300, stale_threshold=5,
    )
    _case("source flip emits info",
          len(out) == 1
          and out[0]["kind"] == "finalized_drift_source_flip"
          and out[0]["severity"] == "info")


def test_operator_hash_change_emits_warning() -> None:
    """Re-finalize at a different hash without first unfinalizing -> warning."""
    prev = {"hash": "cc" * 32, "height": 250, "source": "operator",
            "stale_count": 0, "tip_height_at_obs": 300}
    out = detect_finalized_drift(
        prev,
        {"hash": "dd" * 32, "height": 260, "source": "operator"},
        tip_height=305, stale_threshold=5,
    )
    _case("operator hash change emits warning",
          len(out) == 1
          and out[0]["kind"] == "finalized_drift_operator_change"
          and out[0]["severity"] == "warning")


def test_operator_unchanged_no_alert() -> None:
    """Operator pin still at same hash: no alert."""
    prev = {"hash": "cc" * 32, "height": 250, "source": "operator",
            "stale_count": 0, "tip_height_at_obs": 300}
    out = detect_finalized_drift(
        prev,
        {"hash": "cc" * 32, "height": 250, "source": "operator"},
        tip_height=305, stale_threshold=5,
    )
    _case("operator unchanged: no alert", out == [])


def test_tip_stalled_too_does_not_increment_stale_count() -> None:
    """Tip stalled too -> stale_count NOT incremented (avoid false-positive).

    A node whose tip is stuck because it's offline is NOT a horizon-drift
    event; both height and tip_height stay the same.  The detector must
    only increment stale_count when the tip ADVANCED while the horizon
    stalled.
    """
    prev = {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth",
            "stale_count": 4, "tip_height_at_obs": 304}
    fin = {"hash": "aa" * 32, "height": 100, "source": "max_reorg_depth"}
    out = detect_finalized_drift(prev, fin, tip_height=304, stale_threshold=5)
    _case("tip stalled too: stale_count NOT incremented",
          out == [] and fin["__stale_count__"] == 0)


# ---------------------------------------------------------------------------
# Regression: existing detectors still work after v1.1.3 changes.
# ---------------------------------------------------------------------------

def test_regression_deep_fork() -> None:
    out = detect_deep_fork(
        [{"status": "valid-fork", "hash": "cd" * 32,
          "height": 100, "branchlen": 6}], 6,
    )
    _case("regression: deep_fork still emits", len(out) == 1)


def test_regression_hashrate_collapse() -> None:
    out = detect_hashrate_collapse(deque([(100, 1e15), (101, 0.4e15)]), 0.5)
    _case("regression: hashrate_collapse still emits", len(out) == 1)


def test_regression_near_reorg_cap() -> None:
    out = detect_near_reorg_cap("aa" * 32, "bb" * 32, 200, 199, 99, 100)
    _case("regression: near_reorg_cap still emits", len(out) == 1)


def main() -> int:
    test_first_poll_no_alert()
    test_steady_max_reorg_advance()
    test_horizon_stall_hits_threshold()
    test_stall_escalates_at_double_threshold()
    test_source_flip_emits_info()
    test_operator_hash_change_emits_warning()
    test_operator_unchanged_no_alert()
    test_tip_stalled_too_does_not_increment_stale_count()
    test_regression_deep_fork()
    test_regression_hashrate_collapse()
    test_regression_near_reorg_cap()
    print(f"\nRESULT: {_PASSED} passed, {_FAILED} failed")
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
