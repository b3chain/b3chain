#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[H-1.3] B3PoW-Scratch v1.1 HEADERS message verification cap.

A HEADERS message can contain up to 2000 entries (Bitcoin protocol
limit). At a 50 ms B3PoW verifier budget per header, naively verifying
all 2000 would burn 100 s of CPU per malicious peer per message. To
bound that, ProcessHeadersMessage truncates the verified subset to
`MAX_B3POW_VERIFY_PER_BATCH = 256` headers per message, which keeps
worst-case CPU at ~13 s per malicious peer.

This audit verifies the cap is wired:

  H-1.3 (static): src/net_processing.cpp defines
                  MAX_B3POW_VERIFY_PER_BATCH = 256.
  H-1.3 (static): the cap is *enforced* (the code path actually
                  resizes/truncates the headers vector before
                  verification).
  H-1.3 (static): the cap is small enough to be safe
                  (MAX_B3POW_VERIFY_PER_BATCH <= 512).
  H-1.3 (static): a `LogDebug(BCLog::NET, ...)` line exists near the
                  cap so operators can see when it triggers.

There is intentionally NO functional check that spams 2000 garbage
headers at a live node: the budget is the same as the headers cap
(50 ms * 256 ≈ 13 s) and we don't want the audit to take that long on
every CI run. The C++ unit-test suite already exercises the budget
machinery (see audit-b3pow-budget.py [H-1.1]) and the static checks
here gate against regressions in the integration.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

from audit_common import AuditResult, repo_root  # type: ignore # noqa: E402


def static_constant_defined(r: AuditResult) -> tuple[int | None, str]:
    """Return (value, source-snippet)."""
    p = repo_root() / "src" / "net_processing.cpp"
    if not p.exists():
        r.skipped_check("[H-1.3] src/net_processing.cpp not found", "")
        return None, ""
    body = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(
        r"(?:constexpr|static\s+constexpr|const)\s+(?:std::)?size_t\s+"
        r"MAX_B3POW_VERIFY_PER_BATCH\s*=\s*([0-9]+)\s*;",
        body,
    )
    if not m:
        r.failed_check(
            "[H-1.3] MAX_B3POW_VERIFY_PER_BATCH not defined in net_processing.cpp",
            "",
        )
        return None, body
    val = int(m.group(1))
    r.expect(
        val > 0,
        f"[H-1.3] MAX_B3POW_VERIFY_PER_BATCH defined (= {val})",
    )
    return val, body


def static_constant_within_bound(r: AuditResult, val: int | None) -> None:
    if val is None:
        return
    # Must be small enough to bound worst-case CPU.
    r.expect(
        0 < val <= 512,
        f"[H-1.3] MAX_B3POW_VERIFY_PER_BATCH is within safe range (1..512), got {val}",
    )


def static_cap_enforced(r: AuditResult, body: str) -> None:
    """The code path must actually shrink the headers vector before verification."""
    has_resize = "headers.resize(MAX_B3POW_VERIFY_PER_BATCH)" in body
    has_guard = (
        "headers.size() > MAX_B3POW_VERIFY_PER_BATCH" in body
        or "headers.size() >= MAX_B3POW_VERIFY_PER_BATCH" in body
    )
    r.expect(
        has_resize and has_guard,
        "[H-1.3] HEADERS batch is truncated to MAX_B3POW_VERIFY_PER_BATCH before verification",
    )


def static_log_line(r: AuditResult, body: str) -> None:
    """A debug log line near the cap, so operators can spot truncation."""
    has_log = re.search(
        r"LogDebug\s*\(\s*BCLog::NET\s*,\s*\"[^\"]*[Tt]runcat[^\"]*\"",
        body,
    )
    r.expect(
        bool(has_log),
        "[H-1.3] LogDebug(BCLog::NET, \"Truncating HEADERS batch ...\") line present",
    )


def main() -> int:
    r = AuditResult("H-1.3", "B3PoW-Scratch HEADERS verification cap")
    val, body = static_constant_defined(r)
    if body:
        static_constant_within_bound(r, val)
        static_cap_enforced(r, body)
        static_log_line(r, body)
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
