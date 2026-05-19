#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
DEPRECATED entry point.

This audit has been renamed to `audit-b3pow-miner-e2e.py`. The audit
ID `M-1d` is unchanged so doc/PHASE-6-VERIFICATION.md cross-references
still resolve.

This shim forwards all arguments to the new path so any external
runner pinned to the old filename keeps working for one release. It
will be removed in the next release.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_SCRIPT = HERE / "audit-b3pow-miner-e2e.py"

print(
    "[DEPRECATED] audit-internal-miner-e2e.py has been renamed to "
    "audit-b3pow-miner-e2e.py (B3PoW-Scratch v1.1).  Forwarding...",
    file=sys.stderr,
)

if not NEW_SCRIPT.exists():
    print(f"ERROR: {NEW_SCRIPT} not found.  Re-pull the repo.", file=sys.stderr)
    sys.exit(2)

os.execv(sys.executable, [sys.executable, str(NEW_SCRIPT), *sys.argv[1:]])
