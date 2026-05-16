# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Test catalogue + execution glue for the GUI.

Each TestCase subclass wraps either:

  * a Python callable (BuiltinTest)              -> runs in a worker QThread
  * a subprocess command (SubprocessTest)        -> runs as a QProcess

so the UI can:

  * stream stdout/stderr live to the output pane
  * map the (return code, captured output) to a TestResult via a per-test extractor
  * cancel a running test cleanly

The TestRegistry exposes the canonical ordered list of 9 tests. The UI
calls registry.update_enabled_state(probe) after every capability refresh
so rows with missing prereqs go grey.
"""

from __future__ import annotations

import dataclasses
import os
import re
import sys
import time
from typing import Callable, List, Optional, Sequence, Tuple

from . import capability_check
from .capability_check import CapabilityProbe


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
ERROR = "ERROR"
RUNNING = "RUNNING"
PENDING = "PENDING"


@dataclasses.dataclass
class TestResult:
    status: str = PENDING       # PASS | FAIL | SKIP | ERROR | RUNNING | PENDING
    metric: str = ""
    detail: str = ""
    started_at: float = 0.0
    duration_s: float = 0.0
    stdout_tail: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in (PASS, FAIL, SKIP, ERROR)


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------


class TestCase:
    """Abstract base. Concrete subclasses override `run()` or implement
    SubprocessTest's `command()` + `result_extractor`."""

    def __init__(
        self,
        ident: int,
        name: str,
        description: str,
        prereqs: Sequence[str] = (),
        estimated_seconds: float = 1.0,
        opt_in: bool = False,
    ) -> None:
        self.id = ident
        self.name = name
        self.description = description
        self.prereqs = list(prereqs)
        self.estimated_seconds = estimated_seconds
        self.opt_in = opt_in
        self.enabled = True
        self.disabled_reason = ""

    def update_enabled_state(self, probe: CapabilityProbe) -> None:
        missing = probe.missing(self.prereqs)
        if missing:
            self.enabled = False
            self.disabled_reason = f"missing: {', '.join(missing)}"
        else:
            self.enabled = True
            self.disabled_reason = ""


class SubprocessTest(TestCase):
    """A test invoked as `python <args>` (or any executable + args).

    The UI runs it through QProcess and pipes stdout into the live pane.
    `result_extractor(rc, captured_text)` maps the run to a TestResult.
    """

    def __init__(
        self,
        ident: int,
        name: str,
        description: str,
        argv: Sequence[str],
        result_extractor: Callable[[int, str], Tuple[str, str, str]],
        prereqs: Sequence[str] = (),
        estimated_seconds: float = 1.0,
        opt_in: bool = False,
        cwd: Optional[str] = None,
    ) -> None:
        super().__init__(ident, name, description, prereqs,
                         estimated_seconds, opt_in)
        self.argv = list(argv)
        self.result_extractor = result_extractor
        self.cwd = cwd


class BuiltinTest(TestCase):
    """A test implemented as a Python callable taking an emit(line) callback,
    returning (passed: bool, metric: str). The UI runs it in a QThread."""

    def __init__(
        self,
        ident: int,
        name: str,
        description: str,
        runner: Callable[[Callable[[str], None]], Tuple[bool, str]],
        prereqs: Sequence[str] = (),
        estimated_seconds: float = 1.0,
        opt_in: bool = False,
    ) -> None:
        super().__init__(ident, name, description, prereqs,
                         estimated_seconds, opt_in)
        self.runner = runner


# ---------------------------------------------------------------------------
# Result extractors for the subprocess tests
# ---------------------------------------------------------------------------


def _extract_env_check(rc: int, text: str) -> Tuple[str, str, str]:
    """Test 1 (builtin) -- environment status from probe."""
    return (PASS if rc == 0 else FAIL, "env", "")


def _extract_argparse_mutex(rc: int, text: str) -> Tuple[str, str, str]:
    """Test 3 -- expects rc=2 AND 'mutually exclusive' (or 'cannot be used')
    in stderr. argparse's default for mutex violations is rc=2."""
    msg = text.lower()
    has_msg = ("mutually exclusive" in msg
               or "cannot be used" in msg
               or "not allowed with" in msg)
    if rc == 2 and has_msg:
        return PASS, "rc=2 mutex msg", ""
    return FAIL, f"rc={rc}", text[-300:]


_RATE_RE = re.compile(r"Rate:\s*([\d,]+)\s*H/s", re.IGNORECASE)


