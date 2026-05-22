#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
set -e
cd /opt/b3chain/b3chain
git fetch b3chain
git reset --hard b3chain/b3chain-main
echo "==> running install.sh --enable-stats --enable-audit"
bash contrib/testnet/explorer-ng/install.sh --enable-stats --enable-audit 2>&1 \
    | tee /tmp/install-stats-audit.log | tail -20
RC=${PIPESTATUS[0]}
echo "==> exit: $RC"
sleep 8
echo
echo "==> service status"
systemctl is-active b3chain-explorer-ng.service
echo "==> recent backend logs"
journalctl -u b3chain-explorer-ng.service --no-pager -n 12 | tail -12
echo
echo "==> verify"
bash contrib/testnet/explorer-ng/verify.sh
REMOTE
