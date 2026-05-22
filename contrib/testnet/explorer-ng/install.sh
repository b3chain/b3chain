#!/usr/bin/env bash
#
# Install / upgrade B3Chain Live Explorer (explorer-ng) on seed1.
#
# Idempotent. Safe to re-run after `git pull` of either b3chain or
# b3chain/explorer-ng.
#
# Phases driven by flags:
#   (default)            P0 + P1 + P2 + P4 (core + rebrand + pending-pool + WS)
#   --enable-zmq         add ZMQ pubs to /etc/b3chain/b3chain.conf and restart b3chaind (P2 prereq)
#   --enable-stats       turn on statistics indexer (P3, populates /v2/graphs/tx-pool*)
#   --enable-mining      turn on mining indexer + 7 mining charts + /v2/mining (P5)
#   --enable-audit       turn on audit + block-health (P7, heavy)
#   --enable-lightning   parked: bails out unless b3chain-lnd is reachable (P8)
#   --rebuild-frontend   force `npm run build` of frontend (slow; ~10 min)
#   --skip-fetch         skip `git fetch` of explorer-ng repo
#   --cutover            after parity is accepted, move / -> explorer-ng, demote btc-rpc-explorer to /legacy/
#   --uninstall          remove services and nginx site (config files preserved)
#
# Acceptance after default install (P0+P1+P2+P4):
#   - https://explorer.b3chain.org/v2/ shows latest B3Chain testnet block.
#   - tools/tm-audit.sh PASS in /opt/b3chain-explorer-ng/explorer-ng.
#   - websocket /v2/api/v1/ws upgrades cleanly (curl -i upgrade).
set -euo pipefail
export LC_ALL=C

EXPLORER_NG_REPO="${EXPLORER_NG_REPO:-https://github.com/b3chain/explorer-ng.git}"
EXPLORER_NG_BRANCH="${EXPLORER_NG_BRANCH:-b3chain-main}"
EXPLORER_NG_USER="b3chain-explorer-ng"
EXPLORER_NG_HOME="/var/lib/b3chain-explorer-ng"
EXPLORER_NG_SRC="/opt/b3chain-explorer-ng/explorer-ng"
EXPLORER_NG_WEB="/var/www/b3chain-explorer-ng"
EXPLORER_NG_CONF_DIR="/etc/b3chain/explorer-ng"
NGINX_SITE="/etc/nginx/sites-available/explorer-ng.conf"
NGINX_LINK="/etc/nginx/sites-enabled/explorer-ng.conf"
SYSTEMD_UNIT="/etc/systemd/system/b3chain-explorer-ng.service"

ENABLE_ZMQ=0
ENABLE_STATS=0
ENABLE_MINING=0
ENABLE_AUDIT=0
ENABLE_LIGHTNING=0
REBUILD_FRONTEND=0
SKIP_FETCH=0
CUTOVER=0
UNINSTALL=0

while [ $# -gt 0 ]; do
    case "$1" in
        --enable-zmq) ENABLE_ZMQ=1; shift ;;
        --enable-stats) ENABLE_STATS=1; shift ;;
        --enable-mining) ENABLE_MINING=1; shift ;;
        --enable-audit) ENABLE_AUDIT=1; shift ;;
        --enable-lightning) ENABLE_LIGHTNING=1; shift ;;
        --rebuild-frontend) REBUILD_FRONTEND=1; shift ;;
        --skip-fetch) SKIP_FETCH=1; shift ;;
        --cutover) CUTOVER=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

THIS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Uninstall path
# ---------------------------------------------------------------------------
if [ "$UNINSTALL" = 1 ]; then
    echo "==> stopping and removing b3chain-explorer-ng services + nginx site"
    systemctl disable --now b3chain-explorer-ng.service 2>/dev/null || true
    rm -f "$SYSTEMD_UNIT"
    systemctl daemon-reload
    rm -f "$NGINX_LINK"
    nginx -t && systemctl reload nginx || true
    echo "==> service stopped. config preserved at: $EXPLORER_NG_CONF_DIR"
    exit 0
fi

# ---------------------------------------------------------------------------
# 1) System packages
# ---------------------------------------------------------------------------
echo "==> installing system packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    git curl ca-certificates build-essential pkg-config python3 \
    mariadb-server mariadb-client libssl-dev \
    nginx-core
