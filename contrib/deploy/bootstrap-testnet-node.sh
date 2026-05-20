#!/usr/bin/env bash
#
# bootstrap-testnet-node.sh
#
# Take a fresh Ubuntu 22.04 (or 24.04) host from "blank" to "running
# b3chaind -chain=test under systemd". Idempotent: safe to re-run.
#
# Usage (as root, on the target box):
#
#   wget https://raw.githubusercontent.com/b3chain/b3chain/b3chain-main/contrib/deploy/bootstrap-testnet-node.sh
#   chmod +x bootstrap-testnet-node.sh
#   ./bootstrap-testnet-node.sh [--ref=v0.1.0-testnet] \
#       [--addnode=IP1] [--addnode=IP2] \
#       [--ignore-ip=A.B.C.D] [--ignore-ip=E.F.G.H/24]
#
# The --addnode flag may be repeated. Each IP is added to the b3chain.conf
# `addnode=` list so the node makes a direct outbound connection to its
# peer seed at startup (in addition to DNS-seed discovery).
#
# The --ignore-ip flag may also be repeated. Each value is added to
# fail2ban's sshd jail `ignoreip` list so legit operator IPs are never
# banned, no matter how many bad-username attempts come from them.
#
# Exit codes:
#   0  success, b3chaind is running and answering RPC
#   1  generic failure
#   2  prerequisite missing (run as root, etc.)

export LC_ALL=C
set -euo pipefail

REF="b3chain-main"
ADDNODES=()
IGNORE_IPS=()
RPC_PORT=18534    # localhost-only
P2P_PORT=18533    # public

for arg in "$@"; do
    case "$arg" in
        --ref=*)        REF="${arg#--ref=}" ;;
        --addnode=*)    ADDNODES+=("${arg#--addnode=}") ;;
        --ignore-ip=*)  IGNORE_IPS+=("${arg#--ignore-ip=}") ;;
        -h|--help)
            sed -n '/^# /,/^$/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 1
            ;;
    esac
done

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

# -----------------------------------------------------------------------
log "1. Install build dependencies (apt)"
# -----------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config python3 python3-pip git curl \
    libboost-all-dev libssl-dev libsqlite3-dev libevent-dev \
    libminiupnpc-dev libnatpmp-dev libzmq3-dev systemd ufw fail2ban

# -----------------------------------------------------------------------
log "2. Create unprivileged user and data directory"
# -----------------------------------------------------------------------
if ! id -u b3chain >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin b3chain
fi
install -d -o b3chain -g b3chain -m 750 /var/lib/b3chain
install -d -o b3chain -g b3chain -m 750 /var/lib/b3chain/.b3chain
install -d -m 755 /etc/b3chain
install -d -m 755 /var/log/b3chain

# -----------------------------------------------------------------------
log "3. Clone and build b3chain ($REF)"
# -----------------------------------------------------------------------
SRC=/usr/local/src/b3chain
if [ ! -d "$SRC/.git" ]; then
    git clone https://github.com/b3chain/b3chain.git "$SRC"
fi
cd "$SRC"
git fetch --tags --prune origin
git checkout "$REF"
git reset --hard "$REF" || true   # for branches we want HEAD; tags are detached and reset is a no-op

CURRENT_REV="$(git rev-parse HEAD)"
BUILD_REV_FILE="$SRC/build/.built-rev"
NEEDS_BUILD=1
if [ -x "$SRC/build/bin/b3chaind" ] \
   && [ -f "$BUILD_REV_FILE" ] \
   && [ "$(cat "$BUILD_REV_FILE")" = "$CURRENT_REV" ]; then
    NEEDS_BUILD=0
