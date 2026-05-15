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
POOL_DOMAIN=${B3POOL_DOMAIN:-pool.b3chain.org}
ACME_EMAIL=${B3POOL_ACME_EMAIL:-admin@b3chain.org}
WEBROOT=/var/www/b3chain
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. user (use $DATA_DIR as HOME so npm has somewhere to write .npm/)
if ! id -u "$POOL_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir "$DATA_DIR" \
        --shell /usr/sbin/nologin "$POOL_USER"
else
    # Existing user might have been created with a default /home/ path
    # that doesn't exist. Re-anchor it on $DATA_DIR.
    usermod --home "$DATA_DIR" "$POOL_USER" 2>/dev/null || true
fi

# 2. directories
install -d -o "$POOL_USER" -g "$POOL_USER" -m 750 "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
install -d -o "$POOL_USER" -g "$POOL_USER" -m 750 "$RUN_DIR"
# CFG_DIR is owned root:pool-user so the pool user can traverse it to
# read its own root-owned env file (mode 640 root:pool-user).
install -d -o root -g "$POOL_USER" -m 750 "$CFG_DIR"
# Apply on reruns too -- `install -d` does not chown an existing dir.
chown root:"$POOL_USER" "$CFG_DIR"
chmod 750 "$CFG_DIR"
install -d -m 755 "$WEBROOT"

# 3. system packages
# Pre-seed postfix so the apt install does not pop a TUI dialog. We
# only need local delivery for outbound mail from the web service.
DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND
debconf-set-selections <<EOF
postfix postfix/main_mailer_type string Internet Site
postfix postfix/mailname        string ${POOL_DOMAIN}
EOF
apt-get update -y
apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg jq python3 rsync openssl \
    build-essential python3-dev \
    postgresql postfix nginx certbot
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
# Use `npm ci` if a lockfile is checked in, otherwise fall back to
# `npm install` so first-time installs without a committed lockfile
# still work. Either way devDeps are needed at runtime for the CLI
# tools (migrate / pay-now / recompute-pplns / seed-admin) which use
# tsx to run TypeScript directly.
#
# Force npm's cache + log dirs onto $DATA_DIR (where the pool user
# actually has write access) instead of trying to mkdir /home/<user>.
NPM_ENV="HOME=$DATA_DIR npm_config_cache=$DATA_DIR/.npm"
if [ -f "$APP_DIR/package-lock.json" ]; then
    sudo -u "$POOL_USER" bash -lc \
        "cd $APP_DIR && env $NPM_ENV npm ci --no-audit --no-fund && env $NPM_ENV npm run build"
else
    sudo -u "$POOL_USER" bash -lc \
        "cd $APP_DIR && env $NPM_ENV npm install --no-audit --no-fund && env $NPM_ENV npm run build"
fi

# 6. postgres role + db
# Generate a per-host password the first time we install. Persist it
# under $CFG_DIR so reruns of install.sh keep using the same value
# instead of locking the running services out.
PGPASS_FILE="$CFG_DIR/dbpassword"
if [ -s "$PGPASS_FILE" ]; then
    DB_PASSWORD=$(cat "$PGPASS_FILE")
else
    DB_PASSWORD=$(openssl rand -hex 24)
    umask 077
    printf '%s' "$DB_PASSWORD" > "$PGPASS_FILE"
    chown root:"$POOL_USER" "$PGPASS_FILE"
    chmod 640 "$PGPASS_FILE"
fi

if sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${POOL_DB}'" | grep -q 1; then
    sudo -u postgres psql -c "ALTER ROLE ${POOL_DB} WITH LOGIN PASSWORD '${DB_PASSWORD}'"
else
    sudo -u postgres psql -c "CREATE ROLE ${POOL_DB} LOGIN PASSWORD '${DB_PASSWORD}'"
fi
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${POOL_DB}'" \
    | grep -q 1 || sudo -u postgres createdb -O "${POOL_DB}" "${POOL_DB}"

DB_PASSWORD_ENC=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_PASSWORD")

# 7. environment file
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

B3POOL_DB_URL=postgres://${POOL_DB}:${DB_PASSWORD_ENC}@127.0.0.1:5432/${POOL_DB}

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
B3POOL_BASE_URL=https://${POOL_DOMAIN}
B3POOL_COOKIE_SECRET=${COOKIE_SECRET}
B3POOL_SESSION_HOURS=168

B3POOL_SMTP_HOST=127.0.0.1
B3POOL_SMTP_PORT=25
B3POOL_SMTP_FROM="B3Chain Pool <noreply@b3chain.org>"

B3POOL_LOG_LEVEL=info
EOF
    chmod 640 "$CFG_DIR/pool.env"
    chown root:"$POOL_USER" "$CFG_DIR/pool.env"
