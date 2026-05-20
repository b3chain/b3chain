#!/usr/bin/env bash
#
# Always-on B3Chain testnet miner.
#
# Calls `b3chain-cli generatetoaddress 1 <ADDR>` in a loop. The daemon
# does the actual work (BLAKE3 PoW search + coinbase assembly), and we
# get a steady stream of blocks at the configured testnet difficulty.
#
# Why not contrib/miner/b3chain-cpuminer.py?
# That script is a *reference implementation* that demonstrates how to
# implement BLAKE3 PoW outside the daemon — useful for documenting the
# protocol and for pool-software developers — but it currently relies on
# `coinbasetxn` being present in `getblocktemplate` output, which Bitcoin
# Core 30.x no longer includes. Using `generatetoaddress` here lets the
# daemon construct the coinbase transaction itself (P2WPKH, witness
# commitment, height-encoded scriptSig), which is exactly what we want
# for an always-on operator-run miner.
#
# Configured via /etc/b3chain/miner.env:
#   RPC_USER=...
#   RPC_PASSWORD=...
#   COINBASE_ADDR=tb31q...

export LC_ALL=C
set -uo pipefail

ENV_FILE=${ENV_FILE:-/etc/b3chain/miner.env}
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

CONF=${B3_CONF:-/etc/b3chain/b3chain.conf}
DATADIR=${B3_DATADIR:-/var/lib/b3chain/.b3chain}

if [ -z "${COINBASE_ADDR:-}" ]; then
    echo "ERROR: COINBASE_ADDR not set in $ENV_FILE" >&2
    exit 2
fi

CLI=/usr/local/bin/b3chain-cli
ARGS=(-chain=test -conf="$CONF" -datadir="$DATADIR")

echo "B3Chain testnet miner (generatetoaddress loop)"
echo "  coinbase: $COINBASE_ADDR"
echo "  cli:      $CLI ${ARGS[*]}"

# Trap so SIGTERM from systemd cleanly exits the loop.
trap 'echo "SIGTERM received, exiting"; exit 0' TERM INT

# Spin until the daemon is reachable.
while ! "$CLI" "${ARGS[@]}" getblockchaininfo >/dev/null 2>&1; do
    echo "  waiting for b3chaind RPC..."
    sleep 3
done

block_count=0
while true; do
    # generatetoaddress 1 <addr> <maxtries>
    # maxtries default is 1_000_000 which can take a few seconds at
    # initial testnet difficulty (1e-3). On success, prints a JSON list
    # containing the new block hash; on failure (RPC error or no block
    # found within maxtries) we just retry.
    out=$("$CLI" "${ARGS[@]}" generatetoaddress 1 "$COINBASE_ADDR" 2>&1) || {
        echo "  generatetoaddress failed: $out"
        sleep 5
        continue
    }
    # `out` is a JSON array like `["<hash>"]` (one block per call).
    h=$(echo "$out" | tr -d '[]" \n,')
    if [ -n "$h" ]; then
        block_count=$((block_count + 1))
        # Light log line. systemd-journald will pick this up.
        echo "  mined block #$block_count $h"
    fi
done
