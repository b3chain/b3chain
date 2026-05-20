#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[H-1.1] B3PoW-Scratch v1.1 verifier budget enforcement.

The B3PoW-Scratch verifier has a wall-clock budget
(`Consensus::Params::b3pow_verify_budget_ms`, default 50 ms on
mainnet/testnet/regtest, 1 s on signet) that caps how long one
verification can run before returning `PoWResult::BudgetExceeded`. The
budget protects honest nodes against an adversarial header that is
genuinely above-target but expensive to *prove* above-target
(prev_block_hash-induced cache miss + worst-case scratchpad walk).

This audit verifies the budget plumbing is in place:

  H-1.1 (static): Consensus::Params declares b3pow_verify_budget_ms
                  with a positive default for every chain.
  H-1.1 (static): pow.cpp threads params.b3pow_verify_budget_ms into
                  CheckBlockHeaderPoW().
  H-1.1 (static): validation.cpp returns BlockValidationResult::
                  BLOCK_POW_BUDGET when the verifier exceeds the budget.
  H-1.1 (static): net_processing.cpp routes BLOCK_POW_BUDGET to
                  `Misbehaving(*peer, "b3pow-budget-exceeded")`.
  H-1.1 (dynamic): the matching C++ unit tests (pow_hash_budget_exceeded
                  and CheckBlockHeaderPoW_budget_exceeded) PASS under
                  ctest. If no build/ exists this check SKIPs.

The dynamic part is the authoritative pin; the static checks gate
against silent regressions if someone re-routes the validation result.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

from audit_common import AuditResult, repo_root  # type: ignore # noqa: E402


def static_consensus_param_has_budget(r: AuditResult) -> None:
    p = repo_root() / "src" / "consensus" / "params.h"
    if not p.exists():
        r.skipped_check("[H-1.1] src/consensus/params.h not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_field = re.search(r"int64_t\s+b3pow_verify_budget_ms\s*\{\s*[0-9]+\s*\}", body)
    r.expect(
        bool(has_field),
        "[H-1.1] Consensus::Params declares b3pow_verify_budget_ms with positive default",
    )


def static_chainparams_sets_positive_budget(r: AuditResult) -> None:
    p = repo_root() / "src" / "kernel" / "chainparams.cpp"
    if not p.exists():
        r.skipped_check("[H-1.1] src/kernel/chainparams.cpp not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    # All chainparam blocks assign a positive budget (>= 50 ms).
    assigns = re.findall(r"consensus\.b3pow_verify_budget_ms\s*=\s*([0-9]+)\s*;", body)
    nonzero = [int(x) for x in assigns if int(x) > 0]
    r.expect(
        len(assigns) > 0 and len(nonzero) == len(assigns),
        "[H-1.1] all chain consensus blocks set b3pow_verify_budget_ms > 0",
        f"assignments={assigns}",
    )


def static_pow_cpp_threads_budget(r: AuditResult) -> None:
    p = repo_root() / "src" / "pow.cpp"
    if not p.exists():
        r.skipped_check("[H-1.1] src/pow.cpp not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    threads_budget = "params.b3pow_verify_budget_ms" in body
    r.expect(
        threads_budget,
        "[H-1.1] pow.cpp threads params.b3pow_verify_budget_ms into the verifier",
    )


def static_validation_returns_budget_result(r: AuditResult) -> None:
    p = repo_root() / "src" / "validation.cpp"
    if not p.exists():
        r.skipped_check("[H-1.1] src/validation.cpp not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_result = "BlockValidationResult::BLOCK_POW_BUDGET" in body
    has_check = "PoWResult::BudgetExceeded" in body or "b3pow-budget-exceeded" in body
    r.expect(
        has_result and has_check,
        "[H-1.1] validation.cpp returns BLOCK_POW_BUDGET on PoWResult::BudgetExceeded",
    )


def static_net_processing_misbehaves(r: AuditResult) -> None:
    p = repo_root() / "src" / "net_processing.cpp"
    if not p.exists():
        r.skipped_check("[H-1.1] src/net_processing.cpp not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    routes = (
        "BlockValidationResult::BLOCK_POW_BUDGET" in body
        and 'Misbehaving(*peer, "b3pow-budget-exceeded")' in body
    )
    r.expect(
        routes,
        '[H-1.1] net_processing.cpp routes BLOCK_POW_BUDGET to Misbehaving("b3pow-budget-exceeded")',
    )


def dynamic_ctest_budget(r: AuditResult) -> None:
    """Run the C++ unit tests that exercise the budget."""
    build = repo_root() / "build"
    if not build.is_dir():
        r.skipped_check(
            "[H-1.1] C++ budget tests (no build/ directory; build the project first)",
            "",
        )
        return
    # We invoke ctest -R '(pow|crypto)_tests' and rely on the per-test
    # filters configured in src/test/CMakeLists.txt. Boost.Test does
    # not surface individual cases to ctest, so we run the whole
    # pow_tests binary and grep for the specific test names.
    bin_pow = None
    for cand in (build / "bin" / "test_bitcoin", build / "src" / "test" / "test_bitcoin"):
        if cand.is_file():
            bin_pow = cand
            break
    if bin_pow is None:
        r.skipped_check("[H-1.1] test_bitcoin binary not found under build/", "")
        return
    env = os.environ.copy()
    try:
        proc = subprocess.run(
            [str(bin_pow), "--run_test=pow_tests/pow_hash_budget_exceeded:pow_tests/CheckBlockHeaderPoW_budget_exceeded"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        r.failed_check(f"[H-1.1] could not run budget ctest: {e}", "")
        return
    output = (proc.stdout or "") + (proc.stderr or "")
    passed = "No errors detected" in output or "PASS" in output
    failed = "FAIL" in output and "failures detected" in output.lower()
    r.expect(
        proc.returncode == 0 and passed and not failed,
        "[H-1.1] pow_hash_budget_exceeded + CheckBlockHeaderPoW_budget_exceeded ctest PASS",
        output[-400:].replace("\n", " | ") if proc.returncode != 0 else "",
    )


def main() -> int:
    r = AuditResult("H-1.1", "B3PoW-Scratch verifier budget enforcement")
    static_consensus_param_has_budget(r)
    static_chainparams_sets_positive_budget(r)
    static_pow_cpp_threads_budget(r)
    static_validation_returns_budget_result(r)
    static_net_processing_misbehaves(r)
    dynamic_ctest_budget(r)
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