def _extract_benchmark(rc: int, text: str) -> Tuple[str, str, str]:
    """Test 4 -- parses 'Rate: X,XXX,XXX H/s'. PASS if rc==0 AND rate >= 200_000."""
    if rc != 0:
        return FAIL, f"rc={rc}", text[-300:]
    m = _RATE_RE.search(text)
    if not m:
        return FAIL, "no Rate line", text[-300:]
    rate = int(m.group(1).replace(",", ""))
    if rate >= 200_000:
        if rate >= 1_000_000:
            metric = f"{rate/1_000_000:.2f} MH/s"
        else:
            metric = f"{rate/1_000:.1f} kH/s"
        return PASS, metric, ""
    return FAIL, f"{rate} H/s (<200kH/s)", text[-300:]


def _extract_mock_e2e(rc: int, text: str) -> Tuple[str, str, str]:
    """Test 5 -- mock-pool E2E. PASS if rc==0 AND 'PASS:' AND 'BLAKE3d-verified'."""
    if rc != 0:
        return FAIL, f"rc={rc}", text[-300:]
    if "PASS:" not in text:
        return FAIL, "no PASS line", text[-300:]
    if "BLAKE3d-verified" not in text and "BLAKE3d verified" not in text:
        return FAIL, "no BLAKE3d-verified", text[-300:]
    # Try to extract "submitted N shares".
    m = re.search(r"submitted\s+(\d+)\s+shares", text)
    if m:
        return PASS, f"{m.group(1)}/{m.group(1)} shares", ""
    return PASS, "shares verified", ""


_SOLO_REGTEST_VERDICT_RE = re.compile(
    r"solo_regtest\s+->\s+(PASS|FAIL|SKIP)\s+\(([^)]+)\)")


def _extract_solo_regtest(rc: int, text: str) -> Tuple[str, str, str]:
    """Test 7 -- the runner itself prints a final verdict line we parse."""
    m = _SOLO_REGTEST_VERDICT_RE.search(text)
    if m:
        verdict = m.group(1)
        metric = m.group(2)
        if verdict == "PASS":
            return PASS, metric, ""
        if verdict == "SKIP":
            return SKIP, metric, ""
        return FAIL, metric, text[-400:]
    if rc == 2:
        return SKIP, "skipped", ""
    if rc == 0:
        return PASS, "ok", ""
    return FAIL, f"rc={rc}", text[-400:]


_POOL_STACK_VERDICT_RE = re.compile(
    r"pool_stack\s+->\s+(PASS|FAIL|SKIP)\s+\(([^)]+)\)")


def _extract_pool_stack(rc: int, text: str) -> Tuple[str, str, str]:
    m = _POOL_STACK_VERDICT_RE.search(text)
    if m:
        verdict = m.group(1)
        metric = m.group(2)
        if verdict == "PASS":
            return PASS, metric, ""
        if verdict == "SKIP":
            return SKIP, metric, ""
        return FAIL, metric, text[-400:]
    if rc == 2:
        return SKIP, "skipped", ""
    if rc == 0:
        return PASS, "ok", ""
    return FAIL, f"rc={rc}", text[-400:]


# ---------------------------------------------------------------------------
# Builtin runners
# ---------------------------------------------------------------------------


def _run_env_check(emit: Callable[[str], None]) -> Tuple[bool, str]:
    """Test 1 -- minimal check: Python >= 3.9, blake3 importable, miner script exists."""
    ok = True
    py_ok = sys.version_info >= (3, 9)
    emit(f"  Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
         + (" [OK]" if py_ok else " [FAIL]"))
    if not py_ok:
        ok = False
    try:
        import blake3 as _b3
        emit(f"  blake3: {getattr(_b3, '__version__', 'unknown')} [OK]")
    except ImportError:
        emit("  blake3: not installed [FAIL]")
        ok = False
    if os.path.exists(capability_check.MINER_SCRIPT):
        emit(f"  miner.py: {capability_check.MINER_SCRIPT} [OK]")
    else:
        emit(f"  miner.py: missing at {capability_check.MINER_SCRIPT} [FAIL]")
        ok = False
    metric = f"python {sys.version_info.major}.{sys.version_info.minor}"
    if ok:
        emit("PASS: environment looks good")
    else:
        emit("FAIL: environment missing prerequisites")
    return ok, metric


def _run_helper_unit_tests(emit):
    from .helper_tests import run_helper_unit_tests
    return run_helper_unit_tests(emit)


def _run_jsonl_rederive(emit):
    from .helper_tests import run_jsonl_rederive
    return run_jsonl_rederive(emit)


def _run_live_pool_probe(emit):
    from .live_pool_probe import run_live_pool_probe
    return run_live_pool_probe(emit)


# ---------------------------------------------------------------------------
# TestRegistry -- the canonical ordered list of all 9 tests
# ---------------------------------------------------------------------------


def _python() -> str:
    return sys.executable or "python"


