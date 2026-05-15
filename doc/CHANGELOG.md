# B3Chain Project History

## Status Summary

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Environment and Build Baseline | **COMPLETE** |
| Phase 1 | Chain Identity (Network Isolation) | **COMPLETE** |
| Phase 2 | PoW Replacement (SHA-256d -> Double BLAKE3-256) | **COMPLETE** |
| Phase 3 | Consensus and Monetary Parameters | **COMPLETE** |
| Phase 4 | Genesis Block | **COMPLETE** |
| Phase 5 | Branding and Binary Renaming | **COMPLETE** |
| Phase 6 | Reference CPU Miner | **COMPLETE** |
| Phase 7 | Testing and QA | **COMPLETE** |
| Phase 8 | Deployment and Launch | 8a (testnet bootstrap) **COMPLETE**; 8b (4-8 week soak) in progress; 8c (mainnet) pending |
| Phase 9 | Wallets, CLI, and API | Inherited from Bitcoin Core |
| Phase 10 | Maintenance and Upgrades | Ongoing |
| Phase 11 | Security | Self-audit pass 1: **COMPLETE**; verification + inheritance + comparison + roadmap (pass 2): **COMPLETE**; external audit pending |

---

## Phase 0: Environment and Build Baseline

- Built vanilla Bitcoin Core 30.2.0 from source with CMake on WSL2
- Verified all binaries compile and pass `--version` check
- Established `b3chain-main` branch from unmodified upstream

## Phase 1: Chain Identity

- **Message start magic**: `0xb3 0xc0 0x01 0x0d` (mainnet)
- **Ports**: Mainnet P2P 8533/RPC 8534, Testnet 18533/18534, Regtest 18544/18545
- **Address prefixes**: P2PKH `0x19` (B...), P2SH `0x55` (b...), Bech32 HRP `b3`
- **Testnet**: Bech32 HRP `tb3`, Regtest HRP `b3rt`
- DNS seeds cleared, Bitcoin checkpoints removed
- Network is fully isolated from Bitcoin

## Phase 2: PoW Replacement

- **Algorithm**: Double BLAKE3-256 (`BLAKE3(BLAKE3(header))`)
- Vendored official BLAKE3 C library into `src/crypto/blake3/`
- SIMD acceleration: SSE2, SSE4.1, AVX2, AVX-512 assembly for x86-64
- Added `CBlockHeader::GetPoWHash()` -- only PoW uses BLAKE3
- `CBlockHeader::GetHash()` remains Double SHA-256 (block IDs, merkle, txids)
- Updated `CheckProofOfWork()` and all callers to use `GetPoWHash()`
- Updated `bitcoin-util grind` to use BLAKE3 for nonce search

### Key design decision

Block *identity* hashes stay SHA-256d. Only the proof-of-work validation
switches to BLAKE3. This preserves compatibility with the existing P2P protocol,
merkle tree structure, and transaction ID format.

## Phase 3: Consensus Parameters

| Parameter | Value |
|-----------|-------|
| Block time target | 600s (10 min) |
| Initial block reward | 50 B3C |
| Halving interval | 210,000 blocks (~4 years) |
| Max supply | 21,000,000 B3C |
| Difficulty retarget | Every 2016 blocks |
| Early difficulty guard | First 10,000 blocks: 25% drop if block > 20 min |

## Phase 4: Genesis Block

- Mined unique genesis blocks for mainnet, testnet, and regtest using BLAKE3 PoW
- Genesis timestamp: `"B3Chain — A new satisfying proof-of-work 2025-06-15"`
- Genesis miner script: `contrib/genesis/mine_all_genesis.py`

**Genesis hashes:**

| Network | Block Hash |
|---------|-----------|
| Mainnet | `8c19b11553c449cfe6f8b00c830b8e34249529fd9521cb4825541df9b0372de4` |
| Testnet | `6c86f9f97ee9f0ae35e6a28f6c93d6d80e91ee8c97eec08e6b69e3bdb4bb4fa5` |
| Regtest | `8c19b11553c449cfe6f8b00c830b8e34249529fd9521cb4825541df9b0372de4` |

## Phase 5: Branding

- All binaries renamed: `b3chaind`, `b3chain-cli`, `b3chain-tx`, `b3chain-wallet`, `b3chain-qt`, `b3chain-util`
- Data directory: `~/.b3chain/` (Linux), `%APPDATA%\B3Chain\` (Windows)
- Config file: `b3chain.conf`
- User agent: "B3Chain Core"
- `b3chaind --version` prints "B3Chain Core"

## Phase 6: Reference CPU Miner

- **CPU miner**: `contrib/miner/b3chain-cpuminer.py`
  - Uses `getblocktemplate` / `submitblock` RPC (BIP 22/23)
  - Cookie and password authentication
  - Multi-threaded mining support
  - Hash rate benchmarking mode (~1.4 MH/s single-thread)
- **Mining documentation**: `doc/mining.md`
  - PoW algorithm overview and 80-byte header layout
  - `getblocktemplate` workflow + Python pseudocode
  - Reference CPU miner usage
  - Performance considerations and difficulty adjustment
- **Stratum / pool implementer guide**: `doc/stratum.md`
  - Authoritative pool-side PoW computation contract
  - BLAKE3 single-hash, double-hash, and 80-byte block-header test vectors
  - Stratum protocol differences from Bitcoin (share validation, block
    submission, extranonce, default ports)
  - Reference to the official BLAKE3 specification
- **PoW design document**: `doc/b3chain-pow-design.md`
  - Dual-hash architecture rationale
  - SIMD acceleration details
  - Security considerations

### Phase 6.1 verification (added 2026-05-15)

Tier-3 verification artifacts for the internal miner (`generatetoaddress`,
`generatetodescriptor`, `generateblock`) prove that `GenerateBlock()`'s
nonce loop in `src/rpc/mining.cpp:142` calls
`CheckProofOfWork(block.GetPoWHash(), ...)` rather than
`CheckProofOfWork(block.GetHash(), ...)`:

- **Master checklist**: [`doc/PHASE-6-VERIFICATION.md`](PHASE-6-VERIFICATION.md)
  with one row per check (comment-to-code mapping, loop location, bypass-path
  enumeration, end-to-end live-regtest re-derivation).
- **Verifier**: [`contrib/testing/audit/audit-internal-miner.sh`](../contrib/testing/audit/audit-internal-miner.sh)
  runs all four checks and rewrites the status column of the master
  checklist in place. Supports `--static`, `--e2e-only`, and `--dry-run`.
- **End-to-end helper**: [`contrib/testing/audit/audit-internal-miner-e2e.py`](../contrib/testing/audit/audit-internal-miner-e2e.py)
  spawns an isolated regtest `b3chaind`, mines 5 blocks via each of the
  three internal-miner RPCs, then independently re-derives BLAKE3d and
  SHA-256d for every produced header in Python and asserts the dual-hash
  invariants block by block.
- **Audit index**: row `M-1` added to [`doc/SECURITY-AUDIT.md`](SECURITY-AUDIT.md);
  the new script is also invoked from
  [`contrib/testing/audit/verify-phase11.sh`](../contrib/testing/audit/verify-phase11.sh)
  so a single command continues to validate the full audit suite.

The verification artifacts add no consensus or production code; Phase 6
remains COMPLETE.

### Phase 6.2: Stratum mining pool (added 2026-05-15)

A production-shaped Stratum V1 mining pool ships under
[`contrib/testnet/pool/`](../contrib/testnet/pool/) so anyone can point
a BLAKE3 miner at the testnet endpoint and start contributing hash
power on day one. The pool is a self-contained Node.js + TypeScript
application split into three systemd-managed services that share one
PostgreSQL ledger.

**Three services** (`b3chain-pool-stratum`, `b3chain-pool-daemon`,
`b3chain-pool-web`):

- **Stratum** speaks Stratum V1 (`mining.subscribe` / `authorize` /
  `submit`) on TCP port 3333. Per-connection state, per-connection
  vardiff, and BLAKE3d share validation against both the share target
  and the network target. Forwards every accepted share to the daemon
  over a UNIX domain socket so a stratum restart never loses data.
- **Daemon** owns the persistent ledger: batched share writes, 1-minute
  hashrate buckets, block confirmation polling, PPLNS crediting
  (`creditPplns()` runs at 100 confirms, idempotent via
  `blocks.pplns_credited`), and the hourly `sendmany` payout job
  driven by each user's `minimum_payout_b3c` and validated payout
  address.
- **Web** is Express + EJS + Socket.IO behind nginx at
  `https://pool.b3chain.org/`. Public landing page, `/getting-started`,
  `/blocks`. Verified accounts (signup → email-verify → login →
  password-reset → optional TOTP 2FA) using `argon2`, `cookie-session`,
  CSRF tokens, and `nodemailer`-over-Postfix. Per-user dashboard with a
  Chart.js hashrate graph fed by Socket.IO push updates (no polling,
  per the workspace `complete-implementation` rule). Operator view via
  `/metrics` (Prometheus).

