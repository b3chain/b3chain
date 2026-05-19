#!/usr/bin/env bash
# ============================================================================
# ci/synth_oc.sh -- out-of-context synthesis per leaf RTL module.
#
# Useful for tracking per-module area and timing in isolation -- catches
# accidental fanout explosions or comb-loop creation immediately rather
# than waiting for the full-chip build.
#
# Requires Vivado on PATH.  Skips gracefully on hosts without it.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RTL_DIR="$ROOT/rtl"
OC_DIR="$ROOT/build/oc"

if ! command -v vivado >/dev/null 2>&1; then
    echo "synth_oc.sh: vivado not found, skipping OOC synth"
    exit 0
fi

mkdir -p "$OC_DIR"

LEAVES=(
    blake3_compress
    blake3_xof
    spi_slave
    regfile
    scratchpad_mem
    scratch_init
    mixing_core
    target_compare
    xadc_monitor
)

for mod in "${LEAVES[@]}"; do
    if [[ ! -f "$RTL_DIR/$mod.sv" ]]; then
        echo "synth_oc.sh: SKIP $mod (no source yet)"
        continue
    fi
    echo "--- OOC synth $mod ---"
    cd "$OC_DIR"
    cat > "${mod}_oc.tcl" <<EOF
read_verilog -sv $RTL_DIR/params_pkg.sv
read_verilog -sv $RTL_DIR/$mod.sv
synth_design -mode out_of_context -top $mod -part xcku5p-ffvb676-2-i
report_utilization -file ${mod}_util.rpt
report_timing -file ${mod}_timing.rpt
EOF
    vivado -mode batch -source "${mod}_oc.tcl" -log "${mod}.log" -journal "${mod}.jou" \
        || echo "synth_oc.sh: $mod FAILED -- see ${mod}.log"
done

echo "synth_oc.sh: see $OC_DIR/*_util.rpt and *_timing.rpt"
