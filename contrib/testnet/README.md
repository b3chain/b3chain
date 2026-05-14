# contrib/testnet/

Operator-side scripts for running B3Chain testnet infrastructure.

| Subdir | Purpose |
|---|---|
| `faucet/` | Flask service handing out test B3C, with rate limits |
| `miner/` | Systemd unit + installer for the always-on CPU miner |
| `monitor/` | Cron-based seed-status snapshot ⇒ b3chain.org/testnet-status.txt |
| `explorer/` | Docker compose for btc-rpc-explorer at explorer.b3chain.org |

## Install order on the seed-1 host

1. `contrib/deploy/bootstrap-testnet-node.sh` — runs b3chaind testnet
2. `contrib/testnet/miner/install.sh` — start producing blocks
3. `contrib/testnet/faucet/install.sh` — turn on the faucet
4. `contrib/testnet/explorer/install.sh` — turn on the explorer
5. `contrib/testnet/monitor/install.sh` — cron-based status page

After 1–5 you still need to:

- Add nginx vhosts for `faucet.b3chain.org` (→ `127.0.0.1:5000`) and
  `explorer.b3chain.org` (→ `127.0.0.1:3002`), each with TLS via
  Let's Encrypt.
- Add DNS A/CNAME records pointing those names at the seed-1 IP.
- Create the `testnet-seed.b3chain.org` round-robin A record once the
  other two seeds are provisioned.

See `b3chain.org/testnet.html` for the user-facing connection guide.
