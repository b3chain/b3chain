#!/usr/bin/env bash
#
# Deploy btc-rpc-explorer (https://github.com/janoside/btc-rpc-explorer)
# in a Docker container against the local b3chaind testnet RPC.
#
# Run as root on the seed-1 host AFTER b3chaind-testnet is bootstrapped
# and answering RPC at 127.0.0.1:18534.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

# 1. Install Docker if missing
if ! command -v docker >/dev/null; then
    apt-get update -y
    apt-get install -y --no-install-recommends docker.io
    systemctl enable --now docker
fi

# 2. RPC credentials from the b3chaind config
RPC_PASS=$(cat /etc/b3chain/rpcpassword)
RPC_USER=b3chain

# 3. Start (or replace) the explorer container
docker rm -f b3chain-explorer 2>/dev/null || true

docker run -d \
    --name b3chain-explorer \
    --restart unless-stopped \
    --network host \
    -e BTCEXP_HOST=127.0.0.1 \
    -e BTCEXP_PORT=3002 \
    -e BTCEXP_BITCOIND_HOST=127.0.0.1 \
    -e BTCEXP_BITCOIND_PORT=18534 \
    -e BTCEXP_BITCOIND_USER="$RPC_USER" \
    -e BTCEXP_BITCOIND_PASS="$RPC_PASS" \
    -e BTCEXP_COIN=BTC \
    -e BTCEXP_DEMO=true \
    -e BTCEXP_PRIVACY_MODE=false \
    -e BTCEXP_NO_RATES=true \
    -e BTCEXP_BASIC_AUTH_PASSWORD="" \
    -e BTCEXP_UI_HOME_PAGE_LATEST_BLOCKS_COUNT=10 \
    janoside/btc-rpc-explorer:latest

echo "==> waiting for explorer to be ready"
for i in $(seq 1 30); do
    if curl -sSf http://127.0.0.1:3002/api/blockchain/coins -o /dev/null 2>/dev/null \
       || curl -sSf http://127.0.0.1:3002/ -o /dev/null 2>/dev/null; then
        echo "    explorer responding on 127.0.0.1:3002"
        echo "    add nginx vhost for explorer.b3chain.org reverse-proxying to 127.0.0.1:3002"
        exit 0
    fi
    sleep 2
done

echo "explorer did not start within 60s — check 'docker logs b3chain-explorer'" >&2
exit 1
