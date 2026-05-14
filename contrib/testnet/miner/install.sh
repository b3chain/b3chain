#!/usr/bin/env bash
#
# Install b3chain-cpuminer.py as a systemd service that mines testnet
# blocks paying coinbase to a wallet-managed address.
#
# Run as root on the seed-1 host AFTER b3chaind-testnet is bootstrapped.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

if ! systemctl is-active b3chaind-testnet >/dev/null; then
    echo "b3chaind-testnet is not active; bootstrap the node first" >&2
    exit 1
fi

# 1. Copy the miner loop script (from cloned source tree). It uses
#    `b3chain-cli generatetoaddress` so no extra Python dependencies are
#    required on the seed host.
SRC=/usr/local/src/b3chain
install -m 755 "$SRC/contrib/testnet/miner/b3chain-testnet-miner.sh" \
    /usr/local/bin/b3chain-testnet-miner.sh

# 3. Create or load the miner wallet and a coinbase address
RPC_PASS=$(cat /etc/b3chain/rpcpassword)
RPC_USER=b3chain
RPC_URL=http://127.0.0.1:18534

rpc() {
    local method="$1"
    local params="${2:-[]}"
    local path="${3:-/}"
    curl -s --user "$RPC_USER:$RPC_PASS" \
         --data-binary "{\"jsonrpc\":\"1.0\",\"id\":\"miner\",\"method\":\"$method\",\"params\":$params}" \
         -H 'content-type: application/json' "$RPC_URL$path"
}

wallets=$(rpc listwallets | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["result"]))')
if ! echo " $wallets " | grep -q ' miner '; then
    rpc createwallet '["miner"]' >/dev/null
    echo "    created wallet 'miner'"
fi

COINBASE=$(rpc getnewaddress '["miner-coinbase","bech32"]' /wallet/miner \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"])')
echo "    coinbase address: $COINBASE"

# 4. Drop /etc/b3chain/miner.env
cat > /etc/b3chain/miner.env <<EOF
RPC_USER=$RPC_USER
RPC_PASSWORD=$RPC_PASS
COINBASE_ADDR=$COINBASE
EOF
chmod 640 /etc/b3chain/miner.env
chown root:b3chain /etc/b3chain/miner.env

# 5. systemd unit
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
install -m 644 "$SCRIPT_DIR/miner.service" /etc/systemd/system/b3chain-testnet-miner.service
systemctl daemon-reload
systemctl enable b3chain-testnet-miner.service
systemctl restart b3chain-testnet-miner.service

systemctl is-active b3chain-testnet-miner
echo "==> Miner running. Logs: journalctl -u b3chain-testnet-miner -f"