fi
if [ "$NEEDS_BUILD" = "1" ]; then
    if [ ! -d build ]; then
        # ENABLE_IPC=OFF avoids the libcapnp dependency, which is
        # only needed for upstream's multiprocess work and not for
        # a plain testnet seed.
        cmake -B build \
            -DCMAKE_BUILD_TYPE=Release \
            -DBUILD_GUI=OFF \
            -DENABLE_IPC=OFF
    fi
    # CMake target names are inherited from upstream Bitcoin Core
    # (bitcoind, bitcoin-cli). The OUTPUT_NAME property renames the
    # produced binaries to b3chaind / b3chain-cli at link time.
    #
    # Pick a -j level that won't OOM on small VPS. Each cc1plus while
    # compiling the big files (chainparams.cpp etc.) wants 800 MiB-1
    # GiB of RAM. Use -j1 when there's less than ~2.5 GiB of RAM.
    MEM_KB="$(awk '/^MemTotal:/{print $2}' /proc/meminfo)"
    if [ "${MEM_KB:-0}" -lt 2621440 ]; then  # < 2.5 GiB
        JOBS=1
    else
        JOBS="$(nproc)"
    fi
    echo "    building with -j$JOBS (RAM ${MEM_KB} kB)"
    cmake --build build -j"$JOBS" --target bitcoind bitcoin-cli
    echo "$CURRENT_REV" > "$BUILD_REV_FILE"
fi

install -m 755 "$SRC/build/bin/b3chaind"   /usr/local/bin/b3chaind
install -m 755 "$SRC/build/bin/b3chain-cli" /usr/local/bin/b3chain-cli

# -----------------------------------------------------------------------
log "4. Drop /etc/b3chain/b3chain.conf"
# -----------------------------------------------------------------------
RPC_USER="b3chain"
RPC_PASSWORD_FILE=/etc/b3chain/rpcpassword
if [ ! -s "$RPC_PASSWORD_FILE" ]; then
    head -c 32 /dev/urandom | base64 | tr -d '/+=' > "$RPC_PASSWORD_FILE"
    chmod 600 "$RPC_PASSWORD_FILE"
    chown root:b3chain "$RPC_PASSWORD_FILE"
    chmod 640 "$RPC_PASSWORD_FILE"
fi
RPC_PASS="$(cat "$RPC_PASSWORD_FILE")"

# Render addnode lines (only if any non-empty entries exist).
# Listen options live inside the [test] section so b3chaind binds the
# right P2P port for the test chain. Putting `listen=1` in the global
# section caused upstream's chain-sectionised parser to bind P2P on
# the rpcbind address, conflicting with RPC.
ADDNODE_BLOCK=""
if [ "${#ADDNODES[@]}" -gt 0 ]; then
    for ip in "${ADDNODES[@]}"; do
        if [ -n "$ip" ]; then
            ADDNODE_BLOCK+="addnode=$ip"$'\n'
        fi
    done
fi

# Detect public IPv4 so we can advertise it as `externalip` and stop the
# daemon dialling the compiled-in fixed seed entry that points at this
# very host (which produces a stream of "connected to self" log lines).
# Falls back silently if no public IPv4 is detectable.
EXTERNAL_IP=""
for url in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
    EXTERNAL_IP="$(curl -fsSL --max-time 5 "$url" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$EXTERNAL_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        break
    fi
    EXTERNAL_IP=""
done
EXTERNAL_IP_LINE=""
if [ -n "$EXTERNAL_IP" ]; then
    EXTERNAL_IP_LINE="externalip=$EXTERNAL_IP"$'\n'
fi

cat > /etc/b3chain/b3chain.conf <<EOF
# Auto-generated by bootstrap-testnet-node.sh.
# Hand-edit at your own risk; rerunning the bootstrap will overwrite.

chain=test
server=1
txindex=0
prune=0

[test]
listen=1
bind=0.0.0.0:$P2P_PORT
${EXTERNAL_IP_LINE}port=$P2P_PORT
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcport=$RPC_PORT
rpcuser=$RPC_USER
rpcpassword=$RPC_PASS
# Without fallbackfee, sendtoaddress fails on a young chain whose
# mempool history is too short for estimatesmartfee to produce a
# rate. 0.00001 B3C/kB is plenty for testnet and matches the
# upstream Bitcoin Core testnet default.
fallbackfee=0.00001
${ADDNODE_BLOCK}
EOF
chmod 640 /etc/b3chain/b3chain.conf
chown root:b3chain /etc/b3chain/b3chain.conf