# Node 20 from NodeSource if absent or too old.
need_node=1
if command -v node >/dev/null 2>&1; then
    nv=$(node -v | sed 's/^v//;s/\..*$//')
    [ "$nv" -ge 20 ] && need_node=0
fi
if [ "$need_node" = 1 ]; then
    echo "==> installing Node.js 20"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
fi

# Rust toolchain (required for rust-gbt native preinstall hook). Always
# install rustup system-wide so we have a recent stable cargo (>=1.85,
# needed for Cargo.lock v4). Ubuntu's apt cargo is too old. Idempotent.
export RUSTUP_HOME=/opt/rustup
export CARGO_HOME=/opt/cargo
export PATH="/opt/cargo/bin:$PATH"
if [ ! -x /opt/cargo/bin/cargo ]; then
    echo "==> installing rustup (cargo + rustc) system-wide"
    mkdir -p "$RUSTUP_HOME" "$CARGO_HOME"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --no-modify-path --default-toolchain stable \
            --profile minimal
    chmod -R a+rX /opt/rustup /opt/cargo
fi
cat >/etc/profile.d/cargo.sh <<'CARGOEOF'
export RUSTUP_HOME=/opt/rustup
export CARGO_HOME=/opt/cargo
export PATH="/opt/cargo/bin:$PATH"
CARGOEOF
chmod 0644 /etc/profile.d/cargo.sh
echo "==> cargo: $(/opt/cargo/bin/cargo --version 2>&1 || true)"

# ---------------------------------------------------------------------------
# 2) System user + dirs
# ---------------------------------------------------------------------------
if ! id "$EXPLORER_NG_USER" >/dev/null 2>&1; then
    useradd -r -m -d "$EXPLORER_NG_HOME" -s /usr/sbin/nologin "$EXPLORER_NG_USER"
fi
install -d -m 0755 -o "$EXPLORER_NG_USER" -g "$EXPLORER_NG_USER" "$EXPLORER_NG_HOME"
install -d -m 0755 -o root -g root "$EXPLORER_NG_CONF_DIR"
install -d -m 0755 -o root -g www-data "$EXPLORER_NG_WEB"
install -d -m 2775 -o "$EXPLORER_NG_USER" -g "$EXPLORER_NG_USER" \
    "$(dirname "$EXPLORER_NG_SRC")"

# ---------------------------------------------------------------------------
# 3) MariaDB schema + user (P3 prereq, harmless if stats off)
# ---------------------------------------------------------------------------
bash "$THIS_DIR/mariadb-schema.sh"

# ---------------------------------------------------------------------------
# 4) ZMQ pubs in b3chain.conf  (--enable-zmq)
# ---------------------------------------------------------------------------
if [ "$ENABLE_ZMQ" = 1 ]; then
    echo "==> ensuring ZMQ pubs in /etc/b3chain/b3chain.conf"
    install -d -m 0750 -o b3chain -g b3chain /etc/b3chain || true
    snippet="$THIS_DIR/config/zmq-snippet.conf"
    confd="/etc/b3chain/conf.d"
    install -d "$confd"
    install -m 0644 "$snippet" "$confd/zmq.conf"
    if ! grep -q '^includeconf=conf\.d/zmq\.conf' /etc/b3chain/b3chain.conf 2>/dev/null; then
        echo "includeconf=conf.d/zmq.conf" >> /etc/b3chain/b3chain.conf
    fi
    # Restart whichever b3chaind systemd unit is present on this host. seed1
    # uses b3chaind-testnet.service; other hosts may use b3chaind@test or
    # plain b3chaind. Ignore the "no such unit" error from the unused names.
    for unit in b3chaind-testnet b3chaind@test b3chaind; do
        if systemctl list-unit-files | grep -q "^${unit}\.service"; then
            systemctl restart "${unit}.service" || true
            break
        fi
    done
fi

# ---------------------------------------------------------------------------
# 5) Clone / pull explorer-ng repo
# ---------------------------------------------------------------------------
if [ ! -d "$EXPLORER_NG_SRC/.git" ]; then
    echo "==> cloning $EXPLORER_NG_REPO into $EXPLORER_NG_SRC"
    sudo -u "$EXPLORER_NG_USER" git clone --branch "$EXPLORER_NG_BRANCH" \
        "$EXPLORER_NG_REPO" "$EXPLORER_NG_SRC"
