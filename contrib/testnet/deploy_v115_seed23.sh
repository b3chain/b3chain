#!/usr/bin/env bash
# v1.1.5 cold-start on seed2/seed3. Run as root; B3CHAIND=/path/to/b3chaind required.
set -euo pipefail
B3CHAIND=${B3CHAIND:?set B3CHAIND to staged b3chaind path}

echo "=== STOP b3chaind ==="
systemctl stop b3chaind-testnet.service || true
sleep 2

echo "=== INSTALL binary ==="
cp -a /usr/local/bin/b3chaind /usr/local/bin/b3chaind.bak-v114-prev115 2>/dev/null || true
install -m 755 "$B3CHAIND" /usr/local/bin/b3chaind
md5sum /usr/local/bin/b3chaind

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
b3chain-cli -chain=test -conf=/etc/b3chain/b3chain.conf -datadir=/var/lib/b3chain/.b3chain getconnectioncount
