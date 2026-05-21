#!/usr/bin/env bash
# One-shot v1.1.5 cold-start on seed1. Run as root on the host.
set -euo pipefail

echo "=== STOP services seed1 ==="
systemctl stop b3chain-51watch.service || true
systemctl stop b3chain-testnet-miner.service || true
systemctl stop b3chain-pool.target || true
for u in b3chain-explorer b3chain-faucet electrs-testnet; do
    systemctl stop "${u}.service" 2>/dev/null || true
done
systemctl stop b3chaind-testnet.service
sleep 2
pgrep -x b3chaind && echo "WARN b3chaind still running" || echo "b3chaind stopped"

echo "=== BACKUP + INSTALL binaries ==="
cp -a /usr/local/bin/b3chaind /usr/local/bin/b3chaind.bak-v114-prev115
cp -a /usr/local/bin/b3chain-cli /usr/local/bin/b3chain-cli.bak-v114-prev115
install -m 755 /opt/b3chain/b3chain/build/bin/b3chaind /usr/local/bin/b3chaind
install -m 755 /opt/b3chain/b3chain/build/bin/b3chain-cli /usr/local/bin/b3chain-cli
md5sum /usr/local/bin/b3chaind /usr/local/bin/b3chain-cli

echo "=== UPDATE miner script ==="
cp -a /usr/local/bin/b3chain-testnet-miner.sh /usr/local/bin/b3chain-testnet-miner.sh.bak-prev115-timeout
install -m 755 /opt/b3chain/b3chain/contrib/testnet/miner/b3chain-testnet-miner.sh /usr/local/bin/b3chain-testnet-miner.sh
grep rpcclienttimeout /usr/local/bin/b3chain-testnet-miner.sh

echo "=== WIPE testnet3 ==="
rm -rf /var/lib/b3chain/.b3chain/testnet3

echo "=== START b3chaind ==="
systemctl start b3chaind-testnet.service
for i in $(seq 1 30); do
    if b3chain-cli -chain=test -conf=/etc/b3chain/b3chain.conf -datadir=/var/lib/b3chain/.b3chain getblockcount >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
GEN=$(b3chain-cli -chain=test -conf=/etc/b3chain/b3chain.conf -datadir=/var/lib/b3chain/.b3chain getblockhash 0)
echo "genesis=$GEN"
b3chain-cli -chain=test -conf=/etc/b3chain/b3chain.conf -datadir=/var/lib/b3chain/.b3chain getblockchaininfo | grep -E '"bits"|"difficulty"|"blocks"'

echo "=== ACL for watcher ==="
apt-get install -y acl >/dev/null 2>&1 || true
usermod -aG b3chain deploy || true
setfacl -m g:b3chain:rX /var/lib/b3chain /var/lib/b3chain/.b3chain /var/lib/b3chain/.b3chain/testnet3 || true
setfacl -m g:b3chain:r /var/lib/b3chain/.b3chain/testnet3/debug.log 2>/dev/null || true
setfacl -d -m g:b3chain:r /var/lib/b3chain/.b3chain/testnet3 || true

echo "=== START consumers + miner + watcher ==="
systemctl start b3chain-explorer.service b3chain-faucet.service || true
# electrs: wipe stale index after chain wipe, then start
rm -rf /var/lib/electrs/db
systemctl start electrs-testnet.service || true
systemctl start b3chain-pool.target || true
systemctl start b3chain-testnet-miner.service
systemctl start b3chain-51watch.service

echo "=== DONE seed1 ==="
