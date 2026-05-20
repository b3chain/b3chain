#!/usr/bin/env bash
#
# Install b3chain's patched electrs (Electrum Rust Server) and stage it
# under systemd, pointed at the local b3chaind-testnet RPC + block files.
# The explorer uses this for /address/<addr> per-address balance and tx
# history.
#
# Why a fork?
# -----------
# Upstream romanz/electrs v0.10.6 has THREE hardcoded assumptions that
# break on a Bitcoin-Core fork that changes any of them:
#   1. Network magic bytes  -> solved here via `network=signet` + `signet_magic`
#   2. Daemon P2P port      -> solved here via `daemon_p2p_addr`
#   3. Genesis block hash   -> solved by b3chain/electrs@v0.10.6-b3chain-1:
#      Chain::new now accepts an Option<BlockHeader> override, and
#      Tracker::new feeds it the daemon's actual genesis (via
#      `getblockhash 0` + `getblockheader`) instead of the bitcoin-rs
#      crate's network-ident-keyed hardcoded one.
#
# Run as root on seed1 AFTER b3chaind-testnet is bootstrapped and
# answering RPC at 127.0.0.1:18534. Idempotent (safe to re-run).
export LC_ALL=C
set -euo pipefail

# Opt-in: pass --enable to actually `systemctl enable --now` the service.
# Without it we stop+disable so a broken indexer can't keep flapping.
# Kept as a flag (not unconditional) so we can bisect / hold back without
# editing the installer.
ENABLE_SERVICE=0
for arg in "$@"; do
    case "$arg" in
        --enable) ENABLE_SERVICE=1 ;;
    esac
done

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

if ! systemctl is-active b3chaind-testnet >/dev/null; then
    echo "b3chaind-testnet is not active; bootstrap the node first" >&2
    exit 1
fi

ELECTRS_USER=electrs
ELECTRS_DIR=/var/lib/electrs
ELECTRS_REPO=https://github.com/b3chain/electrs.git
ELECTRS_TAG=v0.10.6-b3chain-1             # bump deliberately; triggers DB wipe
ELECTRS_PORT=50001                        # Electrum RPC (loopback only)
ELECTRS_MONITORING_PORT=4224              # Prometheus (loopback only)
B3CHAIN_USER=b3chain
B3CHAIN_DATADIR=/var/lib/b3chain/.b3chain # parent of testnet3/
B3CHAIN_RPC_HOST=127.0.0.1
B3CHAIN_RPC_PORT=18534
B3CHAIN_P2P_PORT=18533
B3CHAIN_RPC_USER=b3chain

# B3Chain testnet uses custom P2P network magic bytes (`0xb3 0xc1 0x02 0x0e`)
# to isolate from Bitcoin's testnet. electrs's "testnet" mode hardcodes
# Bitcoin's magic, so we run it in "signet" mode and override the magic
# bytes via `signet_magic` -- the canonical electrs escape hatch for
# custom networks. See src/kernel/chainparams.cpp:212.
B3CHAIN_TESTNET_MAGIC=b3c1020e

if [ ! -f /etc/b3chain/rpcpassword ]; then
    echo "/etc/b3chain/rpcpassword missing; cannot configure electrs auth" >&2
    exit 1
fi
B3CHAIN_RPC_PASS="$(cat /etc/b3chain/rpcpassword)"

# 1. apt deps: rustc/cargo for building, clang+cmake for librocksdb-sys.
#    Ubuntu 24.04 (noble) ships rustc 1.75+ which is sufficient for
#    electrs v0.10.x (MSRV is 1.63 as of 0.10.6).
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl git \
    rustc cargo \
    build-essential clang cmake pkg-config \
    libsnappy-dev liblz4-dev libzstd-dev

# 2. system user + home + data dir
if ! id -u "$ELECTRS_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home "$ELECTRS_DIR" \
            --shell /usr/sbin/nologin "$ELECTRS_USER"
fi
install -d -o "$ELECTRS_USER" -g "$ELECTRS_USER" -m 750 \
    "$ELECTRS_DIR" "$ELECTRS_DIR/db"