# -----------------------------------------------------------------------
log "5. Install systemd unit"
# -----------------------------------------------------------------------
cat > /etc/systemd/system/b3chaind-testnet.service <<'EOF'
[Unit]
Description=B3Chain testnet daemon
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/b3chaind -chain=test \
          -conf=/etc/b3chain/b3chain.conf \
          -datadir=/var/lib/b3chain/.b3chain

User=b3chain
Group=b3chain
Type=simple
Restart=on-failure
RestartSec=10
TimeoutStopSec=600

# Hardening
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/b3chain /var/log/b3chain
PrivateTmp=true
PrivateDevices=true
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable b3chaind-testnet.service
systemctl restart b3chaind-testnet.service

# -----------------------------------------------------------------------
log "6. Open firewall ports (ssh + b3chain p2p)"
# -----------------------------------------------------------------------
# CRITICAL: open SSH (22/tcp) BEFORE enabling ufw, otherwise enabling
# the default-deny firewall locks the operator out of the box. Then
# open the b3chain p2p port. RPC stays bound to 127.0.0.1 so we do not
# expose it.
if command -v ufw >/dev/null; then
    ufw allow OpenSSH || ufw allow 22/tcp || true
    ufw allow "$P2P_PORT/tcp" || true
    ufw --force enable >/dev/null 2>&1 || true
    ufw status verbose | head -20 || true
fi

# -----------------------------------------------------------------------
log "7. Configure fail2ban (sshd jail)"
# -----------------------------------------------------------------------
# We have to be careful here: fail2ban's default sshd jail will ban a
# source IP after just 5 failed attempts within 10 minutes (which
# includes "Invalid user" failures from a typoed username). The agent
# that bootstrapped this box previously locked itself out by trying
# `lobby@` instead of `deploy@` 5+ times in a row. Tune the jail so:
#   * legitimate operator typos cost a short ban (5 min, not 10)
#   * known operator IPs are NEVER banned (--ignore-ip flag, repeatable)
#   * the loopback and the host's own private IPs are always whitelisted
#   * threshold is 10 attempts (not 5) - real attackers hit it instantly,
#     legitimate ops with a fat finger don't.
if command -v fail2ban-client >/dev/null; then
    # Build the ignoreip list. Always include loopback + this host's
    # own RFC1918 IPs so on-host scripts can never trip the jail.
    HOST_IPS="$(hostname -I 2>/dev/null | tr -d '\n' | xargs -n1 2>/dev/null \
                | grep -E '^(10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|192\.168\.|127\.)' \
                | tr '\n' ' ')"
    IGNORE_LIST="127.0.0.1/8 ::1 ${HOST_IPS}"
    if [ "${#IGNORE_IPS[@]}" -gt 0 ]; then
        for ip in "${IGNORE_IPS[@]}"; do
            [ -n "$ip" ] && IGNORE_LIST+=" $ip"
        done
    fi

    install -d -m 755 /etc/fail2ban/jail.d
    cat > /etc/fail2ban/jail.d/00-b3chain-sshd.conf <<EOF
# Managed by contrib/deploy/bootstrap-testnet-node.sh.
# Hand edits will be overwritten on next bootstrap run.
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
    systemctl restart fail2ban >/dev/null 2>&1 || true
    # Best-effort sanity check; non-fatal if fail2ban-client isn't ready
    fail2ban-client status sshd 2>/dev/null | sed 's/^/    /' || true
fi

# -----------------------------------------------------------------------
log "8. Wait for RPC and report status"
# -----------------------------------------------------------------------
for _ in $(seq 1 30); do
    if /usr/local/bin/b3chain-cli -chain=test \
           -conf=/etc/b3chain/b3chain.conf \
           -datadir=/var/lib/b3chain/.b3chain \
           getblockchaininfo >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

/usr/local/bin/b3chain-cli -chain=test \
    -conf=/etc/b3chain/b3chain.conf \
    -datadir=/var/lib/b3chain/.b3chain \
    getblockchaininfo

log "DONE. Logs: journalctl -u b3chaind-testnet -f"
log "P2P listening on :$P2P_PORT  (RPC bound to 127.0.0.1:$RPC_PORT)"