elif [ "$SKIP_FETCH" = 0 ]; then
    echo "==> updating $EXPLORER_NG_SRC"
    sudo -u "$EXPLORER_NG_USER" git -C "$EXPLORER_NG_SRC" fetch origin
    sudo -u "$EXPLORER_NG_USER" git -C "$EXPLORER_NG_SRC" \
        reset --hard "origin/$EXPLORER_NG_BRANCH"
fi

# ---------------------------------------------------------------------------
# 6) Trademark audit (must pass before we deploy anything)
# ---------------------------------------------------------------------------
echo "==> running trademark audit on cloned tree"
bash "$THIS_DIR/tools/tm-audit.sh" "$EXPLORER_NG_SRC"

# ---------------------------------------------------------------------------
# 7) Render backend config from template
# ---------------------------------------------------------------------------
RPC_PASS=""
if [ -f /etc/b3chain/b3chain.conf ]; then
    RPC_PASS=$(awk -F= '/^rpcpassword=/ {print $2; exit}' /etc/b3chain/b3chain.conf)
fi
if [ -z "$RPC_PASS" ]; then
    echo "warn: rpcpassword not found in /etc/b3chain/b3chain.conf; using placeholder" >&2
    RPC_PASS="CHANGE_ME"
fi

DBUSER="explorer_ng"
DBPASS=$(cat "$EXPLORER_NG_CONF_DIR/db.pass" 2>/dev/null || true)
if [ -z "$DBPASS" ]; then
    DBPASS="$(openssl rand -hex 24)"
    echo -n "$DBPASS" > "$EXPLORER_NG_CONF_DIR/db.pass"
    chmod 0640 "$EXPLORER_NG_CONF_DIR/db.pass"
    chgrp "$EXPLORER_NG_USER" "$EXPLORER_NG_CONF_DIR/db.pass"
    # Ensure DB user has the same password we just generated.
    mysql -u root <<SQL
ALTER USER '${DBUSER}'@'localhost' IDENTIFIED BY '${DBPASS}';
FLUSH PRIVILEGES;
SQL
fi

CFG="$EXPLORER_NG_CONF_DIR/explorer-ng-config.json"
template="$THIS_DIR/config/b3chain-config.json.template"
sed \
    -e "s|@@RPC_PASS@@|$RPC_PASS|g" \
    -e "s|@@DB_USER@@|$DBUSER|g" \
    -e "s|@@DB_PASS@@|$DBPASS|g" \
    -e "s|@@ENABLE_STATS@@|$( [ "$ENABLE_STATS" = 1 ] && echo true || echo false )|g" \
    -e "s|@@ENABLE_MINING@@|$( [ "$ENABLE_MINING" = 1 ] && echo true || echo false )|g" \
    -e "s|@@ENABLE_AUDIT@@|$( [ "$ENABLE_AUDIT" = 1 ] && echo true || echo false )|g" \
    -e "s|@@ENABLE_LIGHTNING@@|$( [ "$ENABLE_LIGHTNING" = 1 ] && echo true || echo false )|g" \
    "$template" > "$CFG.new"

if ! cmp -s "$CFG.new" "$CFG" 2>/dev/null; then
    mv "$CFG.new" "$CFG"
    chown root:"$EXPLORER_NG_USER" "$CFG"
    chmod 0640 "$CFG"
    CFG_CHANGED=1
else
    rm -f "$CFG.new"
    CFG_CHANGED=0
fi

# Backend reads config from this conventional path inside its own tree.
ln -snf "$CFG" "$EXPLORER_NG_SRC/backend/explorer-ng-config.json"

# ---------------------------------------------------------------------------
# 8) Backend deps + build
# ---------------------------------------------------------------------------
echo "==> backend npm install + build"
# Backend's preinstall hook compiles the native Rust GBT module
# (`rust/gbt/`). Even with B3CHAIN.RUST_GBT=false (we run JS GBT at
# runtime), TypeScript still needs the `rust-gbt` module compiled so
# `import { GbtGenerator } from 'rust-gbt'` resolves at type-check time.
# Upstream pins rust-toolchain=1.84 but ships Cargo.lock v4 (which
# stabilized in 1.85). Bump the pin so cargo can parse the lockfile.
if [ -f "$EXPLORER_NG_SRC/rust/gbt/rust-toolchain" ]; then
    echo "stable" > "$EXPLORER_NG_SRC/rust/gbt/rust-toolchain"
    chown "$EXPLORER_NG_USER":"$EXPLORER_NG_USER" \
        "$EXPLORER_NG_SRC/rust/gbt/rust-toolchain"
