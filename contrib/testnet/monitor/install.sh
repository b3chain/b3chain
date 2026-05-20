#!/usr/bin/env bash
#
# Install the seed-status monitor cron job on the seed-1 host.
# Run as root.
export LC_ALL=C
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
install -m 755 "$SCRIPT_DIR/seed-status.sh" /usr/local/bin/b3chain-seed-status.sh

# Generate a dedicated ssh key for cross-seed polling. The matching
# pubkey must be added to deploy@seed2 / deploy@seed3 ~/.ssh/authorized_keys
# (this script prints it at the end so the operator can copy-paste).
KEY=/root/.ssh/b3chain_monitor_ed25519
if [ ! -f "$KEY" ]; then
    install -d -m 700 /root/.ssh
    ssh-keygen -t ed25519 -N '' -C "b3chain-monitor@$(hostname -s)" -f "$KEY"
fi

# Default config if none exists yet
if [ ! -f /etc/b3chain/seed-status.env ]; then
    cat > /etc/b3chain/seed-status.env <<'EOF'
# Space-separated list of seeds to poll. Each entry is "label|target"
# where target is what we ssh/curl to and label is what we display.
# seed1 polls itself via loopback RPC; seed2/seed3 over ssh.
SEEDS="seed1.b3chain.org|localhost seed2.b3chain.org|151.158.1.22 seed3.b3chain.org|151.158.1.60"
STATUS_TXT=/var/www/b3chain/testnet-status.txt
LOG=/var/log/b3chain/seed-status.log
LOCAL_RPC_USER=b3chain
LOCAL_RPC_PORT=18534
LOCAL_RPC_PASSWORD_FILE=/etc/b3chain/rpcpassword
REMOTE_SSH_KEY=/root/.ssh/b3chain_monitor_ed25519
REMOTE_SSH_USER=deploy
REMOTE_SSH_PORT=2222
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
echo
echo "==> public key for remote-seed polling (add to deploy@seed2 and"
echo "    deploy@seed3 ~/.ssh/authorized_keys):"
echo "----8<----"
cat "$KEY.pub"
echo "----8<----"
