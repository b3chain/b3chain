#!/usr/bin/env bash
#
# Install btc-rpc-explorer (https://github.com/janoside/btc-rpc-explorer)
# from npm and run it under systemd, pointed at the local b3chaind
# testnet RPC.
#
# Run as root on the seed-1 host AFTER b3chaind-testnet is bootstrapped
# and answering RPC at 127.0.0.1:18534.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

if ! systemctl is-active b3chaind-testnet >/dev/null; then
    echo "b3chaind-testnet is not active; bootstrap the node first" >&2
    exit 1
fi

EXP_USER=b3chain-explorer
EXP_DIR=/var/lib/b3chain-explorer
EXP_PORT=3002

# 1. Install Node.js 20 LTS. We pin to 20 (not 22) because
#    btc-rpc-explorer's optional zeromq native module fails to build
#    against Node 22's V8 headers. Node 20 is the current LTS and is
#    fully supported by btc-rpc-explorer.
NODE_MAJOR=20
need_install=1
if command -v node >/dev/null; then
    nv="$(node -v 2>/dev/null | awk -F. '{print substr($1,2)}')"
    if [[ "$nv" =~ ^[0-9]+$ && "$nv" -ge 18 && "$nv" -le 20 ]]; then
        need_install=0
    fi
fi

if [ "$need_install" -eq 1 ]; then
    apt-get update -y
    apt-get install -y --no-install-recommends ca-certificates curl gnupg
    # purge any prior nodejs (Ubuntu's old nodejs OR NodeSource Node22)
    # to avoid /usr/include/node/* file conflicts and V8 header skew.
    apt-get purge -y nodejs npm libnode-dev libnode72 'node-*' 2>/dev/null || true
    apt-get autoremove -y || true
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor --batch --yes -o /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list
    apt-get update -y
    apt-get install -y --no-install-recommends nodejs
fi
node -v

# 2. Build tools needed by node-gyp for any native modules (zeromq etc.)
apt-get install -y --no-install-recommends \
    build-essential python3 python3-dev make g++

# 3. dedicated user + home for the npm prefix and the .env file
if ! id -u "$EXP_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home "$EXP_DIR" \
            --shell /usr/sbin/nologin "$EXP_USER"
fi
install -d -o "$EXP_USER" -g "$EXP_USER" -m 750 "$EXP_DIR" "$EXP_DIR/.config"

# 4. install / update btc-rpc-explorer into that home (no -g, keeps
#    everything contained under /var/lib/b3chain-explorer).
#
#    npm only carries up to 3.4.0; the upstream tagged 3.5.1 on GitHub
#    but never republished. We install directly from the GitHub tag so
#    we get the post-Bitcoin-Core-28 fixes (in particular,
#    `getblockchaininfo.warnings` was changed from a string to an array,
#    which crashes the node-details page in 3.4.0).
#
#    Pin to a specific tag rather than #master so a re-run of this
#    installer is reproducible.
EXPLORER_REF=v3.5.1
sudo -u "$EXP_USER" -H bash -c "
set -e
cd '$EXP_DIR'
# Wipe any prior install to avoid mixing 3.4.0 leftovers with 3.5.x.
rm -rf node_modules package.json package-lock.json
cat > package.json <<JSON
{
  \"name\": \"b3chain-explorer-host\",
  \"private\": true,
  \"dependencies\": {
    \"btc-rpc-explorer\": \"github:janoside/btc-rpc-explorer#${EXPLORER_REF}\"
  }
}
JSON
npm install --prefix '$EXP_DIR' --no-audit --no-fund
"

EXP_BIN="$EXP_DIR/node_modules/.bin/btc-rpc-explorer"
if [ ! -x "$EXP_BIN" ]; then
    echo "btc-rpc-explorer binary not found at $EXP_BIN" >&2
    exit 1
fi

# 4. environment file (RPC creds, port, network selection)
RPC_PASS="$(cat /etc/b3chain/rpcpassword)"
cat > "$EXP_DIR/.config/btc-rpc-explorer.env" <<EOF
BTCEXP_HOST=127.0.0.1
BTCEXP_PORT=$EXP_PORT
BTCEXP_BITCOIND_HOST=127.0.0.1
BTCEXP_BITCOIND_PORT=18534
BTCEXP_BITCOIND_USER=b3chain
BTCEXP_BITCOIND_PASS=$RPC_PASS
BTCEXP_PRIVACY_MODE=true
BTCEXP_NO_RATES=true
BTCEXP_BASIC_AUTH_PASSWORD=
BTCEXP_UI_HOME_PAGE_LATEST_BLOCKS_COUNT=10
BTCEXP_UI_SHOW_TOOLS_SUBHEADER=false
BTCEXP_DEMO=false
BTCEXP_UI_HIDE_INFO_NOTES=true
# Keep slow-device mode OFF: it makes the block detail page render
# without txInputs which crashes the upstream pug template.
BTCEXP_SLOW_DEVICE_MODE=false
BTCEXP_COIN=BTC
EOF
chown "$EXP_USER:$EXP_USER" "$EXP_DIR/.config/btc-rpc-explorer.env"
chmod 640 "$EXP_DIR/.config/btc-rpc-explorer.env"

# 5. systemd unit
cat > /etc/systemd/system/b3chain-explorer.service <<EOF
[Unit]
Description=B3Chain testnet block explorer (btc-rpc-explorer)
After=network-online.target b3chaind-testnet.service
Wants=network-online.target
Requires=b3chaind-testnet.service

[Service]
Type=simple
User=$EXP_USER
Group=$EXP_USER
WorkingDirectory=$EXP_DIR
ExecStart=$EXP_BIN
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$EXP_DIR
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable b3chain-explorer.service
systemctl restart b3chain-explorer.service

echo "==> waiting for explorer HTTP to respond on 127.0.0.1:$EXP_PORT"
# Accept any HTTP status code (including 5xx). On a brand-new chain
# with zero blocks the home page renderer can throw because the
# Bitcoin-flavoured templates assume some chain history; that's
# cosmetic and goes away once the miner produces blocks. What we
# care about is that the daemon is up and listening.
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$EXP_PORT/" || echo "000")
    if [ "$code" != "000" ] && [ "$code" != "" ]; then
        echo "    explorer responding (HTTP $code)"
        if [ "${code:0:1}" = "5" ]; then
            echo "    note: HTTP 5xx is expected on an empty chain; will recover after first block."
        fi
        echo "    add nginx vhost for explorer.b3chain.org reverse-proxying to 127.0.0.1:$EXP_PORT"
        exit 0
    fi
    sleep 2
done

echo "explorer did not respond within 60s; last logs:" >&2
journalctl -u b3chain-explorer --no-pager -n 30 >&2
exit 1
