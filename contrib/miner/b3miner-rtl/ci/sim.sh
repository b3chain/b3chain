#!/usr/bin/env bash
# ============================================================================
# ci/sim.sh -- run every testbench under Verilator.  Each TB returns 0 on
# success, !=0 on failure.
# ============================================================================
export LC_ALL=C
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_DIR="$ROOT/sim"
VECT_DIR="$SIM_DIR/vectors"

echo "sim.sh: ROOT = $ROOT"

# 1) Regenerate vectors -- ensures the RTL is being tested against today's
#    Python reference, not yesterday's checked-in artifacts.
(cd "$ROOT/ref" && python3 -m pytest -q)
(cd "$ROOT/ref" && python3 gen_vectors.py --out "$VECT_DIR")

# 2) Build + run every TB.
TBS=()
for f in "$SIM_DIR"/tb/tb_*.sv; do
    TBS+=("$(basename "$f" .sv)")
done

fail=0
for tb in "${TBS[@]}"; do
    echo ""
    echo "=========================================================="
    echo "  TB: $tb"
    echo "=========================================================="
    if ! make -C "$SIM_DIR/verilator" run TB="$tb"; then
        echo "sim.sh: $tb FAILED" >&2
        fail=1
    fi
done

if [[ $fail -ne 0 ]]; then
    echo ""
    echo "sim.sh: one or more TBs failed" >&2
    exit 1
fi

echo ""
echo "sim.sh: all ${#TBS[@]} TBs passed"
