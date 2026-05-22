#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
set -e
cd /opt/b3chain/b3chain
git fetch b3chain
git reset --hard b3chain/b3chain-main
echo "==> running install.sh --enable-stats --enable-audit"
bash contrib/testnet/explorer-ng/install.sh --enable-stats --enable-audit 2>&1 \
    | tee /tmp/install-features.log | tail -30
RC=${PIPESTATUS[0]}
echo "==> exit: $RC"
echo
echo "==> diff between configs"
sudo diff -q /etc/b3chain/explorer-ng/explorer-ng-config.json* 2>/dev/null || true
echo "==> active config head"
sudo head -55 /etc/b3chain/explorer-ng/explorer-ng-config.json
echo
echo "==> service status"
systemctl is-active b3chain-explorer-ng.service
sleep 5
journalctl -u b3chain-explorer-ng.service --no-pager -n 8 | tail -8
echo
echo "==> verify"
bash contrib/testnet/explorer-ng/verify.sh
REMOTE
