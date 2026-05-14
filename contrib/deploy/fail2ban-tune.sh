#!/usr/bin/env bash
#
# fail2ban-tune.sh
#
# Idempotent: install + tune fail2ban's sshd jail so legit operator
# typos (e.g. wrong username) don't cause a 10-minute lockout. Same
# config block that contrib/deploy/bootstrap-testnet-node.sh now
# applies on a fresh install; this script is for retrofitting an
# already-bootstrapped host.
#
# Usage (as root):
#   ./fail2ban-tune.sh [--ignore-ip=A.B.C.D] [--ignore-ip=E.F.G.H/24]
#
# Run without --ignore-ip to just adopt the new threshold (10 retries,
# 5-minute ban) without whitelisting any extra IPs.

set -euo pipefail
if [ "$EUID" -ne 0 ]; then echo "must run as root" >&2; exit 2; fi

IGNORE_IPS=()
for arg in "$@"; do
    case "$arg" in
        --ignore-ip=*) IGNORE_IPS+=("${arg#--ignore-ip=}") ;;
        -h|--help) sed -n '/^# /,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown arg: $arg" >&2; exit 1 ;;
    esac
done

if ! command -v fail2ban-client >/dev/null; then
    apt-get update -y
    apt-get install -y --no-install-recommends fail2ban
fi

HOST_IPS="$(hostname -I 2>/dev/null | tr -d '\n' | xargs -n1 2>/dev/null \
            | grep -E '^(10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|192\.168\.|127\.)' \
            | tr '\n' ' ')"
IGNORE_LIST="127.0.0.1/8 ::1 ${HOST_IPS}"
for ip in "${IGNORE_IPS[@]:-}"; do
    [ -n "$ip" ] && IGNORE_LIST+=" $ip"
done

install -d -m 755 /etc/fail2ban/jail.d
cat > /etc/fail2ban/jail.d/00-b3chain-sshd.conf <<EOF
# Managed by contrib/deploy/fail2ban-tune.sh / bootstrap-testnet-node.sh.
[DEFAULT]
ignoreip = ${IGNORE_LIST}
bantime  = 5m
findtime = 10m
maxretry = 10

[sshd]
enabled = true
mode    = normal
backend = systemd
EOF
chmod 644 /etc/fail2ban/jail.d/00-b3chain-sshd.conf

systemctl enable fail2ban >/dev/null 2>&1 || true
systemctl restart fail2ban
sleep 1
fail2ban-client unban --all 2>/dev/null || true
fail2ban-client status sshd | sed 's/^/    /'
echo "==> fail2ban tuned: ignoreip=\"$IGNORE_LIST\" bantime=5m maxretry=10"
