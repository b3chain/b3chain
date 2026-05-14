#!/usr/bin/env bash
#
# Install the seed-status monitor cron job on the seed-1 host.
# Run as root.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
install -m 755 "$SCRIPT_DIR/seed-status.sh" /usr/local/bin/b3chain-seed-status.sh

# Default config if none exists yet
if [ ! -f /etc/b3chain/seed-status.env ]; then
    cat > /etc/b3chain/seed-status.env <<EOF
# Space-separated list of seeds to poll. Add seed2/seed3 once
# provisioned; for now we poll just the local seed.
SEEDS="localhost"
STATUS_TXT=/var/www/b3chain/testnet-status.txt
LOG=/var/log/b3chain/seed-status.log
LOCAL_RPC_USER=b3chain
LOCAL_RPC_PORT=18534
LOCAL_RPC_PASSWORD_FILE=/etc/b3chain/rpcpassword
EOF
    chmod 644 /etc/b3chain/seed-status.env
fi

mkdir -p /var/log/b3chain /var/www/b3chain
chmod 755 /var/log/b3chain /var/www/b3chain

# Cron entry: every 5 minutes
cat > /etc/cron.d/b3chain-seed-status <<'EOF'
# B3Chain testnet seed status monitor
*/5 * * * * root /usr/local/bin/b3chain-seed-status.sh
EOF
chmod 644 /etc/cron.d/b3chain-seed-status

# Run once now to seed the status file
/usr/local/bin/b3chain-seed-status.sh || true
echo "==> seed status monitor installed; next run within 5 min"
echo "    snapshot: /var/www/b3chain/testnet-status.txt"
echo "    log     : /var/log/b3chain/seed-status.log"