# 2b. Grant electrs read-only access to b3chaind's data directory.
#     The dir tree is mode 700 by default (drwx------). We add the
#     electrs user to the b3chain group and open the dirs (NOT the
#     files inside chainstate/ which are still RW for b3chaind) for
#     group read+execute.
usermod -aG "$B3CHAIN_USER" "$ELECTRS_USER"
chmod g+rx /var/lib/b3chain                       || true
chmod g+rx "$B3CHAIN_DATADIR"                     || true
chmod g+rx "$B3CHAIN_DATADIR/testnet3"            || true
chmod g+rx "$B3CHAIN_DATADIR/testnet3/blocks"     || true

# 2c. electrs in "signet" mode looks for blocks under `daemon_dir/signet/`
#     but b3chaind writes them to `daemon_dir/testnet3/`. Bridge with a
#     relative symlink so the index points at the real block files.
if [ ! -e "$B3CHAIN_DATADIR/signet" ]; then
    sudo -u "$B3CHAIN_USER" ln -sfn testnet3 "$B3CHAIN_DATADIR/signet"
fi
# Make existing blk*.dat / rev*.dat files group-readable. New files
# created by b3chaind will inherit umask 0077 (i.e. owner-only) so we
# also drop a tmpfiles.d rule that re-applies the read bit nightly.
find "$B3CHAIN_DATADIR/testnet3/blocks" -maxdepth 1 -type f \
    \( -name 'blk*.dat' -o -name 'rev*.dat' -o -name 'blocks/index' \) \
    -exec chmod g+r {} + 2>/dev/null || true

cat > /etc/tmpfiles.d/b3chain-blocks-groupread.conf <<EOF
# Keep b3chaind testnet block files group-readable so electrs can index them.
# Re-applied by systemd-tmpfiles on every boot and via timer; b3chaind's
# umask (0077) would otherwise drop the group-read bit on new blk*.dat.
z $B3CHAIN_DATADIR/testnet3/blocks/blk*.dat 0640 - - -
z $B3CHAIN_DATADIR/testnet3/blocks/rev*.dat 0640 - - -
EOF

# 3. Build electrs from the b3chain fork if not already at the pinned tag.
#
# We can't trust `electrs --version` to identify the fork (it prints the
# upstream Cargo.toml version "0.10.6"). Instead stash the installed git
# tag in $ELECTRS_DIR/.installed-tag and compare against $ELECTRS_TAG.
TAG_STAMP="$ELECTRS_DIR/.installed-tag"
INSTALLED_TAG="$(cat "$TAG_STAMP" 2>/dev/null || true)"
if [ "$INSTALLED_TAG" != "$ELECTRS_TAG" ]; then
    echo "==> building electrs $ELECTRS_TAG (installed: ${INSTALLED_TAG:-none})"
    SRC=/tmp/electrs-src
    rm -rf "$SRC"
    git clone --depth=1 --branch "$ELECTRS_TAG" \
        "$ELECTRS_REPO" "$SRC"
    # Build as the electrs user so cargo's target/ is in its home and
    # doesn't pollute /root. The cargo registry cache is also kept there.
    chown -R "$ELECTRS_USER:$ELECTRS_USER" "$SRC"
    sudo -u "$ELECTRS_USER" -H bash -c "
        set -e
        cd '$SRC'
        cargo build --locked --release --bin electrs
    "
    install -m 0755 "$SRC/target/release/electrs" /usr/local/bin/electrs
    rm -rf "$SRC"

    # The on-disk RocksDB was indexed with the previous binary's view of
    # the chain (potentially with the wrong genesis hash on first install
    # under the unpatched upstream). Force a re-index when the tag
    # changes so the new genesis takes effect.
    if [ -d "$ELECTRS_DIR/db" ]; then
        echo "==> wiping electrs DB (tag changed: ${INSTALLED_TAG:-none} -> $ELECTRS_TAG)"
        systemctl stop electrs-testnet.service 2>/dev/null || true
        rm -rf "$ELECTRS_DIR/db"
        install -d -o "$ELECTRS_USER" -g "$ELECTRS_USER" -m 750 "$ELECTRS_DIR/db"
    fi

    echo "$ELECTRS_TAG" > "$TAG_STAMP"
    chown "$ELECTRS_USER:$ELECTRS_USER" "$TAG_STAMP"