**Schema** (`db/migrations/{001,002,003}_*.sql`): `users`, `workers`,
`sessions`, `email_verify_tokens`, `password_reset_tokens`, `shares`
(partitioned by day, retained 30 days), `hashrate_buckets`,
`pool_hashrate_buckets`, `blocks`, `payouts`, `payout_recipients`, and
the append-only `balance_entries` ledger.

**Reward scheme**: PPLNS over the last 4032 weighted shares (two
retarget windows). Default pool fee 1%, default minimum payout 1.0
B3C; both configurable per-user.

**Documentation**:

- [`docs/ARCHITECTURE.md`](../contrib/testnet/pool/docs/ARCHITECTURE.md)
- [`docs/STRATUM-PROTOCOL.md`](../contrib/testnet/pool/docs/STRATUM-PROTOCOL.md)
- [`docs/PPLNS.md`](../contrib/testnet/pool/docs/PPLNS.md)
- [`docs/DEPLOYMENT.md`](../contrib/testnet/pool/docs/DEPLOYMENT.md)
- [`docs/OPERATOR-RUNBOOK.md`](../contrib/testnet/pool/docs/OPERATOR-RUNBOOK.md)

**Tests**: unit (`tests/{blake3,address,difficulty,share-validator,vardiff,pplns,stratum}.test.ts`)
plus an end-to-end docker compose orchestrated mine-and-pay scenario
(`tests/e2e/`) and a Playwright auth-flow smoke (`tests/playwright/`).
The PPLNS unit test reproduces the worked example documented in
`docs/PPLNS.md` (alice 19.80, bob 4.95, carol 24.75).

**Verification**: [`doc/PHASE-6.2-VERIFICATION.md`](PHASE-6.2-VERIFICATION.md)
mirrors `PHASE-6-VERIFICATION.md` with one row per phase
(P-1: Mineable MVP, P-2: Verified accounts, P-3: PPLNS, P-4: Polish).
[`contrib/testing/audit/audit-stratum-pool.sh`](../contrib/testing/audit/audit-stratum-pool.sh)
runs every check (static greps + Node-test invocations) and rewrites
the status column in place. The script is wired into
[`contrib/testing/audit/verify-phase11.sh`](../contrib/testing/audit/verify-phase11.sh)
under the `P-1` row of the audits array so the same one-liner continues
to validate the full audit suite.

**Live deployment**: deployed to seed1 on 2026-05-15. Three services
running under systemd, fronted by nginx on
`https://pool.b3chain.org/` (Let's Encrypt cert via certbot --webroot
into the existing seed1 acme webroot). Stratum exposed at
`stratum+tcp://pool.b3chain.org:3333`. The deploy uncovered four
issues that were fixed in-flight and folded back into
`contrib/testnet/pool/install.sh` so the script is now actually
end-to-end idempotent on a fresh Ubuntu 22.04 host:

1. The system user needed a real `HOME` (npm refused to create
   `/home/b3chain-pool` under `useradd --no-create-home`).
2. `/etc/b3chain-pool/` had to be `750 root:b3chain-pool` so the
   pool user could traverse to read the env file.
3. `B3POOL_SMTP_FROM` had to be quoted in the env file so bash
   `source` would not interpret the `<noreply@…>` chevrons as a
   redirect.
4. Bitcoin Core 30+ no longer returns `coinbasetxn` from
   `getblocktemplate`, so the stratum job builder now composes the
   coinbase locally (BIP34 height + 8-byte extranonce reservation +
   `/B3Chain Pool/` tag, P2WPKH payout to the pool-payouts wallet,
   plus the `default_witness_commitment` OP_RETURN).

The pool is an overlay: it never touches consensus rules. Phase 6
remains COMPLETE.

### Phase 6.3: Stratum V2 pool support (added 2026-05-15)

Adds a pure-TypeScript Stratum V2 stack alongside the existing V1 pool.
All four SV2 roles ship in-tree under
[`contrib/testnet/pool/src/sv2/`](../contrib/testnet/pool/src/sv2/) and
re-use the V1 share validator and PPLNS pipeline unchanged:

- **Mining Protocol pool** (`b3chain-pool-stratum-v2`) — TCP `:3336`,
  Noise NX framed (X25519 ECDH + ChaCha20-Poly1305 AEAD + BLAKE2s).
  Standard + Extended channels; per-channel extranonce-prefix routing.
- **Job Declaration server** (in-process with the mining pool, TCP
  `:34264`) — issues single-use 32-byte job tokens, accepts
  `DeclareMiningJob`, validates the miner-built coinbase pays the
  pool's `B3POOL_PAYOUT_ADDRESS`, then pushes `SetCustomMiningJob` over
  the open Extended Mining channel.
- **Template Provider** (`b3chain-pool-tp`) — TCP `:8442` loopback.
  Adapts `getblocktemplate` to SV2 `NewTemplate` /
  `SetNewPrevHashTP` / `RequestTransactionData`.
