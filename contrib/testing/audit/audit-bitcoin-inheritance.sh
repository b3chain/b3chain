#!/usr/bin/env bash
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# Bitcoin Security Inheritance audit.
#
# Runs the FULL upstream Bitcoin Core test suite (ctest unit + functional
# test_runner.py --extended) on B3Chain, then classifies every result as
#   PASS               - inherited cleanly
#   DIVERGED-EXPECTED  - on the allowlist (e.g. PoW algo, mainnet fixtures)
#   FAIL               - real regression — investigate
#   SKIP               - upstream skip
#
# The classifier rewrites doc/SECURITY-INHERITANCE.md and exits non-zero
# only on real regressions.
#
# Usage:
#   bash contrib/testing/audit/audit-bitcoin-inheritance.sh
#   B3CHAIN_INHERIT_QUICK=1 bash ...     # only ctest, skip functional
#   B3CHAIN_INHERIT_LOGS=/path bash ...  # use cached logs instead of re-running

export LC_ALL=C
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

LOGDIR="${B3CHAIN_INHERIT_LOGS:-$REPO_ROOT/.inheritance-logs}"
mkdir -p "$LOGDIR"
CTEST_LOG="$LOGDIR/ctest.log"
FUNC_LOG="$LOGDIR/functional.log"

# ---------------------------------------------------------------------------
# Sanity
# ---------------------------------------------------------------------------
if [ ! -d "$REPO_ROOT/build" ]; then
    echo "error: build/ directory not found. Build B3Chain Core first:"
    echo "       cmake -B build && cmake --build build -j\$(nproc)"
    exit 2
fi

if ! command -v python3 >/dev/null; then
    echo "error: python3 not found"
    exit 2
fi

# ---------------------------------------------------------------------------
# Phase 1 — ctest unit suite
# ---------------------------------------------------------------------------
if [ ! -s "$CTEST_LOG" ] || [ "${B3CHAIN_INHERIT_REUSE:-0}" != "1" ]; then
    echo "==> ctest unit suite (logging to $CTEST_LOG)"
    (
        cd "$REPO_ROOT/build" || exit 1
        ctest --output-on-failure -j"$(nproc 2>/dev/null || echo 2)"
    ) >"$CTEST_LOG" 2>&1 || true
else
    echo "==> reusing existing ctest log: $CTEST_LOG"
fi

# ---------------------------------------------------------------------------
# Phase 2 — functional suite
# ---------------------------------------------------------------------------
if [ "${B3CHAIN_INHERIT_QUICK:-0}" = "1" ]; then
    echo "==> skipping functional suite (B3CHAIN_INHERIT_QUICK=1)"
    : > "$FUNC_LOG"
elif [ ! -s "$FUNC_LOG" ] || [ "${B3CHAIN_INHERIT_REUSE:-0}" != "1" ]; then
    echo "==> functional suite (logging to $FUNC_LOG; this is slow)"
    if [ -f "$REPO_ROOT/test/functional/test_runner.py" ]; then
        python3 "$REPO_ROOT/test/functional/test_runner.py" \
            --jobs="$(nproc 2>/dev/null || echo 2)" \
            --extended \
            >"$FUNC_LOG" 2>&1 || true
    else
        echo "warn: test/functional/test_runner.py not present; skipping" \
            > "$FUNC_LOG"
    fi
else
    echo "==> reusing existing functional log: $FUNC_LOG"
fi

# ---------------------------------------------------------------------------
# Phase 3 — classify
# ---------------------------------------------------------------------------
echo
echo "==> classifying results"
python3 "$SCRIPT_DIR/lib/inheritance_classify.py" \
    --ctest "$CTEST_LOG" \
    --functional "$FUNC_LOG" \
    --json-out "$LOGDIR/results.json" \
    --doc "$REPO_ROOT/doc/SECURITY-INHERITANCE.md"
rc=$?

echo
if [ "$rc" -eq 0 ]; then
    echo "AUDIT RESULT: PASS  [Bitcoin inheritance]"
else
    echo "AUDIT RESULT: FAIL  [Bitcoin inheritance]  — see SECURITY-INHERITANCE.md Findings"
fi
exit "$rc"