fi
/usr/local/bin/electrs --version

# 4. Config (toml). 0640 root:electrs so the password isn't world-readable.
install -d -o root -g "$ELECTRS_USER" -m 750 /etc/electrs
cat > /etc/electrs/config.toml <<EOF
# electrs config for b3chain testnet (managed by contrib/testnet/electrs/install.sh)
#
# We run in "signet" mode (rather than "testnet") purely to take advantage of
# the signet_magic escape hatch -- b3chaind speaks Bitcoin-Core wire protocol
# but with custom 4-byte network magic. Block headers, txids, and merkle math
# are all stock Bitcoin Core, so electrs indexes the chain correctly.
# The b3chain/electrs fork additionally fetches the genesis header from the
# daemon at startup so the chain walk uses b3chain's real genesis hash
# instead of bitcoin-rs's hardcoded signet one.
network         = "signet"
signet_magic    = "$B3CHAIN_TESTNET_MAGIC"
daemon_dir      = "$B3CHAIN_DATADIR"
daemon_rpc_addr = "$B3CHAIN_RPC_HOST:$B3CHAIN_RPC_PORT"
daemon_p2p_addr = "$B3CHAIN_RPC_HOST:$B3CHAIN_P2P_PORT"
auth            = "$B3CHAIN_RPC_USER:$B3CHAIN_RPC_PASS"
db_dir          = "$ELECTRS_DIR/db"
electrum_rpc_addr   = "127.0.0.1:$ELECTRS_PORT"
monitoring_addr     = "127.0.0.1:$ELECTRS_MONITORING_PORT"
log_filters     = "INFO"
index_unspendables = false
EOF
chown root:"$ELECTRS_USER" /etc/electrs/config.toml
chmod 0640 /etc/electrs/config.toml

# 5. systemd unit
cat > /etc/systemd/system/electrs-testnet.service <<EOF
[Unit]
Description=electrs (Electrum server) for b3chain testnet
After=network-online.target b3chaind-testnet.service
Wants=network-online.target
Requires=b3chaind-testnet.service

[Service]
Type=simple
User=$ELECTRS_USER
Group=$ELECTRS_USER
SupplementaryGroups=$B3CHAIN_USER
ExecStart=/usr/local/bin/electrs --conf /etc/electrs/config.toml
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=$B3CHAIN_DATADIR
ReadWritePaths=$ELECTRS_DIR
PrivateTmp=true
LimitNOFILE=131072

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

if [ "$ENABLE_SERVICE" -eq 1 ]; then
    systemctl enable electrs-testnet.service
    systemctl restart electrs-testnet.service

    # Sanity check: wait for the Electrum RPC port to bind. Initial index
    # build happens AFTER the bind on a small testnet (sub-minute), so we
    # only wait for the TCP listener here; the explorer falls back to
    # "Tx history unavailable" gracefully while the index catches up.
    echo "==> waiting for electrs to bind 127.0.0.1:$ELECTRS_PORT"
    for i in $(seq 1 60); do
        if (echo > /dev/tcp/127.0.0.1/$ELECTRS_PORT) 2>/dev/null; then
            echo "    electrs accepting connections on tcp/$ELECTRS_PORT"
            echo "    tail logs with: journalctl -u electrs-testnet -f"
            exit 0
        fi
        sleep 2
    done

    echo "electrs did not bind tcp/$ELECTRS_PORT within 120s; last logs:" >&2
    journalctl -u electrs-testnet --no-pager -n 50 >&2
    exit 1
else
    systemctl stop electrs-testnet.service 2>/dev/null || true
    systemctl disable electrs-testnet.service 2>/dev/null || true
    cat <<EOF
==> electrs binary, user, config, and systemd unit are in place but the
    service is left STOPPED + DISABLED.

    The genesis-hash incompatibility that previously forced this default
    is fixed by b3chain/electrs@$ELECTRS_TAG. The --enable gate is kept
    so an operator can install the binary without committing to running
    it (useful for bisecting / staged rollouts).

    To turn it on, re-run with:

        sudo $0 --enable

EOF
fi