- **V1<->V2 Translator** (`b3chain-pool-translator`) — TCP `:3337`.
  Reuses the V1 [`stratum/client.ts`](../contrib/testnet/pool/src/stratum/client.ts)
  on the south side, opens an Extended SV2 channel against the local
  pool on the north side, and translates jobs / shares / difficulty
  bidirectionally so legacy V1 miners benefit from the SV2 stack.

**Identity**: the pool is keyed by an Ed25519 *authority* keypair plus
an X25519 *static* keypair. The static key is wrapped in a
SignedCertificate (90-day default validity) signed by the authority
key. `install.sh` invokes `npm run sv2-keys` once on first install to
generate both keypairs, sign the cert, and publish the cert + the
authority pubkey under [`/var/www/b3chain/sv2/`](https://pool.b3chain.org/sv2/cert)
so miners can fetch them over plain HTTP without a TLS bootstrap (the
cert is self-authenticating against the out-of-band authority pubkey).
See [`docs/NOISE-KEYS.md`](../contrib/testnet/pool/docs/NOISE-KEYS.md).

**Schema** ([`db/migrations/004_sv2_sessions_and_jobs.sql`](../contrib/testnet/pool/db/migrations/004_sv2_sessions_and_jobs.sql)):
`sv2_sessions`, `sv2_channels`, `sv2_declared_jobs`. Audit-only —
share crediting still flows through the protocol-agnostic
[`shares`](../contrib/testnet/pool/src/lib/ipc.ts) IPC, and the daemon
does not need to know which protocol delivered each share.

**Dependencies**: adds `@noble/curves` (X25519 + Ed25519) and
`@noble/ciphers` (ChaCha20-Poly1305 + BLAKE2s) — same `@noble/*`
family as the existing BLAKE3 SHA256 wiring. No native compilation,
no FFI.

**Tests**:
[`tests/sv2-codec.test.ts`](../contrib/testnet/pool/tests/sv2-codec.test.ts),
[`tests/sv2-noise.test.ts`](../contrib/testnet/pool/tests/sv2-noise.test.ts),
[`tests/sv2-mining.test.ts`](../contrib/testnet/pool/tests/sv2-mining.test.ts),
[`tests/sv2-jd.test.ts`](../contrib/testnet/pool/tests/sv2-jd.test.ts),
[`tests/sv2-tp.test.ts`](../contrib/testnet/pool/tests/sv2-tp.test.ts),
[`tests/sv2-translator.test.ts`](../contrib/testnet/pool/tests/sv2-translator.test.ts).
Cover frame + type round-trips with golden vectors, the full Noise NX
handshake + AEAD transport (including a tampered-ciphertext rejection
case), the SignedCertificate sign+verify round-trip, channel state +
extranonce reconstruction, JD token issuance + expiry + single-use
enforcement, the coinbase-pays-pool validator (positive + negative
case), the TP message family, and a V1<->V2 translator integration
test against an in-process fake SV2 upstream pool. The
`tests/e2e/docker-compose.e2e.yml` stack now also boots
`pool-stratum-v2` and `pool-translator`, and
[`tests/e2e/mine-sv2-and-pay.test.ts`](../contrib/testnet/pool/tests/e2e/mine-sv2-and-pay.test.ts)
asserts that an in-tree TS SV2 miner gets PPLNS credit through the SV2
path.

**Verification**: [`doc/PHASE-6.3-VERIFICATION.md`](PHASE-6.3-VERIFICATION.md)
mirrors the Phase 6.2 checklist with one row per SV2 phase
(S-1 foundation, S-2 mining pool, S-3 template provider, S-4 job
declaration, S-5 translator, S-6 e2e).
[`contrib/testing/audit/audit-stratum-v2.sh`](../contrib/testing/audit/audit-stratum-v2.sh)
runs every check and rewrites the status column in place. The script
is wired into [`contrib/testing/audit/verify-phase11.sh`](../contrib/testing/audit/verify-phase11.sh)
under the new `P-2` row of the audits array.
[`doc/SECURITY-AUDIT.md`](SECURITY-AUDIT.md) gains a "Pool (Stratum V2)"
row in both the summary and the per-category section, bringing the
audit total from 12 to 14.

**Operator switches** (in `/etc/b3chain-pool/pool.env`, defaults are
all "off"):
- `B3POOL_SV2_ENABLE=true` — turns on the mining-protocol pool + the
  TP service. Opens UFW `3336/tcp`. TP stays loopback-only.
- `B3POOL_JD_ENABLE=true` — opens the JD listener on UFW `34264/tcp`.
- `B3POOL_TRANSLATOR_ENABLE=true` — runs the V1<->V2 translator and
  opens UFW `3337/tcp`.

The SV2 stack is fully additive and opt-in: V1 miners on `:3333`
continue to work unchanged regardless of the new flags.

**Live deployment**: deployed to seed1 on 2026-05-15 immediately
after Phase 6.2's V1 deploy. All six pool services
(`b3chain-pool-{stratum,daemon,web,stratum-v2,tp,translator}`) are
`active`. UFW open for `3333`, `3336`, `3337`, `34264`; TP stays on
loopback `8442`. The translator successfully completed a Noise NX
handshake against the local SV2 pool at boot ("loaded upstream pool
cert"), and the SV2 mining-protocol pool is producing one job every
2 seconds (matching the V1 `B3POOL_TEMPLATE_POLL_MS=2000`). The
SignedCertificate is reachable at
[`http://pool.b3chain.org/sv2/cert`](http://pool.b3chain.org/sv2/cert)
(106 bytes) and the pinning Ed25519 authority pubkey at
[`http://pool.b3chain.org/sv2/authority.hex`](http://pool.b3chain.org/sv2/authority.hex).
The deploy uncovered two issues that were fixed in-flight and folded
back into `contrib/testnet/pool/install.sh` so the script is now
end-to-end idempotent on a host that already has a Phase 6.2 V1 pool:

1. `install.sh`'s rerun branch now backfills the new SV2 / TP / JD /
   translator env vars into an existing `pool.env` instead of leaving
   them undefined (otherwise `npm run sv2-keys` had no path to write
   the keys to).
2. `npm run sv2-keys` now runs as `root`, not the `b3chain-pool`
   service user, because `/etc/b3chain-pool/` is mode `750
   root:b3chain-pool` -- the pool user can READ files there but
   cannot create new ones. After generation install.sh chowns the
   keyfiles to `640 root:b3chain-pool` so the runtime services can
   still load them at startup.

Phase 6 remains COMPLETE.

### Explorer: /mempool-summary empty-mempool crash + /internal-api/ rate-limit (fixed 2026-05-15)

`https://explorer.b3chain.org/mempool-summary` was showing
`Failed loading mempool: "error" ""` instead of an empty-state summary.
Two upstream `btc-rpc-explorer` bugs hit at the same time because
b3chain testnet usually has an empty mempool.

1. `app/api/coreApi.js#buildMempoolSummary` divides `totWeight / summary.totalWeight`.
   With an empty mempool `summary.totalWeight === 0`, so `NaN > 0.25`
   is false on every iteration and `topIndex` stays at its initial `-1`.
   The next statement is `satoshiPerByteBuckets[topIndex].buckets = 0`,
   which throws `TypeError: Cannot set properties of undefined (setting
   'buckets')`. The `/internal-api/build-mempool-summary` route's
   `catch` block only logs (`329r7whegee`) and never sends a response,
   so the AJAX call hangs until the browser gives up.
2. Once the page started failing, the 125ms status-poll (~8 req/s)
   blew through the default 200 req / 15 min rate limit. The skip
   function in `app.js` only excludes `"/api/"` (and the substring
   `"/api/"` is NOT contained in `"/internal-api/"`, since the
   leading slash is missing), so subsequent retries got 429'd.

Both bugs are patched defensively in
[`contrib/testnet/explorer/install.sh`](../contrib/testnet/explorer/install.sh)
with `sed` (matching the existing upstream-patch style):

- `coreApi.js`: change `if (topIndex < satoshiPerByteBuckets.length)`
  to `if (topIndex >= 0 && topIndex < satoshiPerByteBuckets.length)`
  so an empty mempool short-circuits the bucket-merge step and the
  function returns `{count:0, ...}` cleanly.
- `app.js`: OR-in `req.originalUrl.includes("/internal-api/")` next to
  the existing `/api/` skip, so the AJAX-heavy internal endpoints
  (mempool-summary, mining-summary, predicted-blocks) are not subject
  to the per-IP page-view rate limit.

One-shot script
[`contrib/testnet/explorer/patch-mempool-summary.sh`](../contrib/testnet/explorer/patch-mempool-summary.sh)
applies both patches to an already-deployed explorer without a full
reinstall, and
[`contrib/testnet/explorer/verify-mempool-summary.sh`](../contrib/testnet/explorer/verify-mempool-summary.sh)
exercises the three `/internal-api/` endpoints that drive the page so
this regression is easy to spot in the future.

Live verification (after deploy):
`GET /internal-api/build-mempool-summary` returns HTTP 200 in 17 ms
(was hanging until proxy timeout), the polling endpoint reports
`{count:0,done:0}`, `get-mempool-summary` returns a valid empty-mempool
JSON, and the page renders the empty-state view instead of the error
banner.

### Explorer: live mempool page (added 2026-05-15)

[`https://explorer.b3chain.org/live-mempool`](https://explorer.b3chain.org/live-mempool)
is a new page that replicates the layout of
`https://www.blockchain.com/explorer/mempool/btc`: a 5-up row of
metric cards plus an "Unconfirmed B3C Transactions" feed that updates
in real time without a page refresh. Rows match the upstream format
exactly (`Hash {first4}-{last4}` · `M/D/YYYY, HH:MM:SS` · `0.X B3C`)
and link to the existing `/tx/<txid>` page; the USD fiat column is
omitted because B3C has no market-price feed.

Architecture (overlay-only, no upstream `btc-rpc-explorer` changes):

- [`overlay/app/services/b3-mempool-feed.js`](../contrib/testnet/explorer/overlay/app/services/b3-mempool-feed.js):
  the single source of truth. `init()` starts a `setInterval(pollOnce,
  B3CHAIN_MEMPOOL_POLL_MS||3000)` loop that calls
  `getrawmempool true` (one RPC), diffs the keyed map against the
  previous snapshot, enriches new txids with output sum via
  `coreApi.getRawTransaction` (15-minute `txCache`, bounded
  concurrency of 4), keeps a newest-first 200-entry ring, broadcasts
  `event: tx-added`, `event: tx-removed`, and `event: info` over
  Server-Sent Events to every subscriber, and writes `:hb` every 30s
  to keep nginx from idling the stream closed.
- [`overlay/routes/b3-mempool-router.js`](../contrib/testnet/explorer/overlay/routes/b3-mempool-router.js):
  three routes mounted under `/live-mempool`: `GET /` renders the
  Pug page with a server-side snapshot, `GET /api/snapshot` is the
  REST initial-load + polling-fallback endpoint, `GET /api/stream` is
  the long-lived SSE response handled by `feed.subscribe(req, res)`.
  All `/api/*` paths sit under the existing rate-limit skip for
  `/api/`.
- [`overlay/views/b3-mempool/live.pug`](../contrib/testnet/explorer/overlay/views/b3-mempool/live.pug)
  + [`overlay/public/js/b3-mempool-live.js`](../contrib/testnet/explorer/overlay/public/js/b3-mempool-live.js)
  + [`overlay/public/css/b3-mempool.css`](../contrib/testnet/explorer/overlay/public/css/b3-mempool.css):
  the presentation layer. The client opens an `EventSource`, prepends
  rows with a 400ms fade-in, removes confirmed rows, and re-draws the
  fee-level histogram with Chart.js. If SSE never opens (or never
  delivers an event within ~8s) the page transparently falls back to
  polling `/api/snapshot` every 4s.
- [`overlay/b3-bootstrap.js`](../contrib/testnet/explorer/overlay/b3-bootstrap.js):
  mounts the router beside the existing `/charts` router and calls
  `mempoolFeed.init(coreApi, rpcApi)` so the loop starts at app boot.
- [`contrib/testnet/explorer/install.sh`](../contrib/testnet/explorer/install.sh):
  copies the five new overlay files into `node_modules/btc-rpc-explorer`,
  adds a `<link rel="stylesheet" href="./css/b3-mempool.css">` to
  `layout.pug`, and injects a "Live Mempool" navbar item beside the
  existing "Charts" item. All four `layout.pug` sed blocks are
  independently idempotent via `grep -q` gates.

Tier-3 verification trace (per `.cursor/rules/deep-reasoning-firmware.mdc`):

- TRIGGER: browser `GET /live-mempool` → Pug pre-renders the page with
  the current `feed.getSnapshot()` → inline script calls
  `B3LiveMempool.init({...})` → the client opens `EventSource(./live-mempool/api/stream)`.
- PROCESS (the LOOP): `b3-mempool-feed.js#pollOnce()` is driven by
  `setInterval` started in `init()`. Each cycle executes (file line
  refs):
  1. `await rpcApi.getRpcDataWithParams({method:"getrawmempool", parameters:[true]})`
  2. compute `newTxids` and `removedTxids`
  3. `await _enrichBatch(newTxids)` (concurrency 4, per-tx `coreApi.getRawTransaction`)
  4. prepend new entries to `recent` and cap at 200
  5. `_broadcast("tx-added", entry)` per new tx, then one
     `_broadcast("tx-removed", removedTxids)`, then one
     `_broadcast("info", {info, feeHistogram})`
  6. recompute `bytesPerFeeBucket` snapshot and `aggregateInfo`
  7. `prev = nextMap`
  Every step in the comment maps 1:1 to an executable line.
- COMPLETION: a new mempool tx reaches every connected SSE client
  within `pollMs + RPC latency` (≤ 4s on testnet).
- BYPASS: `pollOnce` is wrapped in a single `try/catch` that records
  `lastError`; one failed cycle does not stop the interval. If
  b3chaind is unreachable, `recent` and `prev` stay unchanged and the
  page renders whatever the buffer holds. If a client connection
  drops, `EventSource` auto-reconnects (~3s default) and the next
  `hello` re-syncs state. There is exactly one code path that
  produces broadcasts (`pollOnce → clients.forEach(write)`) and
  exactly one code path that produces snapshots
  (`/api/snapshot → feed.getSnapshot()`); no third path silently
  skips updating clients.

Risk summary:

- Daemon load: 1 `getrawmempool true` every 3s plus one
  `getrawtransaction` per *new* txid (cached for 15 min upstream);
  bounded by `rpcConcurrency: 10` in explorer config.
- Concurrent SSE clients: each holds an HTTP/1.1 connection. Capped at
  200; oldest is dropped past the cap.
- nginx buffering: `X-Accel-Buffering: no` header is set on the SSE
  response.
- Rate-limit: `/live-mempool/api/*` matches the existing `/api/` skip
  rule that was added in the previous section.

Live verification (after deploy):
`GET /live-mempool` renders the page with the hero and the 5-card
grid. `GET /live-mempool/api/snapshot` returns the current ring +
aggregates as JSON. `GET /live-mempool/api/stream` stays open, emits
`event: hello\ndata: {...}` immediately, then `:hb` every 30s; a
faucet-sent tx triggers a `tx-added` SSE within ~3s and a
`tx-removed` once the next block confirms it.

## Phase 7: Testing and QA

### 7.1 Unit Tests (C++)

**Result: 148 passed, 0 failed, 1 skipped**

Key B3Chain-specific tests:
- `crypto_tests/blake3_single_hash` -- BLAKE3 test vectors
- `crypto_tests/blake3_double_hash` -- Double BLAKE3 construction
- `crypto_tests/blake3_dual_hash_design` -- GetHash() vs GetPoWHash() independence
- `crypto_tests/blake3_rejects_sha256d_nonce` -- Cross-algorithm uncorrelation
- `crypto_tests/blake3_simd_acceleration` -- SIMD degree verification
- `miner_tests` -- Block mining with BLAKE3 PoW
- `pow_tests` -- Difficulty target checking

### 7.2 Functional Tests (Python)

**Result: 258 passed, 0 failed, 19 skipped**

Skipped tests fall into these categories:
- Tests requiring SHA256d-mined blocks (incompatible with BLAKE3 PoW)
- Tests requiring assumeutxo checkpoints (not yet configured)
- Tests requiring BDB wallet support (compiled with SQLite only)
- Tests requiring external tools (e.g., `usdt` tracing)

All 258 passing tests cover: P2P networking, mining RPCs, wallet operations,
block validation, mempool, RPC interface, and more.

### 7.3 Network Simulation

**Result: 19/19 checks passed**

Multi-node regtest simulation (`contrib/testing/regtest-simulation.sh`):
- 3 interconnected nodes on localhost
- 2016 blocks mined (full difficulty retarget period) in ~44 seconds
- Block propagation verified across all nodes
- Wallet send/receive including cross-node transfers
- UTXO set hash agreement across all nodes
- Genesis hash verification
- Chain work consistency

### 7.4 BLAKE3 PoW Verification

**Result: 9/9 vectors passed**

Standalone verification script (`contrib/testing/verify-blake3-pow.py`):
- Single BLAKE3 test vectors (3 tests)
- Double BLAKE3 test vectors (2 tests)
- Block header PoW hash vectors (4 tests)
- Optional live block verification from running node

---

## Test Results Summary

```
C++ Unit Tests ........... 148 passed, 0 failed, 1 skipped
Python Functional Tests .. 258 passed, 0 failed, 19 skipped
Regtest Simulation ....... 19/19 checks passed (2016 blocks, 3 nodes)
BLAKE3 Verification ...... 9/9 vectors passed
```

## Phase 8: Deployment (partial)

### Website deployed

- **Live at**: [https://b3chain.org](https://b3chain.org)
- **Testing page**: [https://b3chain.org/testing.html](https://b3chain.org/testing.html)
- **Source**: [github.com/b3chain/b3chain-website](https://github.com/b3chain/b3chain-website)
- Server: nginx on Ubuntu, git-based deployment from GitHub
- SSL: Let's Encrypt with auto-renewal

### Testing page published

The public Testing & Verification page includes:
- BLAKE3 test vectors (single, double, block header)
- PoW formula and pseudocode for independent implementation
- Regtest simulation walkthrough (19 checks, 2016 blocks, 3 nodes)
- Full test results summary (434 total checks, 0 failures)
- Known limitations and honest engineering disclosure
- Security issue reporting (security@b3chain.org)

### Source code published

- **Core repo**: [github.com/b3chain/b3chain](https://github.com/b3chain/b3chain) (branch: `b3chain-main`)
- **Website repo**: [github.com/b3chain/b3chain-website](https://github.com/b3chain/b3chain-website) (branch: `main`)
- Default branch set to `b3chain-main`
- Bitcoin Core upstream preserved as `upstream` remote
- Server at b3chain.org deployed via git pull from GitHub

### Comprehensive Bitcoin-to-B3Chain rebranding (Phase 5b)

Complete audit and update of all remaining Bitcoin references across the codebase:

**User-visible strings (207 files, 2400+ lines changed):**
- CMakeLists.txt: Project name `B3ChainCore`, descriptions, configure summary
- Qt GUI: All tooltip/status text (send, receive, sign/verify, PSBT, network)
- URI scheme: `bitcoin:` -> `b3chain:` (guiutil, paymentserver, tests)
- IPC process names: `bitcoin-node` -> `b3chain-node`
- RPC help text: Mining commands reference "b3chain" not "bitcoin"
- Signed message magic: `"B3Chain Signed Message:\n"`
- Key verification string: `"B3Chain key verification\n"`
- Unit descriptions: "B3C", "Milli-B3C", "Micro-B3C"
- Translation context: `"b3chain-core"` throughout

**Documentation:**
- SECURITY.md: Rewritten for B3Chain (security@b3chain.org)
- CONTRIBUTING.md: Updated project name, issue tracker, repo URLs
- Build docs (unix/osx/windows): Binary names, clone URLs, data dirs
- tor.md, zmq.md, tracing.md, multiprocess.md: Binary names
- Test READMEs: Binary names updated

**Protocol-level decisions:**
- `bip324.cpp` `"bitcoin_v2_shared_secret"` kept for P2P compatibility
- `netaddress.h` `sha256("bitcoin")` kept for protocol compatibility
- `clientversion.cpp` Bitcoin Core copyright check kept for attribution
- Key IO tests correctly verify Bitcoin addresses are rejected

---

## Phase 11: Security (self-audit pass 1) — COMPLETE

The structured Phase 11 self-audit was added before any mainnet launch
work. Every B3Chain-specific code path now has a script that verifies
its consensus invariants, plus a website detail page with tutorials and
expected output. **All 11 audit items PASSED on the first end-to-end run
(after fixing the regressions the audit itself caught).**

**Master checklist:** [`doc/SECURITY-AUDIT.md`](SECURITY-AUDIT.md)

| ID | Audit | Script | Result |
|----|-------|--------|--------|
| C-1..C-4 | Supply cap, halving, retarget bounds | `audit-supply-cap.py` | PASS (9/9) |
| H-1 | PoW / Block-ID hash isolation (BLAKE3 vs SHA-256) | `audit-pow-isolation.py` | PASS (7/7) |
| N-1 | Network isolation (magic bytes, DNS seeds) | `audit-network-isolation.py` | PASS (15/15) |
| W-1 | Bitcoin address rejection (36 samples) | `audit-address-rejection.py` | PASS (8/8) |
| W-2 | HD wallet BIP44 coin_type 9333 | `audit-hd-coin-type.py` | PASS (9/9) |
| B-1 | SIMD vs portable C BLAKE3 differential | `audit-simd-blake3.py` | PASS (4/4, 1037 inputs) |
| B-2 | Rebranding regression scan | `audit-rebranding.sh` | PASS (6/6, after fixes) |
| A-1 | 51% double-spend live demo | `audit-51-attack-sim.py` | PASS (4/4, full reorg) |

**Findings caught and fixed by the first audit run:**
- 5 leftover Qt `tr()` strings still said "Bitcoin" (intro, guiutil,
  sendcoinsdialog, addressbookpage)
- `src/rpc/rawtransaction_util.cpp` raised "Invalid Bitcoin address"
- `doc/Doxyfile.in` set `PROJECT_NAME = "Bitcoin Core"`
- ~30 `bitcoind` / `bitcoin-cli` references in `contrib/*/README.md`
  bulk-renamed to `b3chain*`

**HD wallet coin_type decision:**
- Mainnet: **`coin_type 9333`** (proposed; SLIP-0044 registration to
  follow). See [`doc/b3chain-bip44.md`](b3chain-bip44.md).
- Testnet/regtest: `1` (per BIP44 standard).
- Implemented in
  [`src/wallet/walletutil.cpp::GenerateWalletDescriptor`](../src/wallet/walletutil.cpp).

**C++ counterpart tests:** `src/test/audit/consensus_invariants_tests.cpp`
runs the supply-cap, PoW-isolation, and magic-bytes checks inside CTest
on every build.

**Public test pages:**
- Hub: [b3chain.org/testing.html](https://b3chain.org/testing.html)
- Phase 11 master: [b3chain.org/testing/security-audit.html](https://b3chain.org/testing/security-audit.html)
- 51% attack explainer + live demo: [b3chain.org/testing/51-attack.html](https://b3chain.org/testing/51-attack.html)

**Out of scope for Phase 11.1 (deferred):**
- External professional audit (to be commissioned before mainnet)
- SLIP-0044 PR for coin_type 9333 (will be filed as a follow-up)
- CI matrix to test SIMD BLAKE3 on every CPU feature combination

---

## Phase 11.2: Verification, Inheritance, BLAKE3-vs-SHA-256 Comparison, Roadmap

Layered on top of the Phase 11.1 self-audit. No consensus changes; this
phase only adds evidence and tooling.

**A. Verification of the Phase 11.1 work**
- [`doc/PHASE-11-VERIFICATION.md`](PHASE-11-VERIFICATION.md) — master
  checklist with one row per Phase 11 deliverable, each with an
  acceptance criterion, runnable verifier command, and expected output.
- [`contrib/testing/audit/verify-phase11.sh`](../contrib/testing/audit/verify-phase11.sh) —
  end-to-end verifier; flips checkboxes in `PHASE-11-VERIFICATION.md`
  and exits non-zero on any FAIL.
- Helpers: `verify_links.py` (on-disk link checker for the website),
  `verify_checklist.py` (validates `SECURITY-AUDIT.md` structure).

**B. Bitcoin security inheritance**
- [`doc/SECURITY-INHERITANCE.md`](SECURITY-INHERITANCE.md) — inventory
  mapping every Bitcoin invariant to its upstream test and B3Chain
  status (`inherited` / `inherited-with-rebrand` / `diverged-by-design`
  / `failing-investigation`).
- [`contrib/testing/audit/audit-bitcoin-inheritance.sh`](../contrib/testing/audit/audit-bitcoin-inheritance.sh) —
  runs the full upstream `ctest` + `test_runner.py --extended` suite
  and classifies every result.
- [`contrib/testing/audit/lib/inheritance_classify.py`](../contrib/testing/audit/lib/inheritance_classify.py) —
  the classifier; allowlists known divergences (PoW algo, mainnet
  UTXO snapshot fixtures), fails on anything else.
- Public page: [`b3chain.org/testing/bitcoin-inheritance.html`](https://b3chain.org/testing/bitcoin-inheritance.html).

**C. BLAKE3 vs SHA-256 comparative suite**
- [`contrib/testing/compare/`](../contrib/testing/compare/) folder with
  three runnable comparisons (throughput, block-validation wall time,
  length-extension demo) and four data-only docs (ASIC landscape,
  energy, attack surface, collision margin).
- Shared helper: `lib/compare_common.py` (timer, host info, JSON
  result schema, baseline loader).
- Orchestrator: `run-all-compare.sh`.
- CI: [`.github/workflows/compare-bench.yml`](../.github/workflows/compare-bench.yml) —
  runs the throughput benchmark on every PR, fails if BLAKE3-d
  regresses by more than 10% versus the pinned baseline in
  `contrib/testing/compare/baseline.json`.
- Public hub: [`b3chain.org/testing/compare.html`](https://b3chain.org/testing/compare.html)
  + 7 detail pages under `testing/compare/`.

**D. Tutorials and forward-looking roadmap**
- [`contrib/testing/audit/tutorials/`](../contrib/testing/audit/tutorials/) —
  one Markdown tutorial per audit (problem → theory → demo → exercise
  → reading) for the 7 audits + the 51% attack page.
- [`contrib/testing/audit/inject-tutorial.py`](../contrib/testing/audit/inject-tutorial.py) —
  idempotent injector; weaves the tutorial markdown into the
  corresponding website page between `<!-- TUTORIAL --> / <!-- /TUTORIAL -->`
  markers.
- [`doc/SECURITY-ROADMAP.md`](SECURITY-ROADMAP.md) — eight prioritised
  improvements (OSS-Fuzz, reproducible Guix builds, continuous bench
  CI, external cryptographic audit, bug bounty, PQC experiment,
  checkpoint key ceremony, hardware-rooted miner integrity).
- Public page: [`b3chain.org/testing/roadmap.html`](https://b3chain.org/testing/roadmap.html).

**Acceptance check**
- `python3 contrib/testing/audit/verify_links.py b3chain-website` →
  exit 0; OK on 27 pages and 216 on-disk references at the time of
  this commit.
- `python3 contrib/testing/audit/inject-tutorial.py` → idempotent on a
  second run (0 changed, 8 unchanged).

---

## Phase 8a: Testnet Bootstrap — COMPLETE

The B3Chain public testnet is **live**. Anyone can join with
`b3chaind -chain=test`; peer discovery is automatic via the operator-run
seed cluster.

### Code change

- `src/kernel/chainparams.cpp::CTestNetParams` now wires
  `vSeeds.emplace_back("testnet-seed.b3chain.org.")` and points
  `vFixedSeeds` at the BIP155-encoded fallback list compiled in from
  `contrib/seeds/nodes_test.txt`.
- `contrib/seeds/nodes_test.txt` lists the three operator-run seeds:
  `166.88.4.250:18533`, `151.158.1.22:18533`, `151.158.1.60:18533`.
- `src/chainparamsseeds.h` regenerated.

### Operations

- `contrib/deploy/bootstrap-testnet-node.sh` — idempotent installer
  that takes a fresh Ubuntu 22.04/24.04 host to a hardened
  systemd-managed `b3chaind -chain=test`, with public P2P on `:18533`
  and RPC bound to `127.0.0.1:18534`. Auto-scales `-j` by available
  RAM and skips `cap'n proto` via `-DENABLE_IPC=OFF`.
- `contrib/testnet/faucet/`   — Flask faucet (24 h cooldown per IP +
  per address) + systemd unit + installer.
- `contrib/testnet/miner/`    — always-on `b3chain-cpuminer.py`
  systemd unit + installer; coinbase paid into the local `miner`
  wallet.
- `contrib/testnet/explorer/` — `btc-rpc-explorer` v3.5.1 from upstream
  GitHub, run as a Node.js systemd unit. The installer applies a
  layered set of in-place patches so the UI reads "B3Chain" / "B3C"
  instead of "Bitcoin" / "BTC":
  - `app/coins/btc.js`: brand name, ticker, currency-unit *display*
    names (`name:` field only — internal lookup keys are left as
    "btc"/"BTC" so upstream code paths that round-trip the value
    keep working), per-network site titles, demo-site cross-links,
    mainnet color, genesis hashes; mining-pool registry URLs are
    deleted to avoid 30 s startup hangs against
    `raw.githubusercontent.com`.
  - `app/currencies.js`: rename `name:"BTC"` → `"B3C"` on the "btc"
    entry of `global.currencyTypes`, and install a `b3c → btc` alias
    so templates that re-look-up the unit (e.g.
    `views/includes/index-network-summary.pug:307`) keep working.
  - `app.js`: widen the daemon-subversion regex to accept both
    `/Satoshi:.../` and `/B3Chain:.../`.
  - `views/layout.pug` + `views/layout-iframe.pug`: rebrand
    masthead, og/twitter meta, canonical URL, currency picker
    (label-only), apple-mobile-web-app-title, footer link to
    `github.com/b3chain/b3chain`; strip the upstream donate +
    twitter footer buttons; rename the "Bitcoin Quote of the Day"
    iframe title.
  - `views/index.pug`, `views/error.pug`, `views/block-stats.pug`,
    `views/mining-summary.pug`: rebrand "Bitcoin Core" daemon refs
    to "B3Chain Core" and the welcome banner to "Made for
    B3Chain".
  - `views/includes/shared-mixins.pug`: defensive guard for
    coinbase-only blocks (avoids `Object.keys(undefined)` crash on a
    fresh chain) + tooltip BTC → B3C rebrand.
  - `routes/baseRouter.js`: cap the difficulty-Δ averaging window
    to the last 100 blocks so the home-page prediction reflects
    recent mining velocity instead of the months-long
    genesis-to-first-block gap.
  - `app/coins/btcFun.js`: replace upstream Bitcoin-history events
    with `module.exports = { items: [] }`.
- `contrib/testnet/faucet/topup.sh` (new) + cron entry — the faucet
  wallet auto-tops-up from the `miner` wallet when its balance falls
  below threshold. The send call pins `fee_rate=1 sat/vB` as a
  defensive fallback so it succeeds even when `estimatesmartfee` has
  no data on a young chain.
- `contrib/deploy/bootstrap-testnet-node.sh` now writes
  `fallbackfee=0.00001` into the auto-generated `b3chain.conf`
  `[test]` section. Without it, every wallet `sendtoaddress` on a
  fresh chain fails with `Fee estimation failed. Fallbackfee is
  disabled.`
- `contrib/deploy/bootstrap-testnet-node.sh` and
  `contrib/deploy/fail2ban-tune.sh` (new) install + harden
  `fail2ban`: `maxretry=10`, `bantime=5m`, automatic allow-list of
  `127.0.0.1/8` + the host's RFC1918 addresses + any
  `--ignore-ip` operator IPs. The longer ban window of the upstream
  default had locked the operator out of seed1 during initial
  deployment.
- `contrib/testnet/monitor/`  — cron-driven seed status snapshot
  exported as `/testnet-status.txt`. Polls all three seeds: seed1 via
  loopback RPC, seed2 + seed3 over a dedicated SSH key
  (`/root/.ssh/b3chain_monitor_ed25519`, generated by the installer).

### Explorer charts + theme overlay

`contrib/testnet/explorer/overlay/` is a self-contained add-on to the
upstream `btc-rpc-explorer` install. The installer copies the overlay
in and patches `app.js` with a single `require("./b3-bootstrap.js")`
line; everything else is overlay code so future explorer upgrades stay
tractable.

- New `/charts` index that mirrors blockchain.com's category layout
  (Currency Statistics, Block Details, Mining Information, Network
  Activity, Market Signals) plus a "Popular Stats" row.
- 25 chart pages at `/charts/<id>` using URL slugs that match
  blockchain.com (`hash-rate`, `difficulty`, `miners-revenue`, ...) so
  external links resolve to a recognisable page. USD-denominated
  Bitcoin charts are rendered in B3C with a "no exchange listing"
  callout.
- `app/services/b3-daily-aggregator.js` walks the chain from genesis
  in 200-block chunks, groups blocks by UTC date, persists to
  `${EXP_DIR}/data/daily.json`, and re-samples on a 30 s tip-poll
  loop. Survives explorer restarts (loads cache, resumes from
  `lastBlockHeight + 1`).
- `app/services/b3-pool-identifier.js` tags each block by its largest
  coinbase output address. Falls back to `address-only:<addr>`, so
  Hashrate Distribution shows useful data even before any pool
  registers a friendly name; operators can extend the
  `KNOWN_MINERS` map to attach labels.
- `routes/b3-charts-router.js` serves the index, detail pages, and a
  JSON time-series API at `/charts/api/:id`.
- `public/css/b3-theme.css` overlays a blockchain.com-flavoured theme
  on top of the upstream Bootstrap CSS: white card-on-light-grey, blue
  accents (`#1a4dd6`), sticky nav, rounded cards with hover lift,
  card-grid charts index. Uses the system UI font stack (no third-
  party font loads — keeps `BTCEXP_PRIVACY_MODE=true` honest).
- `public/js/b3-charts.js` renders Chart.js v4 line / doughnut /
  stacked-area charts with time-range selectors (1W / 1M / 3M / 1Y /
  ALL) and a Linear/Log toggle. Uses the bundled
  `chartjs-adapter-moment` so the time axis resolves dates without
  extra dependencies.
- `install.sh` additions: copy overlay, mount router, inject theme
  CSS link + Charts nav item via two idempotent sed patches; add
  `$EXP_DIR/data` to `ReadWritePaths` and export
  `B3CHAIN_CHARTS_DATA_DIR` so the systemd-confined service can write
  the daily cache.
- Bug fix: the `b3chainCurrencyLabels` injection in `install.sh` was
  using 8 tabs of indentation, which closed the `.dropdown-menu` block
  one level early in pug and leaked the entire settings dropdown
  content (Display Currency / Theme / Display Timezone / More
  settings... / Admin Dashboard) into the navbar as visible siblings.
  This was masked by the dark theme — the leaked text matched the dark
  navbar background — but the new light theme exposed it. Fixed by
  using 9 tabs (matching `- var items` depth) and added an awk-based
  self-heal step that re-indents any pre-existing depth-8 occurrence
  on every install, so older deploys repair themselves.

### Explorer transaction + address pages (blockchain.com-style)

Brings `/tx/<txid>` and `/address/<addr>` to blockchain.com visual + data
parity while staying inside the overlay model (no upstream patches that
would break on `btc-rpc-explorer` upgrades).

- `contrib/testnet/explorer/overlay/views/transaction.pug` (new) replaces
  the upstream tabbed transaction view with: a hero showing the full
  txid with copy + Confirmed/Unconfirmed badge (and a Coinbase tag +
  Miner badge when applicable); a 4-stat card row (Total Output /
  Block Reward, Fee / Fees Collected, Confirmations / Status, Date /
  First Seen); a side-by-side Inputs/Outputs grid with a directional
  arrow (mirroring blockchain.com), each row carrying the address
  link, output-type tag (P2WPKH / P2TR / P2SH / ...), and an
  UNSPENT/SPENT marker from the `utxos` array; and three collapsible
  `<details>` accordions for Advanced Details (hash, block, size,
  vsize, weight, version, locktime, raw hex), Scripts, and JSON. All
  upstream edge cases preserved: pruned-chain warnings, no-txindex
  callout, special-transactions `+funAlert`, mempool-predicted
  next-block inclusion notice.
- `contrib/testnet/explorer/overlay/views/address.pug` (new) replaces
  the upstream address view with: a hero showing the full address +
  encoding tag (P2WPKH / Bech32 / ...) + Mine / Watch-Only / miner-
  payout badges + a right-side QR code; a 4-stat card row (Total
  Received / Total Sent / Final Balance / # Transactions); a
  collapsible Technical Details accordion (Script Pub Key, Hash 160,
  Witness Version/Program, Electrum Script Hash); and a paginated
  transaction list that reuses the upstream `+txList` mixin so each
  row keeps the gain/loss delta semantics for the highlighted address.
  Graceful fallbacks for invalid-address, electrs-not-ready
  (`addressDetailsErrors`), zero-tx, and no-txindex paths.
- `contrib/testnet/electrs/install.sh` (new) installs
  [romanz/electrs](https://github.com/romanz/electrs) v0.10.6 as a
  sibling systemd service on seed1 pointed at the b3chaind testnet
  RPC. The service runs as a dedicated `electrs` system user (member
  of the `b3chain` group for read-only block access), listens on
  `127.0.0.1:50001` (Electrum protocol, loopback only — no TLS
  needed), and persists its index to `/var/lib/electrs/db`. A
  `tmpfiles.d` snippet keeps `blk*.dat` files group-readable across
  b3chaind restarts so the indexer doesn't lose access to newly-
  created block files.
- `contrib/testnet/explorer/install.sh`: copies the two new overlay
  pug files into upstream's `views/`, and wires the explorer to
  electrs by setting `BTCEXP_ADDRESS_API=electrum` +
  `BTCEXP_ELECTRUM_SERVERS=tcp://127.0.0.1:50001` in the env file.
  `BTCEXP_PRIVACY_MODE` is flipped from `true` to `false` so the
  Electrum address API code path is actually reached (both services
  run on the same host so there is no third-party data leak).
- `contrib/testnet/explorer/overlay/public/css/b3-theme.css`: appends
  `b3-tx-*`, `b3-addr-*`, plus shared `b3-tag` and `b3-callout`
  building blocks. New layout primitives: stat-card grid (4 columns,
  collapses to 2 on `≤900px`), io grid (`1fr 48px 1fr` with arrow
  rotated to vertical on mobile), hero with right-aligned QR (drops
  below address on mobile), accordion built on native `<details>` so
  no JavaScript needed.

### Live results

- Three seed nodes running B3Chain Core 30.2.0 in two different
  geographic regions, all peering with each other.
- Genesis hash served by every seed:
  `8c61fcbc6249f2518010fabc1589f91d35378f48757ef97323e8cb401103ae64`
- DNS seed `testnet-seed.b3chain.org` (round-robin A record) lets new
  nodes discover the cluster without any code change.
- Tagged as `v0.1.0-testnet`.

### Public docs

- Connection guide: <https://b3chain.org/testnet.html>
- Faucet: <https://faucet.b3chain.org>
- Block explorer: <https://explorer.b3chain.org>

### Phase 8b — soak period

The chain now enters a 4-8 week soak. Things being watched:
difficulty retarget cycles (every 2016 blocks), orphan rate, reorg
events, wallet sync time from genesis on a fresh node, memory and
disk growth on each seed. If a critical bug is found during soak the
chain is reset; otherwise it continues into Phase 8c (mainnet
launch).

---

## Repository Structure (B3Chain-specific files)

```
contrib/
  genesis/                    # Genesis block mining scripts
    mine_all_genesis.py       # Mine mainnet/testnet/regtest genesis
    gen_genesis.py            # Single genesis generator
    gen_genesis_extra.py      # Extra network genesis
    gen_genesis_testnet.py    # Testnet genesis generator
  miner/
    b3chain-cpuminer.py       # Reference CPU miner
  testing/
    README.md                 # Testing guide
    regtest-simulation.sh     # 3-node regtest simulation
    verify-blake3-pow.py      # BLAKE3 PoW verification
  testgen/
    gen_key_io_test_vectors.py # Address encoding test vectors

doc/
  b3chain-pow-design.md       # PoW design document
  mining.md                   # Mining workflow + reference CPU miner
  stratum.md                  # Pool implementer contract (PoW + test vectors + BLAKE3 spec)
  CHANGELOG.md                # This file

src/crypto/blake3/            # Vendored BLAKE3 library (C + x86-64 ASM)
```
