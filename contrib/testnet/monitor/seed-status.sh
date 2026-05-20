#!/usr/bin/env bash
#
# Polls every configured seed for getblockchaininfo and writes a
# human-readable snapshot to /var/www/b3chain/testnet-status.txt
# (served by nginx as https://b3chain.org/testnet-status.txt) and a
# log line to /var/log/b3chain/seed-status.log.
#
# Configured via /etc/b3chain/seed-status.env:
#
#   SEEDS="seed1.testnet.b3chain.org seed2.testnet.b3chain.org ..."
#   STATUS_TXT=/var/www/b3chain/testnet-status.txt
#   LOG=/var/log/b3chain/seed-status.log
#   LOCAL_RPC_USER=b3chain
#   LOCAL_RPC_PASSWORD_FILE=/etc/b3chain/rpcpassword
#   LOCAL_RPC_PORT=18534
#   # Optional: SSH key + user + port for reaching remote seeds via SSH
#   REMOTE_SSH_KEY=/root/.ssh/b3chain_monitor
#   REMOTE_SSH_USER=deploy
#   REMOTE_SSH_PORT=2222
#
# A "seed" entry in $SEEDS may include an explicit ssh target after a
# pipe ("|"), in which case the ssh target is used to reach the host
# while the bare hostname is used as the display label, e.g.
#   SEEDS="seed1.b3chain.org|localhost seed2.b3chain.org|151.158.1.22 \
#          seed3.b3chain.org|151.158.1.60"
#
# Run from cron: every 5 minutes.

set -uo pipefail

CFG=/etc/b3chain/seed-status.env
[ -f "$CFG" ] && . "$CFG"

: "${SEEDS:=seed1.testnet.b3chain.org}"
: "${STATUS_TXT:=/var/www/b3chain/testnet-status.txt}"
: "${LOG:=/var/log/b3chain/seed-status.log}"
: "${LOCAL_RPC_USER:=b3chain}"
: "${LOCAL_RPC_PORT:=18534}"
: "${LOCAL_RPC_PASSWORD_FILE:=/etc/b3chain/rpcpassword}"
: "${SELF_HOSTNAME:=$(hostname -f)}"

LOCAL_PASS=$(cat "$LOCAL_RPC_PASSWORD_FILE" 2>/dev/null || echo "")

mkdir -p "$(dirname "$STATUS_TXT")" "$(dirname "$LOG")"

# Split a "label|target" entry into label + target. If no pipe is
# present the label and target are the same.
seed_label()  { echo "${1%%|*}"; }
seed_target() {
    case "$1" in
        *\|*) echo "${1#*|}" ;;
        *)    echo "$1" ;;
    esac
}

# Query a single seed's getblockchaininfo. For the local seed we use
# loopback RPC; for remote seeds we attempt SSH-based query (cheaper
# than exposing RPC publicly).
seed_height() {
    local target=$1
    if [ "$target" = "$SELF_HOSTNAME" ] || [ "$target" = "127.0.0.1" ] \
       || [ "$target" = "localhost" ]; then
        curl -s --max-time 5 \
             --user "$LOCAL_RPC_USER:$LOCAL_PASS" \
             --data-binary '{"jsonrpc":"1.0","id":"mon","method":"getblockchaininfo","params":[]}' \
             -H 'content-type: application/json' \
             "http://127.0.0.1:$LOCAL_RPC_PORT/" \
            | python3 -c 'import json,sys; d=json.load(sys.stdin)["result"]; print(d["blocks"], d["bestblockhash"])' \
            || echo "ERR rpc"
        return
    fi
    if [ -n "${REMOTE_SSH_KEY:-}" ]; then
        timeout 10 ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
            -p "${REMOTE_SSH_PORT:-22}" \
            -i "$REMOTE_SSH_KEY" "${REMOTE_SSH_USER:-deploy}@$target" \
            'b3chain-cli -chain=test -conf=/etc/b3chain/b3chain.conf -datadir=/var/lib/b3chain/.b3chain getblockchaininfo' 2>/dev/null \
            | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["blocks"], d["bestblockhash"])' 2>/dev/null \
            || echo "ERR ssh"
        return
    fi
    echo "ERR no-method"
}

ts=$(date -u +%FT%TZ)
{
    echo "B3Chain testnet status (UTC $ts)"
    echo "================================================================"
    printf "%-40s %10s  %s\n" "seed" "height" "best_hash"
    echo "----------------------------------------------------------------"
    declare -a heights=()
    for seed in $SEEDS; do
        label=$(seed_label  "$seed")
        target=$(seed_target "$seed")
        result=$(seed_height "$target")
        if [ -z "$result" ] || echo "$result" | grep -q ERR; then
            printf "%-40s %10s  %s\n" "$label" "?" "unreachable"
            continue
        fi
        height=$(echo "$result" | awk '{print $1}')
        bhash=$(echo "$result" | awk '{print $2}')
        printf "%-40s %10s  %s\n" "$label" "$height" "$bhash"
        heights+=("$height")
    done
    echo
    if [ ${#heights[@]} -gt 0 ]; then
        max=0
        for h in "${heights[@]}"; do
            [ "$h" -gt "$max" ] 2>/dev/null && max=$h
        done
        echo "Tip height (max across seeds): $max"
    fi
    echo
    echo "Updated by contrib/testnet/monitor/seed-status.sh"
} > "$STATUS_TXT.tmp"
mv "$STATUS_TXT.tmp" "$STATUS_TXT"

# log a single line per run
line=$(printf '%s ' "$ts")
for seed in $SEEDS; do
    label=$(seed_label  "$seed")
    target=$(seed_target "$seed")
    result=$(seed_height "$target")
    if [ -z "$result" ] || echo "$result" | grep -q ERR; then
        line+="$label=NA "
    else
        line+="$label=$(echo "$result" | awk '{print $1}') "
    fi
done
echo "$line" >> "$LOG"
