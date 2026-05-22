#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=15 deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
set -e
echo "=== node version pre ==="
node -v 2>/dev/null || echo "no node"

if ! node -v 2>/dev/null | grep -qE '^v(20|22|24)\.'; then
    echo "=== installing Node 20 from NodeSource ==="
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
fi

echo "=== node version post ==="
node -v
npm -v

echo "=== apt: mariadb-server + build-essential + python3 + libssl-dev ==="
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    mariadb-server mariadb-client \
    build-essential pkg-config python3 libssl-dev

systemctl enable --now mariadb || true
systemctl is-active --quiet mariadb && echo "mariadb: active"

echo
echo "=== ZMQ snippet on b3chaind ==="
mkdir -p /etc/b3chain/conf.d
cat > /etc/b3chain/conf.d/zmq.conf <<'EOF'
zmqpubrawtx=tcp://127.0.0.1:28332
zmqpubrawblock=tcp://127.0.0.1:28333
zmqpubhashtx=tcp://127.0.0.1:28334
zmqpubhashblock=tcp://127.0.0.1:28335
zmqpubsequence=tcp://127.0.0.1:28336
EOF
chown root:b3chain /etc/b3chain/conf.d/zmq.conf
chmod 0640 /etc/b3chain/conf.d/zmq.conf

if ! grep -q '^includeconf=conf\.d/zmq\.conf' /etc/b3chain/b3chain.conf; then
    echo "includeconf=conf.d/zmq.conf" >> /etc/b3chain/b3chain.conf
    echo "==> appended includeconf to b3chain.conf"
fi

echo
echo "=== restarting b3chaind-testnet to pick up ZMQ ==="
systemctl restart b3chaind-testnet.service
sleep 3
systemctl is-active --quiet b3chaind-testnet.service && echo "b3chaind-testnet: active"

echo
echo "=== verifying ZMQ pubs ==="
b3chain-cli -chain=test \
    -conf=/etc/b3chain/b3chain.conf \
    -datadir=/var/lib/b3chain/.b3chain getzmqnotifications 2>&1 | head -30

echo
echo "=== prestage done ==="
REMOTE
