# contrib/deploy/

Operator-side deployment helpers for B3Chain seed nodes.

## bootstrap-testnet-node.sh

Idempotent bash script that takes a fresh Ubuntu 22.04 (or 24.04) host
to a running `b3chaind -chain=test` under systemd. Usage:

```
sudo ./bootstrap-testnet-node.sh \
    --ref=v0.1.0-testnet \
    --addnode=<peer1-ip> \
    --addnode=<peer2-ip>
```

The `--addnode` flag may be repeated. Each IP becomes an `addnode=`
line in `/etc/b3chain/b3chain.conf` so the new seed makes direct
outbound connections to its sibling seeds at startup.

What it does:

1. `apt install` build dependencies.
2. Create `b3chain` system user, `/var/lib/b3chain` data dir,
   `/etc/b3chain` config dir, `/var/log/b3chain` log dir.
3. Clone https://github.com/b3chain/b3chain.git, checkout the
   requested ref (`b3chain-main` by default), build with cmake.
4. Install `/usr/local/bin/b3chaind` and `/usr/local/bin/b3chain-cli`.
5. Generate `/etc/b3chain/rpcpassword` (32 random bytes) and write
   `/etc/b3chain/b3chain.conf` binding RPC to localhost only.
6. Install systemd unit `b3chaind-testnet.service` with hardening.
7. Open ufw port 18533/tcp.
8. Wait for RPC to answer and print `getblockchaininfo`.

After bootstrap:

```
journalctl -u b3chaind-testnet -f
b3chain-cli -chain=test -conf=/etc/b3chain/b3chain.conf \
            -datadir=/var/lib/b3chain/.b3chain getpeerinfo
```

To upgrade to a newer release:

```
sudo ./bootstrap-testnet-node.sh --ref=v0.1.1-testnet
```

The script deletes the build directory if HEAD is newer than the
existing binary, then rebuilds and restarts the service.
