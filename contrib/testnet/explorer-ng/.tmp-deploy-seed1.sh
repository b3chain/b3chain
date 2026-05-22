#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=15 deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
set -e
cd /opt/b3chain
if [ ! -d b3chain ]; then
    echo "ERROR: /opt/b3chain/b3chain not present" >&2
    exit 2
fi
cd b3chain

# Pull latest scaffolding
echo "==> updating /opt/b3chain/b3chain"
git fetch b3chain 2>&1 | tail -5
git reset --hard b3chain/b3chain-main

ls -la contrib/testnet/explorer-ng/

echo
echo "==> running install.sh"
bash contrib/testnet/explorer-ng/install.sh 2>&1 | tee /tmp/install-explorer-ng.log | tail -100
RC=${PIPESTATUS[0]}
echo "==> install.sh exit: $RC"
exit $RC
REMOTE