def _build_default_registry() -> List[TestCase]:
    """The 9 tests in fastest-first order."""
    miner = capability_check.MINER_SCRIPT
    mock_test_script = capability_check.MOCK_TEST_SCRIPT
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    solo_runner = os.path.join(tests_dir, "solo_regtest_runner.py")
    stack_runner = os.path.join(tests_dir, "pool_stack_runner.py")

    return [
        BuiltinTest(
            1, "Environment check",
            "Python >= 3.9, blake3 importable, miner script exists.",
            runner=_run_env_check,
            prereqs=("python", "miner"),
            estimated_seconds=0.5,
        ),
        BuiltinTest(
            2, "Helper unit tests",
            "Direct calls into the miner module: parse_stratum_url, "
            "target_from_share_difficulty, network_difficulty_from_bits, "
            "build_coinbase_full, compute_merkle_root_from_branches, "
            "serialize_header against known-answer vectors.",
            runner=_run_helper_unit_tests,
            prereqs=("python", "miner"),
            estimated_seconds=0.5,
        ),
        SubprocessTest(
            3, "Argparse mutex",
            "Confirms --stratum and --coinbaseaddr are mutually exclusive (rc=2).",
            argv=[_python(), miner,
                  "--stratum", "stratum+tcp://127.0.0.1:3333",
                  "--coinbaseaddr", "b3q1example"],
            result_extractor=_extract_argparse_mutex,
            prereqs=("python", "miner"),
            estimated_seconds=2.0,
        ),
        SubprocessTest(
            4, "Benchmark",
            "Runs the miner with --benchmark and parses the H/s rate. "
            "PASS if rate >= 200 kH/s.",
            argv=[_python(), miner, "--benchmark"],
            result_extractor=_extract_benchmark,
            prereqs=("python", "blake3", "miner"),
            estimated_seconds=10.0,
        ),
        SubprocessTest(
            5, "Mock-pool E2E",
            "Runs test_pool_miner.py: in-process mock Stratum server + miner, "
            "5 shares submitted, JSONL BLAKE3d-verified.",
            argv=[_python(), mock_test_script],
            result_extractor=_extract_mock_e2e,
            prereqs=("python", "blake3", "miner", "mock_test"),
            estimated_seconds=4.0,
        ),
        BuiltinTest(
            6, "JSONL re-derive",
            "Spawns the mock pool in-process, runs the miner with --json-log, "
            "re-hashes every recorded share's header_hex and asserts byte-equality "
            "with pow_hash_le.",
            runner=_run_jsonl_rederive,
            prereqs=("python", "blake3", "miner", "mock_test"),
            estimated_seconds=5.0,
        ),
        SubprocessTest(
            7, "Solo regtest",
            "Spawns b3chaind -regtest in a temp datadir, mines 1 block via the "
            "miner using getblocktemplate/submitblock, asserts getblockcount>=1, "
            "tears the daemon down.",
            argv=[_python(), solo_runner],
            result_extractor=_extract_solo_regtest,
            prereqs=("python", "blake3", "miner", "b3chaind", "b3chain-cli"),
            estimated_seconds=45.0,
        ),
        BuiltinTest(
            8, "Live pool reachability",
            "TCP-connects to pool.b3chain.org:3333, sends mining.subscribe, "
            "expects a JSON-RPC result within 5s.",
            runner=_run_live_pool_probe,
            prereqs=("python", "internet"),
            estimated_seconds=2.0,
        ),
        SubprocessTest(
            9, "Local Docker pool stack",
            "OPT-IN. Brings up postgres via docker compose, runs npm install / "
            "migrate / dev:daemon / dev:stratum, mines 5 shares against the local "
            "pool, then tears the whole stack down. ~3 minutes.",
            argv=[_python(), stack_runner],
            result_extractor=_extract_pool_stack,
            prereqs=("python", "blake3", "miner", "b3chaind", "b3chain-cli",
                     "docker", "npm", "pool_src"),
            estimated_seconds=240.0,
            opt_in=True,
        ),
    ]


class TestRegistry:
    """The canonical ordered list of TestCases, plus enable-state management."""

    def __init__(self) -> None:
        self.tests: List[TestCase] = _build_default_registry()

    def __iter__(self):
        return iter(self.tests)

    def __len__(self) -> int:
        return len(self.tests)

    def get(self, ident: int) -> Optional[TestCase]:
        for t in self.tests:
            if t.id == ident:
                return t
        return None

    def by_index(self, idx: int) -> TestCase:
        return self.tests[idx]

    def update_enabled_state(self, probe: CapabilityProbe) -> None:
        for t in self.tests:
            t.update_enabled_state(probe)

    def runnable_for_run_all(self, include_slow: bool = False) -> List[TestCase]:
        out: List[TestCase] = []
        for t in self.tests:
            if not t.enabled:
                continue
            if t.opt_in and not include_slow:
                continue
            out.append(t)
        return out
