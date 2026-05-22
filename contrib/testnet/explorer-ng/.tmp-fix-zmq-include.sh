#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=15 deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
set -e
echo "==> removing broken includeconf line and copying zmq.conf into datadir"

DATADIR=/var/lib/b3chain/.b3chain
mkdir -p "$DATADIR/conf.d"
cp /etc/b3chain/conf.d/zmq.conf "$DATADIR/conf.d/zmq.conf"
chown -R b3chain:b3chain "$DATADIR/conf.d"
chmod 0640 "$DATADIR/conf.d/zmq.conf"

# Drop the includeconf line we added at top level; readd into [test] section instead.
sed -i '/^includeconf=conf\.d\/zmq\.conf$/d' /etc/b3chain/b3chain.conf

# Append includeconf inside [test] section. b3chain.conf already has [test]
# section at the bottom, so appending after the section header (or at EOF)
# is fine: bitcoin-core treats remaining lines as part of the last section.
if ! grep -q '^includeconf=conf\.d/zmq\.conf$' /etc/b3chain/b3chain.conf; then
    echo "includeconf=conf.d/zmq.conf" >> /etc/b3chain/b3chain.conf
fi

echo "==> b3chain.conf now:"
sed 's/rpcpassword=.*/rpcpassword=<HIDDEN>/' /etc/b3chain/b3chain.conf

echo
echo "==> reset failed unit and restart"
systemctl reset-failed b3chaind-testnet.service || true
systemctl restart b3chaind-testnet.service
sleep 5

echo
echo "==> status after restart"
systemctl is-active b3chaind-testnet.service && echo "active OK" || systemctl status b3chaind-testnet.service --no-pager -l | head -20

echo
echo "==> getzmqnotifications"
b3chain-cli -chain=test \
    -conf=/etc/b3chain/b3chain.conf \
    -datadir=/var/lib/b3chain/.b3chain getzmqnotifications 2>&1 | head -20

echo
echo "==> getblockcount"
b3chain-cli -chain=test \
    -conf=/etc/b3chain/b3chain.conf \
    -datadir=/var/lib/b3chain/.b3chain getblockcount
REMOTE
