#!/bin/bash
set -eu

ROOT=/data/projects/b3pow-implementation/b3miner-rtl
BIT="$ROOT/build/xcku5p_b3miner/xcku5p_b3miner.bit"
TCL="$ROOT/boards/xcku5p-2ffvb676/build/program_volatile.tcl"
EXPECTED_SHA=efa6fc50a638b6c037289805f2e2272f50913001f88fc57f009dbe98b84e01c7
EXPECTED_SIZE=15431348

exec 9>/tmp/b3miner-jtag-autoload.lock
flock -n 9 || exit 0

test "$(stat -c %s "$BIT")" = "$EXPECTED_SIZE"
test "$(sha256sum "$BIT" | awk '{print $1}')" = "$EXPECTED_SHA"
if grep -Eiq 'cfgmem|write_cfgmem|program_hw_cfgmem' "$TCL"; then
    echo "refusing configuration-memory command" >&2
    exit 2
fi

for _ in $(seq 1 30); do
    if lsusb -d 0403:6010 >/dev/null 2>&1; then break; fi
    sleep 2
done
lsusb -d 0403:6010 >/dev/null
sleep 2

source /data/tools/amd/2026.1/Vivado/settings64.sh
vivado -mode batch -source "$TCL" -notrace \
    -log "$ROOT/build/xcku5p_b3miner/autoload.log" \
    -journal "$ROOT/build/xcku5p_b3miner/autoload.jou"