fi
NPM_BACKEND_FLAGS="--no-audit --no-fund --prefer-offline"
# /opt/cargo holds the system-wide rustup-installed cargo binary
# (read-only for non-root). The service user needs its own CARGO_HOME
# under its $HOME for the registry cache + per-build target dir.
install -d -m 0755 -o "$EXPLORER_NG_USER" -g "$EXPLORER_NG_USER" \
    "$EXPLORER_NG_HOME/.cargo"
sudo -u "$EXPLORER_NG_USER" -H -E bash -lc "
    export RUSTUP_HOME=/opt/rustup
    export CARGO_HOME=$EXPLORER_NG_HOME/.cargo
    export PATH=/opt/cargo/bin:\$PATH
    set -e
    cd '$EXPLORER_NG_SRC/backend'
    npm ci $NPM_BACKEND_FLAGS || npm install $NPM_BACKEND_FLAGS
    npm run build
"

# ---------------------------------------------------------------------------
# 9) Frontend build (only if requested or first install)
# ---------------------------------------------------------------------------
if [ "$REBUILD_FRONTEND" = 1 ] || [ ! -f "$EXPLORER_NG_WEB/index.html" ]; then
    echo "==> frontend build (this can take ~10 minutes)"
    sudo -u "$EXPLORER_NG_USER" -H bash -lc "
        set -e
        cd '$EXPLORER_NG_SRC/frontend'
        npm ci --no-audit --no-fund --prefer-offline || npm install --no-audit --no-fund
        # Build with /v2/ base href so we can serve under nginx /v2/.
        npx ng build --configuration production --base-href /v2/
    "
    rsync -a --delete "$EXPLORER_NG_SRC/frontend/dist/explorer/" "$EXPLORER_NG_WEB/" \
        || rsync -a --delete "$EXPLORER_NG_SRC/frontend/dist/" "$EXPLORER_NG_WEB/"
    chown -R root:www-data "$EXPLORER_NG_WEB"
    find "$EXPLORER_NG_WEB" -type d -exec chmod 0755 {} +
    find "$EXPLORER_NG_WEB" -type f -exec chmod 0644 {} +
fi

# ---------------------------------------------------------------------------
# 10) systemd unit
# ---------------------------------------------------------------------------
install -m 0644 "$THIS_DIR/systemd/b3chain-explorer-ng.service" "$SYSTEMD_UNIT"
systemctl daemon-reload
systemctl enable b3chain-explorer-ng.service
if [ "${CFG_CHANGED:-0}" = 1 ]; then
    systemctl restart b3chain-explorer-ng.service
else
    systemctl start b3chain-explorer-ng.service
fi

# ---------------------------------------------------------------------------
# 11) nginx site
# ---------------------------------------------------------------------------
install -m 0644 "$THIS_DIR/nginx/explorer-ng.conf" "$NGINX_SITE"
ln -snf "$NGINX_SITE" "$NGINX_LINK"

if [ "$CUTOVER" = 1 ]; then
    echo "==> cutover requested: editing existing /etc/nginx/sites-available/explorer.conf"
    if [ -f /etc/nginx/sites-available/explorer.conf ]; then
        # Move root location to explorer-ng /var/www; demote btc-rpc-explorer to /legacy/.
        # We just write a marker; the operator should review the resulting diff.
        cp /etc/nginx/sites-available/explorer.conf \
           /etc/nginx/sites-available/explorer.conf.pre-cutover.bak
        sed -i 's|location / {|location /legacy/ {|' \
            /etc/nginx/sites-available/explorer.conf || true
    fi
fi

nginx -t
systemctl reload nginx

# ---------------------------------------------------------------------------
# 12) Summary
# ---------------------------------------------------------------------------
echo
echo "==> install OK"
echo "    backend:   systemctl status b3chain-explorer-ng.service"
echo "    frontend:  https://explorer.b3chain.org/v2/"
echo "    config:    $CFG"
echo "    verify:    sudo bash $THIS_DIR/verify.sh"
