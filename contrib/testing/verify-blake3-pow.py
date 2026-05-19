#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
DEPRECATED entry point.

This script has been renamed to `verify-b3pow.py` because the B3Chain
proof-of-work is no longer the interim double-BLAKE3 design - it is
B3PoW-Scratch v1.1 (1 MB memory-hard scratchpad, see
contrib/miner/b3miner-rtl/SPEC.md).

This shim transparently forwards all arguments to `verify-b3pow.py`
so any external link to the old filename keeps working for one
release. It will be removed in the next release.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW_SCRIPT = HERE / "verify-b3pow.py"

print(
    "[DEPRECATED] verify-blake3-pow.py has been renamed to verify-b3pow.py "
    "(B3PoW-Scratch v1.1).  Forwarding...",
    file=sys.stderr,
)

if not NEW_SCRIPT.exists():
    print(f"ERROR: {NEW_SCRIPT} not found.  Re-pull the repo.", file=sys.stderr)
    sys.exit(2)

os.execv(sys.executable, [sys.executable, str(NEW_SCRIPT), *sys.argv[1:]])
