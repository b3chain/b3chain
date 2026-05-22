#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=15 deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
echo "=== b3chaind --version ==="
/usr/local/bin/b3chaind --version 2>&1 | head -3

echo "=== help-debug zmq ==="
/usr/local/bin/b3chaind -help-debug 2>&1 | grep -A1 -E '^\s*-zmq' | head -20 || echo "no zmq options listed"

echo "=== ldd vs libzmq ==="
ldd /usr/local/bin/b3chaind 2>&1 | grep -i zmq || echo "no libzmq linked"

echo "=== RPC categories ==="
b3chain-cli -chain=test -conf=/etc/b3chain/b3chain.conf -datadir=/var/lib/b3chain/.b3chain help 2>&1 | grep -iE '^==' | head -20

echo "=== zmq lines in debug.log ==="
tail -200 /var/lib/b3chain/.b3chain/testnet3/debug.log 2>/dev/null | grep -iE 'zmq|invalid|unknown' | head -20 || echo "no zmq mentions"
REMOTE
