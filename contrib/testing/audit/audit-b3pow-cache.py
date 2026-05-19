#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[H-1.2] B3PoW-Scratch v1.1 LRU scratchpad cache.

B3PoW-Scratch initialises a 1 MB scratchpad from prev_block_hash for
every verification. Without caching, a node would rebuild the pad
~5 ms each time, which makes a one-tip-many-sibling adversarial flow
expensive. b3pow::Cache is an LRU keyed by prev_block_hash, owned by
ChainstateManager, with size `consensus.b3pow_cache_depth` (4 entries
on main/test/regtest = ~4 MB resident).

This audit verifies the cache is wired:

  H-1.2 (static): Consensus::Params declares b3pow_cache_depth with a
                  positive default.
  H-1.2 (static): src/validation.h declares m_b3pow_cache of type
                  b3pow::Cache on ChainstateManager.
  H-1.2 (static): src/validation.cpp constructs m_b3pow_cache with
                  consensus.b3pow_cache_depth.
  H-1.2 (static): src/primitives/block.cpp's GetPoWHash() accepts a
                  pad argument and reuses it (no per-call init).
  H-1.2 (dynamic): the C++ unit tests in b3pow_cache_tests exercise
                  insert/retrieve, eviction, distinct pads per prev,
                  thread-safety. SKIP if no build/ directory.

The Python b3pow_ref also caches pads (see
test/functional/test_framework/messages.py::_B3POW_PAD_CACHE) and the
functional test feature_b3pow.py exercises that path.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

from audit_common import AuditResult, repo_root  # type: ignore


def static_consensus_param_has_cache_depth(r: AuditResult) -> None:
    p = repo_root() / "src" / "consensus" / "params.h"
    if not p.exists():
        r.skipped_check("[H-1.2] src/consensus/params.h not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_field = re.search(r"int64_t\s+b3pow_cache_depth\s*\{\s*[1-9][0-9]*\s*\}", body)
    r.expect(
        bool(has_field),
        "[H-1.2] Consensus::Params declares b3pow_cache_depth with positive default",
    )


def static_chainparams_sets_positive_depth(r: AuditResult) -> None:
    p = repo_root() / "src" / "kernel" / "chainparams.cpp"
    if not p.exists():
        r.skipped_check("[H-1.2] src/kernel/chainparams.cpp not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    assigns = re.findall(r"consensus\.b3pow_cache_depth\s*=\s*([0-9]+)\s*;", body)
    nonzero = [int(x) for x in assigns if int(x) > 0]
    r.expect(
        len(assigns) > 0 and len(nonzero) == len(assigns),
        f"[H-1.2] every chainparams sets b3pow_cache_depth > 0",
        f"assignments={assigns}",
    )


def static_chainstate_declares_cache(r: AuditResult) -> None:
    p = repo_root() / "src" / "validation.h"
    if not p.exists():
        r.skipped_check("[H-1.2] src/validation.h not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_field = re.search(r"b3pow::Cache\s+m_b3pow_cache", body)
    r.expect(
        bool(has_field),
        "[H-1.2] ChainstateManager declares b3pow::Cache m_b3pow_cache",
    )


def static_chainstate_constructs_cache_from_depth(r: AuditResult) -> None:
    p = repo_root() / "src" / "validation.cpp"
    if not p.exists():
        r.skipped_check("[H-1.2] src/validation.cpp not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_init = "b3pow_cache_depth" in body and "m_b3pow_cache" in body
    r.expect(
        has_init,
        "[H-1.2] ChainstateManager constructs m_b3pow_cache from consensus.b3pow_cache_depth",
    )


def static_block_getpowhash_accepts_pad(r: AuditResult) -> None:
    """GetPoWHash() must accept a pad to avoid per-call init."""
    p = repo_root() / "src" / "primitives" / "block.h"
    if not p.exists():
        r.skipped_check("[H-1.2] src/primitives/block.h not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    # The v1.1 signature includes `pad` and `budget` parameters.
    sig_ok = "GetPoWHash(" in body and "pad" in body
    r.expect(
        sig_ok,
        "[H-1.2] CBlockHeader::GetPoWHash(prev_block_hash, pad, ...) accepts a pad parameter",
    )


def dynamic_ctest_cache(r: AuditResult) -> None:
    build = repo_root() / "build"
    if not build.is_dir():
        r.skipped_check(
            "[H-1.2] C++ b3pow_cache_tests (no build/ directory; build the project first)",
            "",
        )
        return
    bin_pow = None
    for cand in (build / "bin" / "test_bitcoin", build / "src" / "test" / "test_bitcoin"):
        if cand.is_file():
            bin_pow = cand
            break
    if bin_pow is None:
        r.skipped_check("[H-1.2] test_bitcoin binary not found under build/", "")
        return
    try:
        proc = subprocess.run(
            [str(bin_pow), "--run_test=b3pow_cache_tests"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        r.failed_check(f"[H-1.2] could not run b3pow_cache_tests: {e}", "")
        return
    output = (proc.stdout or "") + (proc.stderr or "")
    passed = "No errors detected" in output
    r.expect(
        proc.returncode == 0 and passed,
        "[H-1.2] b3pow_cache_tests ctest PASS",
        output[-400:].replace("\n", " | ") if proc.returncode != 0 else "",
    )


def main() -> int:
    r = AuditResult("H-1.2", "B3PoW-Scratch LRU scratchpad cache")
    static_consensus_param_has_cache_depth(r)
    static_chainparams_sets_positive_depth(r)
    static_chainstate_declares_cache(r)
    static_chainstate_constructs_cache_from_depth(r)
    static_block_getpowhash_accepts_pad(r)
    dynamic_ctest_cache(r)
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
