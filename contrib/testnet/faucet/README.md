# B3Chain testnet faucet

Tiny Flask service that hands out testnet B3C to anyone who provides a
valid testnet address. Deployed at `https://faucet.b3chain.org` for
b3chain testnet.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app: `GET /` form, `POST /request`, `GET /status` JSON |
| `faucet.service` | systemd unit, runs gunicorn as `b3chain-faucet` user |
| `install.sh` | one-shot installer (run as root on the seed-1 host) |

## Behaviour

- Accepts B3Chain testnet addresses (`tb3...`, `m...`, `n...`, `2...`).
- Rejects mainnet addresses (no leakage between chains).
- Per-IP and per-destination cooldown: 24 h by default.
- Rate-limit data lives in a sqlite file; deleting it resets all
  cooldowns.
- Hot wallet must be funded; refilling is left to the operator (e.g. a
  daily cron that moves coins from the miner wallet into the faucet
  wallet).

## Operator install (once)

On the seed-1 host (after `b3chaind-testnet` is running):

```
sudo bash contrib/testnet/faucet/install.sh
```

Then add an nginx site for `faucet.b3chain.org` reverse-proxying to
`127.0.0.1:5000`, with TLS via Let's Encrypt.

## Funding the hot wallet

```
b3chain-cli -chain=test -rpcwallet=miner sendtoaddress \
    "$(b3chain-cli -chain=test -rpcwallet=faucet getnewaddress)" 50
```

Cron daily at 04:00 keeps the faucet topped up:

```
0 4 * * * /usr/local/bin/b3chain-faucet-refill.sh
```
