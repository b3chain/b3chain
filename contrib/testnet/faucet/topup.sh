#!/usr/bin/env bash
#
# Faucet auto-topup. Run from cron on the host that has both the
# `miner` wallet (where coinbase rewards land) and the `faucet`
# wallet (which the public faucet hands out from). When the faucet
# wallet's spendable balance drops below MIN, send TOPUP from miner
# to a fresh faucet address.
#
# Configured via /etc/b3chain-faucet/topup.env. Logs to syslog AND
# /var/log/b3chain-faucet/topup.log.

export LC_ALL=C
set -uo pipefail

CFG=/etc/b3chain-faucet/topup.env
[ -f "$CFG" ] && . "$CFG"

: "${RPC_HOST:=127.0.0.1}"
: "${RPC_PORT:=18534}"
: "${RPC_USER:=b3chain}"
: "${RPC_PASSWORD_FILE:=/etc/b3chain/rpcpassword}"
: "${FAUCET_WALLET:=faucet}"
: "${MINER_WALLET:=miner}"
: "${MIN:=2.0}"      # B3C - top up when faucet falls below this
: "${TOPUP:=10.0}"   # B3C - amount to send miner -> faucet
: "${LOG:=/var/log/b3chain-faucet/topup.log}"
: "${MIN_MATURE_BALANCE:=11.0}"  # don't try to send if miner has less
# Explicit fee rate (sat/vB) used for the topup tx. On a young chain
# `estimatesmartfee` returns nothing and the wallet refuses to send
# unless either `-fallbackfee` is configured OR the caller passes an
# explicit `fee_rate`. We pass the explicit rate as a defensive
# fallback even when fallbackfee is set in b3chain.conf.
: "${FEE_RATE:=1}"   # sat/vB

PASS=$(cat "$RPC_PASSWORD_FILE" 2>/dev/null || echo "")
mkdir -p "$(dirname "$LOG")"

ts() { date -u +%FT%TZ; }
log() { echo "$(ts) $*" | tee -a "$LOG"; }

rpc() {
    # rpc <wallet> <method> [json-array of params]
    local wallet=$1 method=$2 params=${3:-[]}
    curl -sS --max-time 10 \
        --user "$RPC_USER:$PASS" \
        --data-binary "{\"jsonrpc\":\"1.0\",\"id\":\"topup\",\"method\":\"$method\",\"params\":$params}" \
        -H 'content-type: application/json' \
        "http://$RPC_HOST:$RPC_PORT/wallet/$wallet"
}

balance() {
    rpc "$1" getbalance \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result", 0))'
}

faucet_bal=$(balance "$FAUCET_WALLET")
miner_bal=$(balance "$MINER_WALLET")

if [ -z "$faucet_bal" ] || [ -z "$miner_bal" ]; then
    log "ERR could not read balances (faucet=$faucet_bal miner=$miner_bal); is b3chaind up?"
    exit 1
fi

# python comparison so we accept floats
need=$(python3 -c "print('yes' if float('$faucet_bal') < float('$MIN') else 'no')")
if [ "$need" = "no" ]; then
    log "OK faucet=$faucet_bal >= MIN=$MIN (miner=$miner_bal); no topup needed"
    exit 0
fi

enough=$(python3 -c "print('yes' if float('$miner_bal') >= float('$MIN_MATURE_BALANCE') else 'no')")
if [ "$enough" = "no" ]; then
    log "WARN faucet=$faucet_bal < MIN=$MIN BUT miner=$miner_bal < $MIN_MATURE_BALANCE (insufficient mature coins); waiting"
    exit 0
fi

# get a fresh receive address from the faucet wallet
addr=$(rpc "$FAUCET_WALLET" getnewaddress '["topup", "bech32"]' \
       | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result", ""))')
if [ -z "$addr" ]; then
    log "ERR could not get faucet address"
    exit 1
fi

# send from miner wallet. sendtoaddress positional args
# (Bitcoin Core 22+ / B3Chain Core 30):
#   [address, amount, comment, comment_to, subtractfeefromamount,
#    replaceable, conf_target, estimate_mode, avoid_reuse, fee_rate]
# We pin fee_rate=1 sat/vB so the call always succeeds even if
# `estimatesmartfee` has no data and `fallbackfee` is unset.
res=$(rpc "$MINER_WALLET" sendtoaddress "[\"$addr\", $TOPUP, \"\", \"\", false, false, null, \"unset\", false, $FEE_RATE]")
txid=$(echo "$res" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("result") or "ERR:"+str(d.get("error")))')
log "SENT $TOPUP B3C: $MINER_WALLET -> $FAUCET_WALLET ($addr) tx=$txid (faucet was $faucet_bal, miner $miner_bal)"
