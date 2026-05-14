#!/usr/bin/env bash
#
# Install the B3Chain testnet faucet on a host that already has
# b3chaind-testnet.service running and answering RPC at 127.0.0.1:18534.
#
# Run as root.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

APP_DIR=/usr/local/lib/b3chain-faucet
DATA_DIR=/var/lib/b3chain-faucet
LOG_DIR=/var/log/b3chain-faucet
CFG_DIR=/etc/b3chain-faucet
FAUCET_USER=b3chain-faucet

# 1. user
if ! id -u "$FAUCET_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$FAUCET_USER"
fi

# 2. directories
install -d -o "$FAUCET_USER" -g "$FAUCET_USER" -m 750 "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
install -d -m 750 "$CFG_DIR"

# 3. python venv
apt-get update -y
apt-get install -y --no-install-recommends python3-venv python3-pip
sudo -u "$FAUCET_USER" python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install flask gunicorn

# 4. application file
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
install -o "$FAUCET_USER" -g "$FAUCET_USER" -m 644 "$SCRIPT_DIR/app.py" "$APP_DIR/app.py"

# 5. environment file (passwords)
if [ ! -f "$CFG_DIR/faucet.env" ]; then
    if [ ! -r /etc/b3chain/rpcpassword ]; then
        echo "missing /etc/b3chain/rpcpassword (b3chaind-testnet not bootstrapped?)" >&2
        exit 1
    fi
    cat > "$CFG_DIR/faucet.env" <<EOF
B3FAUCET_RPC_HOST=127.0.0.1
B3FAUCET_RPC_PORT=18534
B3FAUCET_RPC_USER=b3chain
B3FAUCET_RPC_PASSWORD_FILE=/etc/b3chain/rpcpassword
B3FAUCET_WALLET=faucet
B3FAUCET_AMOUNT=0.5
B3FAUCET_COOLDOWN_HOURS=24
B3FAUCET_DB=$DATA_DIR/faucet.db
EOF
    chmod 640 "$CFG_DIR/faucet.env"
    chown root:"$FAUCET_USER" "$CFG_DIR/faucet.env"
fi

# 6. ensure faucet user can read /etc/b3chain/rpcpassword
groupadd -f b3chain
usermod -aG b3chain "$FAUCET_USER"
chgrp b3chain /etc/b3chain/rpcpassword
chmod 640 /etc/b3chain/rpcpassword

# 7. ensure the faucet wallet exists; create it if not.
RPC_PASS=$(cat /etc/b3chain/rpcpassword)
have_wallet=$(curl -s --user "b3chain:$RPC_PASS" \
    --data-binary '{"jsonrpc":"1.0","id":"faucet","method":"listwallets","params":[]}' \
    -H 'content-type: application/json' http://127.0.0.1:18534/ \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print("yes" if "faucet" in r else "no")')
if [ "$have_wallet" = "no" ]; then
    curl -s --user "b3chain:$RPC_PASS" \
        --data-binary '{"jsonrpc":"1.0","id":"faucet","method":"createwallet","params":["faucet"]}' \
        -H 'content-type: application/json' http://127.0.0.1:18534/ >/dev/null
    echo "    created wallet 'faucet'"
fi

# 8. systemd unit
install -m 644 "$SCRIPT_DIR/faucet.service" /etc/systemd/system/b3chain-faucet.service
systemctl daemon-reload
systemctl enable b3chain-faucet.service
systemctl restart b3chain-faucet.service

systemctl is-active b3chain-faucet.service
echo "==> Faucet up on 127.0.0.1:5000. Add nginx vhost for faucet.b3chain.org."
