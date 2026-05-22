#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
set -e

# Find the b3chain conf
CONF=$(find /etc/b3chain /var/lib/b3chain -name 'b3chain.conf' 2>/dev/null | head -1)
echo "==> conf: $CONF"
if [ -z "$CONF" ]; then
    echo "ERROR: b3chain.conf not found"
    exit 1
fi
echo "==> current relevant lines:"
grep -E '^(txindex|chain|test|server|rpc)' "$CONF" || true

# Add txindex=1 if not present
if ! grep -q '^txindex=' "$CONF"; then
    echo "==> adding txindex=1"
    echo "txindex=1" >> "$CONF"
fi

# Find systemd unit name for b3chaind
UNIT=$(systemctl list-units --type=service --no-pager --plain | grep b3chaind | awk '{print $1}' | head -1)
echo "==> b3chaind unit: $UNIT"
if [ -z "$UNIT" ]; then
    echo "ERROR: b3chaind unit not found"
    exit 1
fi

systemctl restart "$UNIT"
sleep 5
systemctl is-active "$UNIT"
echo "==> waiting for reindex to start..."
sleep 5
b3chain-cli -chain=test -conf=/etc/b3chain/b3chain.conf -datadir=/var/lib/b3chain/.b3chain getblockchaininfo 2>&1 | head -15
REMOTE
