#!/usr/bin/env bash
# ============================================================================
# ci/lint.sh -- verilator --lint-only on every RTL module.
#
# This catches syntax errors, missing-port warnings, signed/unsigned mismatches,
# always_comb/always_ff drift, and most obvious linter issues -- all before any
# simulation tries to elaborate.  Runs in seconds; first line of defence.
# ============================================================================
export LC_ALL=C
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RTL_DIR="$ROOT/rtl"

VERILATOR=${VERILATOR:-verilator}

echo "lint.sh: RTL_DIR = $RTL_DIR"

if ! command -v "$VERILATOR" >/dev/null 2>&1; then
    echo "lint.sh: ERROR -- '$VERILATOR' not found in PATH" >&2
    echo "         install via: apt install verilator    (Ubuntu 22.04+)" >&2
    exit 127
fi

# Newest unified-lint mode.  Treat warnings as errors except the ones we
# accept by design.  We use the broad `-Wno-WIDTH` form rather than the
# narrower `-Wno-WIDTHTRUNC` because Verilator 4.x (shipped on Ubuntu
# 22.04, where the GitHub Actions `ubuntu-22.04` runner installs from
# apt) does not recognise `-Wno-WIDTHTRUNC` and aborts with
# `%Error: Unknown warning specified: -Wno-WIDTHTRUNC`.  Verilator 5.x
# accepts `-Wno-WIDTH` too -- it implies WIDTHTRUNC + WIDTHEXPAND --
# so the broader form is forward-compatible.
WAIVERS=(
    -Wno-MULTIDRIVEN   # FF reset in async-reset clause is intentional
    -Wno-WIDTH         # explicit narrowing in some places (commented in RTL)
    -Wno-UNOPTFLAT     # combinational state-machine feedback loops
)

# Lint each top-level RTL file in turn with params_pkg always pulled in.
fail=0
for f in "$RTL_DIR"/*.sv; do
    name="$(basename "$f" .sv)"
    if [[ "$name" == "params_pkg" ]]; then
        continue
    fi
    echo "--- lint $name ---"
    if ! "$VERILATOR" --lint-only -sv -Wall "${WAIVERS[@]}" \
            +incdir+"$RTL_DIR" \
            "$RTL_DIR/params_pkg.sv" \
            "$f"; then
        echo "lint.sh: $name FAILED" >&2
        fail=1
    fi
done

if [[ $fail -ne 0 ]]; then
    echo "lint.sh: one or more modules failed lint" >&2
    exit 1
fi

echo "lint.sh: all modules clean"