else
    # On reruns, refresh the DB password line in case it was rotated above.
    sed -i "s|^B3POOL_DB_URL=.*|B3POOL_DB_URL=postgres://${POOL_DB}:${DB_PASSWORD_ENC}@127.0.0.1:5432/${POOL_DB}|" \
        "$CFG_DIR/pool.env"
    # Quote SMTP_FROM if an older install.sh wrote it unquoted (the
    # bare `<` would otherwise be interpreted as a redirect when the
    # CLI tools `. /etc/b3chain-pool/pool.env`). Only match lines that
    # do not already start with a quote.
    sed -i 's|^B3POOL_SMTP_FROM=\([^"].*<.*>.*\)$|B3POOL_SMTP_FROM="\1"|' \
        "$CFG_DIR/pool.env"
fi

# 8. ensure pool user can read RPC password
groupadd -f b3chain
usermod -aG b3chain "$POOL_USER"
chgrp b3chain /etc/b3chain/rpcpassword
chmod 640 /etc/b3chain/rpcpassword

# 9. apply migrations (load env file the same way systemd does)
sudo -u "$POOL_USER" bash -lc \
    "cd $APP_DIR && env $NPM_ENV bash -c 'set -a && . $CFG_DIR/pool.env && set +a && npm run migrate'"

# 10. ensure the pool-payouts wallet exists (use jq, not python, for parsing)
RPC_PASS=$(cat /etc/b3chain/rpcpassword)
RPC_URL=http://127.0.0.1:18534

rpc() {
    # rpc <method> [params-json] [/wallet/<name>]
    local method=$1 params=${2:-[]} wallet=${3:-}
    curl -fsS --user "b3chain:$RPC_PASS" \
        --data-binary "{\"jsonrpc\":\"1.0\",\"id\":\"pool\",\"method\":\"$method\",\"params\":$params}" \
        -H 'content-type: application/json' "${RPC_URL}${wallet}"
}

WALLETS_JSON=$(rpc listwallets)
if ! echo "$WALLETS_JSON" | jq -er '.result[]' 2>/dev/null | grep -qx 'pool-payouts'; then
    rpc createwallet '["pool-payouts"]' >/dev/null
    echo "    created wallet 'pool-payouts'"
fi

# 10a. ensure a payout address is pinned in pool.env. The stratum
# coinbase will pay the block subsidy to this exact bech32 address;
# we generate it once from the pool-payouts wallet so reruns of
# install.sh keep using the same address.
if ! grep -q '^B3POOL_PAYOUT_ADDRESS=' "$CFG_DIR/pool.env"; then
    PAYOUT_ADDR=$(rpc getnewaddress '["pool-coinbase","bech32"]' /wallet/pool-payouts \
        | jq -r '.result')
    if [ -z "$PAYOUT_ADDR" ] || [ "$PAYOUT_ADDR" = "null" ]; then
        echo "ERROR: could not allocate payout address from pool-payouts wallet" >&2
        exit 1
    fi
    echo "B3POOL_PAYOUT_ADDRESS=$PAYOUT_ADDR" >> "$CFG_DIR/pool.env"
    echo "    pinned payout address: $PAYOUT_ADDR"
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

# 12. nginx vhost: install bootstrap (HTTP-only) first, then certbot,
#     then swap in the full HTTPS vhost. Idempotent: if a TLS cert
#     for ${POOL_DOMAIN} already exists, skip straight to the HTTPS
#     vhost.
NGX_AVAILABLE=/etc/nginx/sites-available
NGX_ENABLED=/etc/nginx/sites-enabled

install -m 644 "$SCRIPT_DIR/nginx/pool.b3chain.org-bootstrap.conf" \
    "$NGX_AVAILABLE/pool.b3chain.org.conf"
ln -sf "$NGX_AVAILABLE/pool.b3chain.org.conf" \
    "$NGX_ENABLED/pool.b3chain.org.conf"
nginx -t
systemctl reload nginx

if [ ! -e "/etc/letsencrypt/live/${POOL_DOMAIN}/fullchain.pem" ]; then
    echo "==> requesting Let's Encrypt cert for ${POOL_DOMAIN}"
    certbot certonly --webroot -w "$WEBROOT" -d "$POOL_DOMAIN" \
        --non-interactive --agree-tos --email "$ACME_EMAIL" \
        --keep-until-expiring
fi

# Now install the full HTTPS vhost (overwrites the bootstrap file).
install -m 644 "$SCRIPT_DIR/nginx/pool.b3chain.org.conf" \
    "$NGX_AVAILABLE/pool.b3chain.org.conf"
nginx -t
systemctl reload nginx

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
echo "    Web    : https://${POOL_DOMAIN}"
echo "    Logs   : ${LOG_DIR}/"
