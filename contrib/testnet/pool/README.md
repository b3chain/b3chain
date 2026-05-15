# B3Chain Stratum Mining Pool

A Stratum V1 mining pool for [B3Chain](https://github.com/b3chain/b3chain) with a
web UI for verified user accounts and live per-user hashrate dashboards.

- Pool URL (testnet): `stratum+tcp://pool.b3chain.org:3333`
- Web UI: `https://pool.b3chain.org`
- Reward scheme: PPLNS over the last 4032 weighted shares
- Pool fee: 1%
- Default minimum payout: 1.0 B3C

This lives at `contrib/testnet/pool/`, mirroring the
[`contrib/testnet/faucet/`](../faucet/) layout.

## Architecture

Three Node.js services:

| Service | Process | Talks to |
|---|---|---|
| `b3chain-pool-stratum` | Stratum V1 TCP listener on `:3333` | miners (TCP), pool daemon (UNIX sock) |
| `b3chain-pool-daemon` | Block-template poller, share writer, PPLNS, payouts, block confirmer | b3chaind (RPC), Postgres |
| `b3chain-pool-web` | Express + Socket.IO on `127.0.0.1:5100` | Postgres, b3chaind (validateaddress), browsers |

Both stratum and daemon import the same `src/lib/{blake3,header,...}.ts`
helpers. Web is read-only against the database (writes happen from daemon).

## Running locally (dev)

```bash
# 1. Postgres
docker compose -f docker-compose.dev.yml up -d
# 2. Install deps
npm install
# 3. Apply migrations
B3POOL_DB_URL=postgres://b3chain_pool:dev@127.0.0.1:5432/b3chain_pool \
  npm run migrate
# 4. Start b3chaind in regtest mode (separate terminal)
b3chaind -regtest -daemon -rpcuser=dev -rpcpassword=dev -wallet=pool-payouts
# 5. Start the three pool services
cp .env.example .env && $EDITOR .env
npm run dev:daemon  # one terminal
npm run dev:stratum # another
npm run dev:web     # another
# 6. Point the reference miner at the pool. Every share submitted is
#    printed with full byte-level detail (job/extranonces/header/PoW
#    hash/targets/server response/RTT) so the pool's share-validation
#    pipeline can be cross-checked. --json-log captures the same
#    information as JSONL for replay.
pip3 install blake3
python3 ../../../contrib/miner/b3chain-cpuminer.py \
    --stratum stratum+tcp://127.0.0.1:3333 \
    --user dev@example.com.worker1 --pass x \
    --threads 2 --json-log /tmp/shares.jsonl \
    --progress-interval 500000
```

Open `http://127.0.0.1:5100` to see the public landing page.

## Production deployment (seed1)

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — narrative architecture
- [docs/STRATUM-PROTOCOL.md](docs/STRATUM-PROTOCOL.md) — share validation, BLAKE3 specifics
- [docs/PPLNS.md](docs/PPLNS.md) — payout math with worked example
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — seed1 install runbook
- [docs/OPERATOR-RUNBOOK.md](docs/OPERATOR-RUNBOOK.md) — daily ops, failure modes

## Phased rollout

| Phase | Status | Description |
|---|---|---|
| A. Mineable MVP | done | Stratum + getblocktemplate/submitblock + public landing |
| B. Verified accounts | done | Signup, email verify, 2FA, per-user dashboard |
| C. PPLNS payouts | done | Block confirmer, PPLNS credit, hourly auto-payout |
| D. Production polish | done | Vardiff, rate limit, /metrics, runbook |
