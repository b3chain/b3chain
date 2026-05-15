#!/usr/bin/env bash
#
# Install the B3Chain Stratum mining pool on a host that already has
# b3chaind-testnet.service running and answering RPC at 127.0.0.1:18534.
#
# Run as root.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

APP_DIR=/usr/local/lib/b3chain-pool
DATA_DIR=/var/lib/b3chain-pool
LOG_DIR=/var/log/b3chain-pool
RUN_DIR=/run/b3chain-pool
CFG_DIR=/etc/b3chain-pool
POOL_USER=b3chain-pool
POOL_DB=b3chain_pool
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. user
if ! id -u "$POOL_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$POOL_USER"
fi

# 2. directories
install -d -o "$POOL_USER" -g "$POOL_USER" -m 750 "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
install -d -o "$POOL_USER" -g "$POOL_USER" -m 750 "$RUN_DIR"
install -d -m 750 "$CFG_DIR"

# 3. node + postgres + postfix
apt-get update -y
apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg postgresql postfix nginx
if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y --no-install-recommends nodejs
fi

# 4. application files
rsync -a --delete \
    --exclude='node_modules' --exclude='dist' \
    --exclude='.env' --exclude='docker-compose.dev.yml' \
    --exclude='tests' \
    "$SCRIPT_DIR/" "$APP_DIR/"
chown -R "$POOL_USER:$POOL_USER" "$APP_DIR"

# 5. node deps + build
sudo -u "$POOL_USER" -H bash -lc "cd $APP_DIR && npm ci && npm run build"

# 6. environment file
if [ ! -f "$CFG_DIR/pool.env" ]; then
    if [ ! -r /etc/b3chain/rpcpassword ]; then
        echo "missing /etc/b3chain/rpcpassword (b3chaind-testnet not bootstrapped?)" >&2
        exit 1
    fi
    COOKIE_SECRET=$(openssl rand -hex 32)
    cat > "$CFG_DIR/pool.env" <<EOF
B3POOL_RPC_HOST=127.0.0.1
B3POOL_RPC_PORT=18534
B3POOL_RPC_USER=b3chain
B3POOL_RPC_PASSWORD_FILE=/etc/b3chain/rpcpassword
B3POOL_PAYOUT_WALLET=pool-payouts
B3POOL_NETWORK=testnet

B3POOL_DB_URL=postgres://${POOL_DB}@127.0.0.1:5432/${POOL_DB}

B3POOL_STRATUM_BIND=0.0.0.0
B3POOL_STRATUM_PORT=3333
B3POOL_STRATUM_DEFAULT_DIFF=1024
B3POOL_STRATUM_VARDIFF_TARGET_S=10
B3POOL_STRATUM_VARDIFF_RETUNE_S=30
B3POOL_FEE_PERCENT=1.0

B3POOL_TEMPLATE_POLL_MS=2000
B3POOL_PAYOUT_INTERVAL_MS=3600000
B3POOL_BLOCK_CONFIRMATIONS=100
B3POOL_PPLNS_N_SHARES=4032
B3POOL_SHARE_SOCKET=${RUN_DIR}/share.sock

B3POOL_WEB_BIND=127.0.0.1
B3POOL_WEB_PORT=5100
B3POOL_BASE_URL=https://pool.b3chain.org
B3POOL_COOKIE_SECRET=${COOKIE_SECRET}
B3POOL_SESSION_HOURS=168

B3POOL_SMTP_HOST=127.0.0.1
B3POOL_SMTP_PORT=25
B3POOL_SMTP_FROM=B3Chain Pool <noreply@b3chain.org>

B3POOL_LOG_LEVEL=info
EOF
    chmod 640 "$CFG_DIR/pool.env"
    chown root:"$POOL_USER" "$CFG_DIR/pool.env"
fi

# 7. ensure pool user can read RPC password
groupadd -f b3chain
usermod -aG b3chain "$POOL_USER"
chgrp b3chain /etc/b3chain/rpcpassword
chmod 640 /etc/b3chain/rpcpassword

# 8. postgres role + db
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${POOL_DB}'" \
    | grep -q 1 || sudo -u postgres createuser --no-superuser --no-createdb --no-createrole "${POOL_DB}"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${POOL_DB}'" \
    | grep -q 1 || sudo -u postgres createdb -O "${POOL_DB}" "${POOL_DB}"

# 9. apply migrations
sudo -u "$POOL_USER" -H bash -lc "cd $APP_DIR && npm run migrate"

# 10. ensure the pool-payouts wallet exists
RPC_PASS=$(cat /etc/b3chain/rpcpassword)
have_wallet=$(curl -s --user "b3chain:$RPC_PASS" \
    --data-binary '{"jsonrpc":"1.0","id":"pool","method":"listwallets","params":[]}' \
    -H 'content-type: application/json' http://127.0.0.1:18534/ \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print("yes" if "pool-payouts" in r else "no")')
if [ "$have_wallet" = "no" ]; then
    curl -s --user "b3chain:$RPC_PASS" \
        --data-binary '{"jsonrpc":"1.0","id":"pool","method":"createwallet","params":["pool-payouts"]}' \
        -H 'content-type: application/json' http://127.0.0.1:18534/ >/dev/null
    echo "    created wallet 'pool-payouts'"
fi

# 11. systemd units
install -m 644 "$SCRIPT_DIR/systemd/b3chain-pool-stratum.service" /etc/systemd/system/
install -m 644 "$SCRIPT_DIR/systemd/b3chain-pool-daemon.service"  /etc/systemd/system/
install -m 644 "$SCRIPT_DIR/systemd/b3chain-pool-web.service"     /etc/systemd/system/
install -m 644 "$SCRIPT_DIR/systemd/b3chain-pool.target"          /etc/systemd/system/
systemctl daemon-reload
systemctl enable b3chain-pool.target b3chain-pool-stratum.service \
    b3chain-pool-daemon.service b3chain-pool-web.service
systemctl restart b3chain-pool-daemon.service
systemctl restart b3chain-pool-stratum.service
systemctl restart b3chain-pool-web.service

# 12. nginx vhost (operator must set up TLS via certbot first)
if [ ! -e /etc/nginx/sites-enabled/pool.b3chain.org.conf ]; then
    install -m 644 "$SCRIPT_DIR/nginx/pool.b3chain.org.conf" \
        /etc/nginx/sites-available/pool.b3chain.org.conf
    ln -sf /etc/nginx/sites-available/pool.b3chain.org.conf \
        /etc/nginx/sites-enabled/pool.b3chain.org.conf
    echo "==> Installed nginx vhost. Run certbot for pool.b3chain.org, then:"
    echo "    nginx -t && systemctl reload nginx"
fi

# 13. logrotate
cat > /etc/logrotate.d/b3chain-pool <<EOF
${LOG_DIR}/*.log {
    daily
    rotate 14
    missingok
    compress
    delaycompress
    notifempty
    copytruncate
}
EOF

# 14. UFW (open stratum)
if command -v ufw >/dev/null 2>&1; then
    ufw allow 3333/tcp || true
fi

systemctl is-active b3chain-pool-stratum.service
systemctl is-active b3chain-pool-daemon.service
systemctl is-active b3chain-pool-web.service
echo "==> Pool services up."
echo "    Stratum: 0.0.0.0:3333"
echo "    Web    : 127.0.0.1:5100 (front with nginx)"
echo "    Logs   : ${LOG_DIR}/"
