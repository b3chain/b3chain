#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=15 deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
echo "=== systemctl status b3chaind-testnet ==="
systemctl status b3chaind-testnet.service --no-pager -l | head -30 || true
echo
echo "=== journal last 30 lines ==="
journalctl -u b3chaind-testnet.service --no-pager -l -n 30
echo
echo "=== current b3chain.conf (ignoring secrets) ==="
sed 's/rpcpassword=.*/rpcpassword=<HIDDEN>/' /etc/b3chain/b3chain.conf
echo
echo "=== conf.d/zmq.conf ==="
cat /etc/b3chain/conf.d/zmq.conf
REMOTE
