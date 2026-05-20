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

# Files that depend on Xilinx UNISIM primitives (SYSMONE4, IBUFGDS,
# MMCME4_ADV, BUFG, ...).  Vanilla Verilator on Ubuntu cannot resolve
# those modules without the full Vivado UNISIM library, so we skip
# them in this portable lint pass; the Vivado `report_methodology`
# step covers them in the synth flow.
SKIP_FILES=(
    "b3miner_top"   # instantiates IBUFGDS, MMCME4_ADV, BUFG (Xilinx PLL)
    "xadc_monitor"  # instantiates SYSMONE4 (Xilinx XADC)
)

# Newest unified-lint mode.  Treat warnings as errors except the ones
# we accept by design.  Notes on choice of waivers:
#
#   -Wno-WIDTH        (broad) -- Verilator 4.x (Ubuntu 22.04 apt) doesn't
#                                recognise the finer-grained -Wno-WIDTHTRUNC,
#                                so use the umbrella form.  5.x accepts both.
#   -Wno-VARHIDDEN    -- inner 'state' var shadows top-level FSM 'state' inside
#                        unique-case scopes; intentional.
#   -Wno-UNUSED       -- carry-through signals (e.g. blk_fresh) declared for
#                        symmetry with the ref but only consumed in non-
#                        Verilator simulation flows.
#   -Wno-BLKSEQ       -- BLAKE3 round mixes blocking and non-blocking writes
#                        by design; matches upstream BLAKE3 reference RTL.
#   -Wno-PINCONNECTEMPTY -- Xilinx primitives have many optional ports; we
#                            only wire the ones we use.  (Belt-and-braces;
#                            should not trigger after SKIP_FILES above.)
#   -Wno-DECLFILENAME -- multiple modules per .sv file (e.g. reset_sync
#                        inside b3miner_top.sv).
#   --bbox-unsup      -- box constructs Verilator 4.x doesn't synthesize but
#                        the hardware tools do (e.g. delayed array writes
#                        inside for-loops in the BLAKE3 mixer).
WAIVERS=(
    -Wno-MULTIDRIVEN
    -Wno-WIDTH
    -Wno-UNOPTFLAT
    -Wno-VARHIDDEN
    -Wno-UNUSED
    -Wno-BLKSEQ
    -Wno-PINCONNECTEMPTY
    -Wno-DECLFILENAME
    --bbox-unsup
)

# Lint each top-level RTL file in turn with params_pkg always pulled in.
fail=0
for f in "$RTL_DIR"/*.sv; do
    name="$(basename "$f" .sv)"
    if [[ "$name" == "params_pkg" ]]; then
        continue
    fi
    skip=0
    for s in "${SKIP_FILES[@]}"; do
        if [[ "$name" == "$s" ]]; then
            skip=1
            break
        fi
    done
    if [[ $skip -eq 1 ]]; then
        echo "--- skip $name (Xilinx primitives -- vivado-only lint) ---"
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
