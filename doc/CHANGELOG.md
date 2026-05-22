# B3Chain Project History

## Explorer-ng header logo → B3Chain (2026-05-22)

- **Fix:** Nav still showed upstream `mempoolSpace` inline SVG (half-block +
  “mempool” wordmark) when `OFFICIAL=false`.
- **Deploy:** `patches/replace-header-logo.sh` swaps `app-svg-images
  name="mempoolSpace"` for `/resources/b3chain-explorer-ng-logo.svg` in
  master-page, preview, tracker, and footer; requires frontend rebuild.

## Explorer-ng copy + link rebrand at `/v2/` (2026-05-22)

- **Fix:** Served HTML still had upstream taglines (“Explore the full Bitcoin
  ecosystem”), `@mempool` Twitter meta, wrong canonical URL, and a missing
  `b3chain-explorer-preview.jpg` OG image.
- **Deploy:** `patches/rebrand-b3chain-copy.sh` rewrites user-visible copy and
  outbound links; `install.sh` runs strip + rebrand + chain-params on every
  install, rsyncs `src/resources/`, and falls back OG preview to
  `dashboard.png`; `verify.sh` fails on `Bitcoin ecosystem` in served HTML.

## Explorer-ng end-to-end UI rebrand (2026-05-22)

- **Footer/header:** `replace-header-logo.sh` (flexible regex for all
  `mempoolSpace` SVGs), new `rebrand-footer.sh` (B3Chain tagline, FAQ copy,
  hide mempool social links + mainnet network switchers, `b3chain.org` link).
  **Fix:** `rebrand-footer.sh` uses `#` perl delimiters (not `|`) — `|` in
  patterns had corrupted `global-footer.component.html` on seed1.
- **Ticker:** `apply-chain-params.sh` already maps visible `BTC` → `B3C`
  (including amount selector).
- **verify.sh:** checks built `main.*.js` and patched `global-footer` source,
  not only static `index.html`.

## Explorer-ng redirect /testnet4 → /v2/testnet (2026-05-22)

- **Fix:** `https://explorer.b3chain.org/testnet4` returned btc-rpc-explorer
  404 (`Not Found: /testnet4`). Nginx now 301-redirects mempool-style network
  paths (`/testnet4`, `/testnet`, `/mempool`, `/signet`, `/regtest`) to
  `/v2/testnet` until `--cutover` moves explorer-ng to `/`.

## Explorer-ng Matomo + mining-pool icons (2026-05-22)

- **Fix:** Console `stats.explorer.b3chain.org/m.js ERR_NAME_NOT_RESOLVED` —
  `enterprise.service.ts` still called `insertMatomo()` for
  `explorer.b3chain.org` but no analytics host exists. `patches/disable-matomo.sh`
  no-ops `insertMatomo()`; requires frontend rebuild to take effect in bundles.
- **Fix:** `/resources/mining-pools/{unknown,default}.svg` 404 — fork omitted
  upstream `src/resources/mining-pools/`; install now copies placeholder SVGs
  from `contrib/testnet/explorer-ng/assets/mining-pools/` (includes
  `b3chain-pool.svg`).

## Explorer-ng `/resources` + `/api` root paths (2026-05-22)

- **Fix:** B3Chain Live Explorer at `/v2/` failed in the browser because
  `index.html` loads `/resources/config.js` and the Angular app calls
  root-absolute `/api/v1/*` and `wss://…/api/v1/ws`, but production
  `ng build` omits `src/resources/` and nginx only proxied `/v2/api/`.
- **Deploy:** nginx now serves `/resources/` from
  `/var/www/b3chain-explorer-ng/resources/` and proxies `/api/` to the
  backend on `:8999`; `install.sh` installs
  `config/b3chain-frontend-config.json`, runs `generate-config.js`, and
  rsyncs `src/resources/` after every frontend build.
- **Verify:** `curl` returns 200 for `/resources/config.js` and
  `/api/v1/statistics/2h`; use `https://explorer.b3chain.org/v2/` (not
  `/mempool`, which is not a route on this host).

## B3Chain Live Explorer live at `/v2/` (2026-05-22)

- `b3chain/explorer-ng` repo created — clean-room AGPLv3 fork of upstream
  `mempool/mempool` rebranded as "B3Chain Live Explorer", squash-imported
  to `b3chain-main` after passing `tools/tm-audit.sh` (no `Mempool`
  brand-name, no `mempool.space`, no upstream logo assets in
  user-visible surfaces). Internal code identifiers (`MempoolBlock`
  class, `MEMPOOL` config namespace) are deliberately preserved to keep
  the upstream codebase compilable.
- Deployed on seed1 via `contrib/testnet/explorer-ng/install.sh` with
  feature flags **`--enable-stats --enable-audit --enable-mining`** and
  `b3chaind-testnet` running with **`txindex=1`**. Frontend served at
  `https://explorer.b3chain.org/v2/`; WebSocket upgrade live at
  `/v2/api/v1/ws`; old `btc-rpc-explorer` still on `/`.
- `verify.sh` (6 checks) PASSES: tm-audit clean, service active, RPC
  tip == backend tip, frontend index served, ws upgrade returns 101
  over `--http1.1`, no upstream brand string in served HTML.
- Mining indexer running: 31 blocks indexed; lastEstimatedHashrate
  ~273 H/s; B3Chain Pool row seeded for future blocks tagged with our
  pool string. RBF/CPFP endpoints HTTP 200 (empty list — awaits
  testnet faucet).
- `install.sh --cutover` (move `/v2/ → /` and demote old explorer to
  `/legacy/`) is implemented but **deferred to operator decision** —
  not run automatically.

## Explorer-ng scaffolding (2026-05-22)

- New tree `contrib/testnet/explorer-ng/` adds operator scaffolding for the
  upcoming **B3Chain Live Explorer** (a clean-room AGPLv3 fork of
  `mempool/mempool` with **all upstream branding stripped** — no "Mempool"
  marks, no half-block logo, no "Goggles"/"Accelerator" feature names; see
  `.cursor/plans/mempool_replication_seed1_6aa9c3e1.plan.md` "Trademark
  posture" section).
- `bootstrap-fork.sh` clones upstream at a pinned ref, runs the
  `tools/strip-upstream-brand.sh` codemod (deletes upstream brand assets,
  renames internal files, rewrites visible tokens), applies
  `patches/apply-chain-params.sh` (B3C ticker, bech32 HRPs, genesis hash
  placeholders), runs `tools/tm-audit.sh` (must pass), then squash-pushes a
  single neutral "import upstream sources" commit to
  `git@github.com:b3chain/explorer-ng.git@b3chain-main`.
- `install.sh` deploys the fork on seed1: Node 20, MariaDB, system user
  `b3chain-explorer-ng`, systemd unit, nginx site under `/v2/`, ZMQ pubs in
  `/etc/b3chain/conf.d/zmq.conf` (with `--enable-zmq`). Phase advance via
  flags: `--enable-stats` (P3), `--enable-mining` (P5), `--enable-audit`
  (P7), `--cutover` (move `/` from btc-rpc-explorer to explorer-ng).
- `verify.sh` smoke-tests post-install: tm-audit clean, service active,
  RPC tip == backend tip, frontend index served, WS upgrade, no upstream
  brand string in served HTML.
- `tools/tm-audit.sh` is the deploy gate: refuses any tree where the word
  `Mempool` (capitalized brand), `mempool.space`, "Mempool Goggles",
  "Mempool Accelerator", or upstream logo asset filenames appear, with
  carve-outs only for AGPL §5/§7 attribution and bitcoind RPC method
  names (`getrawmempool`, etc.). Auto-skips when run inside this
  bitcoin-core mono-repo (which legitimately mentions "mempool" in
  protocol code/docs); strict mode kicks in only inside the explorer-ng
  tree.
- Files: `README.md`, `bootstrap-fork.sh`, `install.sh`, `verify.sh`,
  `mariadb-schema.sh`, `tools/{tm-audit,strip-upstream-brand}.sh`,
  `patches/apply-chain-params.sh`, `nginx/explorer-ng.conf`,
  `systemd/b3chain-explorer-ng.service`, `config/{b3chain-config.json
  .template,zmq-snippet.conf}`, `assets/b3chain-explorer-ng-logo.svg`.

## CI matrix unblock (2026-05-21)

- Remove accidental `agent-runs.py` and vendored subtree `.github/workflows`
  copies under `src/crc32c`, `src/ipc/libmultiprocess`, `src/secp256k1`.
- Lint: `mlc` ignore `doc/outreach/`, `doc/strategy/`, and
  `doc/security/51-ATTACK-RESPONSE-SUMMARY.md` (links outside CI checkout).
- Fuzz: reset regtest chain in `p2p_handshake` when prior inputs advance the
  tip (fixes `ResetIbd` / `IsInitialBlockDownload` on Windows and macOS).
- Fuzz: exclude `b3pow_random_header` from CI smoke (ASan deadly signal under
  `-max_total_time=60` on empty corpus).
- CI: `TEST_RUNNER_TIMEOUT_FACTOR=180` on ARM32 and previous-releases jobs for
  `miner_tests` headroom.
- CI (p8): sanitizer/CentOS/i686/no-wallet jobs — timeout 180× and
  `-DREDUCED_CI_MINER_BLOCKS` (20-block import in `miner_tests`); CentOS/macOS
  `BITCOIN_CMD=b3chain -m`; Windows cross-built functional timeout 80×; tidy
  job cap 180m.
- CI: macOS native GUI job — same `TEST_RUNNER_TIMEOUT_FACTOR=180` and
  `REDUCED_CI_MINER_BLOCKS` (closes macOS GUI CTest failure on run 26172916022).
- Explorer: `patch-explorer-display.sh` — young-chain homepage shows blocks
  0..tip (while `height+1 <= 2×recentBlocksCount`), correct coin supply
  `(height+1)×subsidy`, scientific difficulty, estimated hashrate from
  `difficulty×2^32/target`, smart fees `0` when empty, genesis coinbase
  timestamps from v1.1.5 block time. Deployed on seed1 via
  `contrib/testnet/explorer/patch-explorer-display.sh`.
- **benchmark-trend** (p9): green on `41dc252463` (28m); tracks
  `B3PoW.*|CheckBlock.*|ConnectBlock.*` — separate from main `ci.yml` matrix.
- **Matrix sign-off** (p10): pending all `ci.yml` jobs `success` on a single
  HEAD after queue drains; see GitHub Actions checklist on latest push.

## v1.1.5 — testnet powLimit relaxation + miner RPC timeout fix (2026-05-21)

**Testnet-only consensus change.** Mainnet, signet, testnet4, and regtest
are untouched. Coordinated cold-start on seed1, seed2, and seed3.

### Consensus (`CTestNetParams` only)

- **`consensus.powLimit`** relaxed from v1.1.4's `0x1e01ffff`
  (`000001ffff…`) to **`0x1f00ffff`**
  (`0000ffff00000000000000000000000000000000000000000000000000000000`).
  ~128× easier than v1.1.4; intended for commodity single-thread CPU
  mining on the operator VPS (~1–2 min/block observed vs ~5–6 h at
  v1.1.4).
- **`operating_pow_floor_bits`** → `0x1effff80` (2× stricter than the
  new powLimit, same relationship mainnet keeps between powLimit and
  its operating floor).
- **Testnet genesis re-mined** at `0x1f00ffff`:
  ```
  CreateGenesisBlock(1739145601, 111470, 0x1f00ffff, 1, 50*COIN)
  hashGenesisBlock = ebc117cd39760da3c8a3687484858e8ea2cfbc88990fb587957b4ba956a661c6
  hashMerkleRoot   = 6fefcc8f9ca9674e3948b2a74c381f8abb9f0e38349fad3d62794ed3895269dc
  ```
  Tooling: [`contrib/genesis/mine_testnet_v115.py`](../contrib/genesis/mine_testnet_v115.py),
  [`contrib/genesis/mine_all_genesis.py`](../contrib/genesis/mine_all_genesis.py)
  (testnet entry updated).

**Implementation note:** the `uint256` powLimit literal must decode to
exactly the same target as compact `0x1f00ffff` — the shorter
`000000ffff…` form is 256× too strict and causes `DeriveTarget` to
reject the genesis block on load. See
[`doc/security/51-MONITORING-OPS.md`](security/51-MONITORING-OPS.md)
"v1.1.5 testnet powLimit divergence".

### Miner ops fix (no consensus change)

- [`contrib/testnet/miner/b3chain-testnet-miner.sh`](../contrib/testnet/miner/b3chain-testnet-miner.sh):
  **`ARGS` now includes `-rpcclienttimeout=0`**. Bitcoin Core recommends
  disabling the client timeout for mining RPCs; the default 900 s (and
  the interim 3600 s patch) caused hourly `"timeout reached"` while
  `b3chaind` kept hashing in overlapping `httpworker` threads — the
  client disconnect does not cancel `GenerateBlock()` in
  [`src/rpc/mining.cpp`](../src/rpc/mining.cpp).

### Deploy (seed1 / seed2 / seed3)

- Git: `c3866b06f7` (consensus + miner script), `0e3f7f3c45` (powLimit
  uint256 fix), `6d17f26913` (ops doc note) on `b3chain-main`.
- Built on seed1; `b3chaind` md5 `8b02b59e5ffadf33e7bdf4cec4b15440`
  installed on all three seeds.
- Wiped `testnet3/` on each seed; full 4-peer mesh restored.
- **Verified:** block 1 mined on seed1 in ~79 s; tip propagated to
  seed2/seed3; miner journal shows `mined block #1` with no timeout
  spam.

### Explorer fix (seed1)

After the v1.1.5 chain wipe, [explorer.b3chain.org](https://explorer.b3chain.org)
showed `Error building page: TypeError: Cannot read properties of undefined
(reading '0')`. Root causes:

- **`electrs-testnet`** was not restarted after cutover (deploy script
  referenced wrong unit `b3chain-electrs`); fixed in
  [`contrib/testnet/deploy_v115_seed1.sh`](../contrib/testnet/deploy_v115_seed1.sh)
  (wipe `/var/lib/electrs/db`, start `electrs-testnet.service`).
- **`btc.js` genesis metadata** still pointed at v1.1.4 hashes/coinbase
  txid; updated to v1.1.5 values in
  [`contrib/testnet/explorer/install.sh`](../contrib/testnet/explorer/install.sh)
  and idempotent post-cutover
  [`contrib/testnet/explorer/patch-v115-genesis.sh`](../contrib/testnet/explorer/patch-v115-genesis.sh).
- **Young-chain homepage crash:** btc-rpc-explorer loads
  `recentBlocksCount + 1` (default 11) block heights; with tip < 10
  this requested negative heights → RPC failure → `latestBlocks[0]`
  undefined. Patched `baseRouter.js` to clamp heights to `>= 0`
  (`B3Chain-negative-height-guard`) plus genesis coinbase
  `getrawtransaction` fallback (b3chaind rejects genesis coinbase via
  RPC).

**Verified:** homepage renders Latest Blocks table (heights 0–5) with no
error banner.


Closes the four stale-doc / dead-code gaps surfaced by the
"are all three miners updated to reflect B3PoW-Scratch v1.1?" audit
(May 2026).  No consensus change, no bitstream rebuild required, no
parity vectors touched.  The audit confirmed that the **CPU miner**
(`contrib/miner/b3chain-cpuminer.py`), the **FPGA RTL**
(`contrib/miner/b3miner-rtl/`), and the **FPGA host firmware**
(`contrib/miner/b3miner-firmware/`) all run B3PoW-Scratch v1.1.1
correctly; the **GPU miner** (`contrib/miner/b3chain-gpuminer/`) is
intentionally deprecated because B3PoW-Scratch is GPU-hostile by
design.  The fixes below are pure documentation, dead-code, and
source-organisation cleanups.

- **Stale `REG_ID` magic ID updated** from the pre-F-1 build-0001
  value `0xB3110001` to the current v1.1.1 build-0002 value
  `0xB3110002` in five operator-facing locations:
  [`contrib/miner/b3miner-firmware/components/b3_fpga/README.md`](../contrib/miner/b3miner-firmware/components/b3_fpga/README.md),
  [`contrib/miner/b3miner-rtl/README.md`](../contrib/miner/b3miner-rtl/README.md),
  [`contrib/miner/b3miner-rtl/docs/HWLOOP.md`](../contrib/miner/b3miner-rtl/docs/HWLOOP.md),
  [`contrib/miner/b3miner-rtl/BITSTREAM_LOAD.md`](../contrib/miner/b3miner-rtl/BITSTREAM_LOAD.md),
  and the table-comment headers in
  [`contrib/miner/b3miner-rtl/rtl/regfile.sv`](../contrib/miner/b3miner-rtl/rtl/regfile.sv)
  and
  [`contrib/miner/b3miner-rtl/sim/tb/tb_b3miner_top.sv`](../contrib/miner/b3miner-rtl/sim/tb/tb_b3miner_top.sv).
  The actual hardware driver (`params_pkg.sv:REG_ID_MAGIC`,
  `b3_fpga_regs.h:B3_FPGA_MAGIC`) was already at `0xB3110002` —
  this was purely a stale-comment sweep.  Unit-TB mock value in
  `sim/tb/tb_spi_slave.sv` left as-is (tests SPI protocol layer, not
  consensus).
- **`CONFIG_B3_POW_LEGACY_DOUBLE_BLAKE3` retired.**  Every b3chain
  network (mainnet, testnet, testnet4, regtest) runs B3PoW-Scratch
  v1.1.1 from genesis per
  [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md)
  §1, so the firmware's legacy-double-BLAKE3 opt-out is dead code.
  Removed the Kconfig option from
  [`contrib/miner/b3miner-firmware/main/Kconfig.projbuild`](../contrib/miner/b3miner-firmware/main/Kconfig.projbuild),
  removed the `#if !CONFIG_B3_POW_LEGACY_DOUBLE_BLAKE3` guard around
  `b3_fpga_init_scratchpad()` in
  [`contrib/miner/b3miner-firmware/components/b3_fpga/b3_fpga_worker.c`](../contrib/miner/b3miner-firmware/components/b3_fpga/b3_fpga_worker.c)
  (so the scratchpad regen runs unconditionally on every new
  parent), and rewrote the PoW paragraph in
  [`contrib/miner/b3miner-firmware/README.md`](../contrib/miner/b3miner-firmware/README.md)
  to say B3PoW-Scratch is the only supported algorithm.
- **`LANE_SHUFFLE` promoted to `params_pkg.sv`.**  The cross-lane
  diffusion permutation `{1, 6, 3, 0, 5, 2, 7, 4}` (SPEC §6.5) used
  to live as a local `LANE_PERM` inside
  [`contrib/miner/b3miner-rtl/rtl/mixing_core.sv`](../contrib/miner/b3miner-rtl/rtl/mixing_core.sv);
  it now sits in `params_pkg::LANE_SHUFFLE` next to `ITER_MUL`,
  `BLAKE3_PERM`, and `BLAKE3_IV` so every consensus-locked constant
  lives in one place and the file matches `ref/b3pow_ref.py`
  name-for-name.  Bit-equivalent to the prior local copy; parity
  vectors (`sim/vectors/*.hex`, `b3pow_consensus_vectors.json`)
  unchanged.  See
  [`contrib/miner/b3miner-rtl/CHANGELOG.md`](../contrib/miner/b3miner-rtl/CHANGELOG.md)
  v1.1.4 entry.

## Launch package — Phase 0 alignment (in progress)

Mining stack and public-facing docs aligned to **B3PoW-Scratch v1.1**,
removing the audit-flagged split where consensus / RTL / FPGA host had
moved to Scratch while the pool, miners, and docs still described
double-BLAKE3. Phase 0 is the credibility gate the rest of the launch
package depends on.

- **Pool share validator (TypeScript).** New
  [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../contrib/testnet/pool/src/lib/b3pow-scratch.ts)
  is a bit-exact port of `b3pow_ref.py`; new
  [`contrib/testnet/pool/src/lib/pad-cache.ts`](../contrib/testnet/pool/src/lib/pad-cache.ts)
  holds pristine per-parent scratchpads and hands out fresh copies per
  share (the canonical algorithm mutates its pad). Validator at
  [`contrib/testnet/pool/src/stratum/share-validator.ts`](../contrib/testnet/pool/src/stratum/share-validator.ts)
  now calls `b3powScratch(header, prevHashLE, padCopy)` instead of
  `blake3d(header)`. New parity test
  [`contrib/testnet/pool/tests/b3pow-scratch.test.ts`](../contrib/testnet/pool/tests/b3pow-scratch.test.ts)
  reproduces every entry in
  [`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json).
- **Reference CPU miner.**
  [`contrib/miner/b3chain-cpuminer.py`](../contrib/miner/b3chain-cpuminer.py)
  now defaults to B3PoW-Scratch (imports `b3pow_ref` via a sys.path
  shim), threads a process-shared `PadCache` through the pool and solo
  loops, and emits `pow_algo` + `prev_hash_le`/`be` in the JSONL
  `share_submit` event. The retired double-BLAKE3 algorithm remains
  available behind `--legacy-blake3d` for cross-checking historical
  vectors (with a stderr warning that such shares cannot be accepted).
- **GPU miner deprecated.**
  [`contrib/miner/b3chain-gpuminer/README.md`](../contrib/miner/b3chain-gpuminer/README.md)
  is now flagged as deprecated. It still computes the retired
  double-BLAKE3 PoW (B3PoW-Scratch is GPU-hostile by design); the
  tree is retained as a reference for the previous algorithm only.
- **Public-facing docs rewritten.**
  [`README.md`](../README.md),
  [`doc/b3chain-pow-design.md`](b3chain-pow-design.md),
  [`doc/mining.md`](mining.md), and
  [`doc/stratum.md`](stratum.md) now describe B3PoW-Scratch v1.1 as
  the live algorithm and point at SPEC.md / `b3pow_ref.py` /
  `b3pow_scratch.cpp` / the TS port for the byte-exact details.
  Oversell sweep: "ASIC resistance" claims replaced with
  measured-nuance language ("FPGA-economical, GPU-hostile, not
  ASIC-proof"). `SPEC.md` §11 now lists every in-tree implementation
  pointer in one table.
- **Pad-cache latent bug fix.**
  [`contrib/testing/verify-b3pow.py`](../contrib/testing/verify-b3pow.py)
  was caching the post-mix mutated pad. Switched to a pristine cache
  that hands out a fresh `bytearray` copy per call, matching the new
  TS / cpuminer pattern. CI parity is unchanged (`17/17` vectors pass).

## v1.1.3 — Operator-pinned chain recovery RPCs (current)

Single-coherent maintenance release stacked on `be8c1f6c24`.  **No
consensus change**: the new rejection path piggy-backs on the
existing `BlockValidationResult::BLOCK_DEEP_REORG` result code so
`net_processing.cpp` dispatches both flavours (`"deep-reorg-attempt"`
vs `"reorg-past-finalized"`) to the same `Misbehaving` handler.  No
chain-ID roll, no genesis re-mine.

Closes the gap that
[`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](security/RESPONSE-RUNBOOK-51ATTACK.md)
used to point at without backing mechanism: "operator-pinned manual
recovery" is now a real recipe with in-tree code, persistence, and a
watcher detector.  See [`B3POW-51-ATTACK-ANALYSIS.md §4.4`](security/B3POW-51-ATTACK-ANALYSIS.md)
for the BCH / ETC / Monero peer-chain comparison that motivated the
design.

### Group A — `Chainstate::{Finalize,Unfinalize,Park,Unpark}Block` + 5 new RPCs

- **`finalizeblock <hash>`**: pin a block on the active chain as the
  finalize horizon.  Any subsequent candidate that would reorg past
  this block is rejected with `BlockValidationResult::BLOCK_DEEP_REORG`,
  reason `"reorg-past-finalized"`.  Persisted in
  [`CBlockTreeDB`](../src/node/blockstorage.cpp) (new `'P'` key) so
  the pin survives node restart.  Bypass paths enumerated inline in
  [`src/validation.cpp`](../src/validation.cpp): genesis, off-active,
  lower-height, M-8 emergency-checkpoint conflict, 6-confirmation
  warning.
- **`unfinalizeblock`**: clear the pin (idempotent, persisted).
- **`parkblock <hash>` / `unparkblock <hash>`**: refuse to follow a
  branch on this node, reversibly.  Implemented as a thin wrapper
  over `Chainstate::InvalidateBlock` + the new `BLOCK_PARKED` bit
  in [`src/chain.h`](../src/chain.h) so unpark can reverse the park
  without disturbing genuine consensus-failure flags on the same
  segment.
- **`getfinalizedblockhash`** (read-only, `"blockchain"` category):
  returns `{hash, height, source ∈ {operator, max_reorg_depth}}` so
  monitoring can distinguish the explicit pin from the implicit M-4
  horizon (tip − `max_reorg_depth`).
- All four operator RPCs registered as `"hidden"` category, mirroring
  the existing `invalidateblock` / `reconsiderblock` pair.  The
  read-only `getfinalizedblockhash` is `"blockchain"` category and
  safe to advertise to monitoring fleets.

Implementation: commit `1bce9813e6`, 6 files / 541 lines.

### Group B — `detect_finalized_drift` watcher detector

Fourth detector added to
[`contrib/monitoring/51attack-watch.py`](../contrib/monitoring/51attack-watch.py)
(in addition to the three landed in v1.1.2):

- `finalized_drift_source_flip` — info-severity, fires on every
  `finalizeblock` / `unfinalizeblock` (= operator just touched the
  pin).
- `finalized_drift_operator_change` — warning, fires on a
  re-finalize without first unfinalizing.
- `finalized_drift_horizon_stall` — warning (escalates to critical
  at 2× threshold), fires when the implicit `max_reorg_depth`
  horizon does not advance for N consecutive polls while the tip
  does (= tip stalled vs cap drift).

New CLI flag `--finalized-stall-threshold` (default 5 polls / 2.5
min at the default 30 s `--interval`).  BYPASS path documented for
older `b3chaind` without the M-14 RPC: `RpcUnavailable` is logged
once via `finalized_rpc_missing_logged` and the detector silently
no-ops for the rest of the watcher process lifetime.  The other
three detectors keep running.

Implementation: commit `307191d070`, 199 lines.  Sanity tested with
8 new detector cases + 3 existing-detector regression cases (11/11
pass) via the in-process Tier-3 verify suite.

### Group C — Threat-model doc enhancements

Updates to
[`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](security/B3POW-51-ATTACK-ANALYSIS.md):

- `§1.2 mitigations table`: new M-14 row.
- `§1.3 what we do not claim`: new bullet 4 explaining why we
  *don't* ship BCH-style automatic finalization at depth 10.
- `§4.4 Comparison with peer chains` (new): side-by-side BCH /
  ETC / Monero / b3chain deep-reorg policy table with the
  rationale for our 200-block cap + opt-in operator pin.
- `V-1`, `V-2`, `V-5`, `V-7`, `V-12` mitigations: M-14 added to
  each (with vector-specific phrasing).
- `§6 cost matrix`: Notes column updated to cite M-4 + M-14
  on the rows where the operator pin is materially useful.
- `§7 recommendations matrix`: new R-17 row (M-14, status
  "Ship in v1.1.3").
- `§8 defended already`: new D4 row for the watcher daemon
  (now four detectors including `detect_finalized_drift`).
- `§10 provenance`: new functional tests + watcher unit tests
  listed for M-14 reproducibility.

### Group D — Runbook / roadmap / audit / changelog wiring

- [`RESPONSE-RUNBOOK-51ATTACK.md §3.0a`](security/RESPONSE-RUNBOOK-51ATTACK.md):
  new section *Operator-pinned recovery via M-14 RPCs (USE THIS
  FIRST)* with shell-line-by-shell-line recipes for the finalize,
  park, undo, and monitoring flows.  Sits one step BEFORE the
  existing `§3.1 Emergency checkpoint (LAST RESORT)`.
- [`SECURITY-ROADMAP.md §10`](SECURITY-ROADMAP.md): new section
  *Operator-pinned chain recovery RPCs (M-14)*, status
  `in-progress (RPCs landed in v1.1.3)`, with full scope / expected
  gain / risks blocks.
- [`SECURITY-AUDIT.md A-10`](SECURITY-AUDIT.md): new audit row
  cross-referencing M-14, BLOCK_PARKED, persistence, and the
  watcher detector.

### Forward references / out of scope

- aserti3-2d DAA (skipped — our LWMA-3 is more reactive to sudden
  hashrate drops, which is the actual F-3 / V-5 threat model).
- Avalanche pre-consensus (skipped — would compromise the
  lightweight-node story; v2.x conversation).
- Automatic finalization at any depth (explicitly rejected;
  see §4.4 of the analysis doc).

## v1.1.2 — Post-F-6 cleanup + in-house roadmap progress

Maintenance release stacked on top of `a24b77b60c` (the v1.1.1 F-6 fix).
No new consensus rules; no genesis re-mine; no chain-ID roll.  Closes
the gap between what `doc/CHANGELOG.md` and `doc/SECURITY-ROADMAP.md`
already described and what was actually in git, and lands the in-house
half of three SECURITY-ROADMAP deliverables.

- **F-6 follow-up cleanups (Group A).**
  - [`src/kernel/chainparams.cpp`](../src/kernel/chainparams.cpp):
    testnet4 was inheriting Bitcoin testnet4's `nMinimumChainWork`
    + `defaultAssumeValid` (block 91000 hash `...839d9b`).  Both
    zeroed to match the other production chains; the F-6 genesis
    re-mine rolled the chain ID so any inherited assumevalid was
    meaningless.  Pre-genesis: no live impact.
  - [`contrib/testnet/explorer/install.sh`](../contrib/testnet/explorer/install.sh):
    added `testnet4` + `signet` genesis-hash sed lines so a btc-rpc-explorer
    rebuilt against b3chain no longer falls back to upstream Bitcoin
    genesis hashes (which would 404 every block lookup).
  - [`b3chain-website/testing/test-vectors.html`](https://b3chain.org/testing/test-vectors.html)
    and `pow-verifier.html`: refreshed `SPEC_VERSION = 0x00010101`,
    mainnet `nBits = 0x1d7fffff`, and all six post-F-6
    `expected_pow_hash` values; vector names in the
    expected-output block updated to match the actual
    `consensus_vectors.json` schema.
- **Track the three untracked miner trees + CI workflows (Group B).**
  Four logical commits adding ~150 source files (~14,350 lines, all
  text, no binaries / no build artefacts):
  - `c55c08d913` — `.github/workflows/{ci.yml, b3miner-rtl.yml}` +
    `contrib/miner/b3miner-rtl/` (64 files / 8,260 lines).  The F-1
    ITER_MUL[7] fix in `ref/b3pow_ref.py` + `rtl/params_pkg.sv`, the
    F-4 `ref/tests/test_address_uniformity.py` uniformity gate, the
    F-6-touched `ref/gen_vectors.py`, the canonical SPEC.md, and all
    SystemVerilog + Vivado / Verilator scaffolding.
  - `105e50f567` — `contrib/miner/b3miner-firmware/` (42 files /
    2,714 lines).  ESP-IDF firmware tree for B3Miner-1 hardware.
  - `4cd4a81a84` — `contrib/miner/b3chain-gpuminer/` (24 files /
    3,376 lines).  Deprecated double-BLAKE3 GPU miner kept as
    historical reference.
- **In-house SECURITY-ROADMAP scaffolds (Group C, commit
  `1761ea3b5a`).**
  - **§3 Continuous benchmark CI** (`scaffold landed`).  New
    [`.github/workflows/benchmark.yml`](../.github/workflows/benchmark.yml)
    + [`contrib/testing/audit/audit-bench-trend.py`](../contrib/testing/audit/audit-bench-trend.py).
    Nightly + per-PR-on-hot-path job builds `bench_bitcoin` for HEAD
    and HEAD~1, runs the focused filter
    `B3PoW.*|CheckBlock.*|ConnectBlock.*`, fails the run on > 5%
    median regression, and publishes a markdown summary to the job
    page.
  - **§9 Continuous 51%-attack monitoring** (`script landed`).  New
    [`contrib/monitoring/51attack-watch.py`](../contrib/monitoring/51attack-watch.py)
    long-running daemon polls `getchaintips` /
    `getblockchaininfo` / `getnetworkhashps` every `--interval`
    seconds and emits structured JSONL alerts on (a) non-active
    tips at `branchlen >= 6`, (b) network hashps ≤ 50% of the
    100-block peak (height-keyed sliding window, immune to host
    clock-jumps), (c) reorgs reaching half of `max_reorg_depth`
    (M-4).  Includes an in-memory dedup window, RPC-down /
    webhook-5xx / detector-exception bypass paths, and an optional
    webhook for PagerDuty / Slack / generic JSON sinks.  Operator
    deployment guide:
    [`doc/security/51-MONITORING-OPS.md`](security/51-MONITORING-OPS.md).
    Tier-3-verified per
    [`.cursor/rules/tiered-verification.mdc`](../.cursor/rules/tiered-verification.mdc):
    every comment step has matching code, the polling loop is named,
    and every bypass / failure path is enumerated.
  - **§1 OSS-Fuzz onboarding** (`build scaffold ready`).  New
    [`contrib/oss-fuzz/b3chain/`](../contrib/oss-fuzz/b3chain/README.md)
    directory mirrors `google/oss-fuzz/projects/bitcoin-core/`
    layout (project.yaml, Dockerfile, build.sh, README.md) so the
    future PR enabling ClusterFuzz for b3chain is a drop-in copy.
- **CI fixes uncovered by the first cross-repo Linux run (Group D).**
  - `e944ee16cf` — `.github/workflows/b3miner-rtl.yml` path
    `../../../src/test/data/...` → `../../../../src/test/data/...`
    (one more `..` to reach the repo root from `contrib/miner/b3miner-rtl/ref/`).
    The fresh `b3miner-rtl` workflow now passes on Linux: F-1, F-4,
    and F-6 are all exercised end-to-end with no drift.
  - `5093846f61` — `.github/workflows/benchmark.yml` cmake flags
    `-DBUILD_WALLET=OFF` → `-DENABLE_WALLET=OFF`, add `-DENABLE_IPC=OFF`
    so the configure step does not require `libcapnp-dev` (not in
    the runner's apt-get list).

Documentation updates rolled in:
[`doc/SECURITY-ROADMAP.md`](SECURITY-ROADMAP.md) — status flips for
items 1 (`proposed (build scaffold ready)`), 3 (`in-progress (scaffold
landed)`), 9 (`in-progress (script landed)`), with relative-path
links to the landed scaffolds.
[`doc/SECURITY-AUDIT.md`](SECURITY-AUDIT.md) — new rows A-8 (benchmark
trend) and A-9 (51-attack monitoring).
[`contrib/miner/b3miner-rtl/CHANGELOG.md`](../contrib/miner/b3miner-rtl/CHANGELOG.md)
— note that the F-1 + F-4 fixes are now in tree (were authored in this
tree, never tracked until v1.1.2).

## v1.1.1 — B3PoW-Scratch 51%-attack mitigations

`SPEC_VERSION = 0x00010101` (algorithm), `REG_ID_MAGIC = 0xB3110002`
(RTL/firmware).  See
[`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](security/B3POW-51-ATTACK-ANALYSIS.md)
for the full threat model and
[`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](security/RESPONSE-RUNBOOK-51ATTACK.md)
for incident response.

### Algorithm-layer (F-1, F-4)

- **F-1 — ITER_MUL[7] distinct constant.** `ITER_MUL[7]` was a
  duplicate of `ITER_MUL[1]`; in lane 7 this collapsed the address
  derivation to a 7-lane mixer.  Replaced with a new wyhash-vetted
  64-bit constant `0x6E5C6F88AA5BDA77` in
  [`src/crypto/b3pow_scratch.cpp`](../src/crypto/b3pow_scratch.cpp),
  [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py),
  and [`contrib/miner/b3miner-rtl/rtl/params_pkg.sv`](../contrib/miner/b3miner-rtl/rtl/params_pkg.sv).
  Bumped `SPEC_VERSION` to `0x00010101` and `REG_ID_MAGIC` to
  `0xB3110002`.  All `b3pow_consensus_vectors.json` entries
  regenerated via `gen_vectors.py`.  This is a **pre-genesis** fix;
  no live network impact.
- **F-4 — Address uniformity test.** New
  [`contrib/miner/b3miner-rtl/ref/tests/test_address_uniformity.py`](../contrib/miner/b3miner-rtl/ref/tests/test_address_uniformity.py)
  runs a per-lane chi-squared test on the address derivation across
  2²⁰ samples per lane.  Wired into
  [`.github/workflows/b3miner-rtl.yml`](../.github/workflows/b3miner-rtl.yml)
  so any future RTL change to the address mixer cannot regress
  uniformity without CI catching it.  SPEC.md §8.F gives an informal
  2-round full-diffusion proof of the `LANE_SHUFFLE = (5L + 1) mod 8`
  permutation.

### Consensus layer (M-2, M-3, M-4, M-8, M-13, F-2, F-3, F-6)

- **M-2 / F-2 — BIP94 timewarp mitigation.** `consensus.enforce_BIP94 = true`
  on mainnet/testnet/signet (Bitcoin Core's default is mainnet-off).
  Caps the minimum timestamp at a difficulty boundary to
  `parent->nTime - 600s`.  Closes the Murch-Zawy timewarp attack
  vector V-3; quantified in [`audit-timewarp-sim.py`](../contrib/testing/audit/audit-timewarp-sim.py).
- **M-3 — LWMA-3 difficulty algorithm.** Bitcoin's 2016-block linear
  retarget is permanently replaced by **LWMA-3** (window=45,
  solve-time clamp at 6× target spacing / -target_spacing/6) on
  mainnet/testnet/signet.  Regtest retains the legacy retarget so
  the upstream functional tests keep passing.  New
  [`src/pow/lwma3.{h,cpp}`](../src/pow/lwma3.h);
  dispatch from [`src/pow.cpp`](../src/pow.cpp).
  Unit tests at [`src/test/lwma3_tests.cpp`](../src/test/lwma3_tests.cpp).
  Closes V-4 (LWMA-3 retargets every block, so a hashrate collapse
  recovers within ~45 blocks).
- **M-4 / F-3 — Reorg-depth cap.** `consensus.max_reorg_depth = 200`
  (~33 h at 600 s spacing).  Blocks proposing a reorg deeper than
  this below the active tip are rejected with new validation result
  `BlockValidationResult::BLOCK_DEEP_REORG`, routed to
  `Misbehaving("deep-reorg-attempt")` in `net_processing.cpp`.
  Bypassed during IBD and on regtest by explicit policy.
- **M-8 — Emergency-checkpoint stub** (OFF by default, ships with
  ZERO checkpoints).  New `-assumevalidcheckpoints=<path>` flag and
  module [`src/node/emergency_checkpoints.{h,cpp}`](../src/node/emergency_checkpoints.h).
  Loaded JSON `(height, hash)` entries reject any block with a
  mismatching hash at that height via new
  `BlockValidationResult::BLOCK_CHECKPOINT`.  Operational procedure
  is in [`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](security/RESPONSE-RUNBOOK-51ATTACK.md).
- **M-13 / F-6 — `powLimit` tightened 4× + post-bootstrap operating
  floor.** `consensus.powLimit` reduced from `0x1e01ffff` to
  `0x1d7fffff` on mainnet/testnet/signet/testnet4 (regtest unchanged).
  New `consensus.operating_pow_floor_bits = 0x1d3fffff` (2× stricter
  than `powLimit`) enforced by LWMA-3 once height past
  `nEarlyDifficultyGuardHeight`.  Defends F-6 by lifting the per-board
  minimum-difficulty solve time from ≈ 411 s to ≈ 1644 s under the
  consensus floor and ≈ 3290 s under the operating floor; collapses
  the F-6 exploit window to ≤ 1 block before LWMA-3 retargets upward.
  **Pre-genesis change** — all four production genesis blocks re-mined
  at the new floor (`b6cdeba0…`, `4b3f758b…`, `eb3fd63c…`,
  `d30df57f…`); contrib helpers
  [`mine_all_genesis.py`](../contrib/genesis/mine_all_genesis.py),
  [`gen_vectors.py`](../contrib/miner/b3miner-rtl/ref/gen_vectors.py)
  updated and re-run.  See
  [`src/kernel/chainparams.cpp`](../src/kernel/chainparams.cpp),
  [`src/pow/lwma3.cpp`](../src/pow/lwma3.cpp) step 5.

### Cache and verifier hardening (M-5, M-6, M-7, F-5)

- **M-6 / F-5 — 2-tier pinned LRU cache.**
  [`b3pow::Cache`](../src/crypto/b3pow_cache.h) gains a pinned tier
  (`kDefaultPinnedCapacity = 3`) so the tip + 2 ancestors cannot be
  evicted by hostile peer churn.  `consensus.b3pow_cache_depth`
  raised from 4 → 8 on mainnet/testnet/signet.
  `Chainstate::UpdateTip` calls `m_b3pow_cache.Pin(...)` whenever the
  active tip changes.  Audit:
  [`audit-b3pow-cache-pinning.py`](../contrib/testing/audit/audit-b3pow-cache-pinning.py)
  shows 0 tip evictions under a 10 000-header hostile flood (vs 1 250
  under the pre-fix LRU).
- **M-7 — Depth-asymmetric verifier budget.**
  `CheckBlockHeaderPoW(..., HeaderDepth)` scales the verifier budget
  by header depth below the active tip:
  - tip ±6 → full budget (50 ms mainnet)
  - 6 < depth ≤ 100 → 1⁄2 budget (25 ms mainnet)
  - depth > 100 → 1⁄5 budget (10 ms mainnet)
  Closes V-9 (CPU bleed via stale-fork header flood).
- **M-5 — Depth-aware ban score** in `net_processing.cpp` HEADERS
  handler: when the headers chain we just accepted is rooted ≥
  `max_reorg_depth` below the active tip, the peer is
  `Misbehaving("stale-tip-headers", gap=N cap=M)`.  Bypassed during
  IBD.

### Eclipse / Sybil hardening (M-9, M-10)

- **M-9 — `DEFAULT_MAX_PEER_CONNECTIONS` raised 125 → 200** on
  mainnet/testnet/signet.  See [`src/net.h`](../src/net.h).
- **M-10 — `-paranoid-headers-sync` (OFF by default)** with
  `-paranoid-headers-quorum=N` (default 3, clamped to [1, 16]):
  defers commit of any tip-extending header until N distinct peers
  have delivered the exact same final-header hash.  Defeats
  fabricated-header eclipse attacks.  See
  [`src/net_processing.{h,cpp}`](../src/net_processing.h),
  [`src/node/peerman_args.cpp`](../src/node/peerman_args.cpp).

### Simulators

New analysis simulators under [`contrib/testing/audit/`](../contrib/testing/audit/):

| Script | Audit row | Models |
|---|---|---|
| `audit-selfish-mining-sim.py` | A-2 | Eyal-Sirer (2014) selfish-mining state machine; threshold α* |
| `audit-timewarp-sim.py` | A-3 | Murch-Zawy timewarp on 2016-block retarget; BIP94 on/off |
| `audit-bootstrap-reorg-sim.py` | A-4 | Launch-phase reorg cost (capex/opex) at heights 100/500/1000/5000/10000 |
| `audit-cache-eviction-dos.py` | A-5 | Plain LRU vs 2-tier pinned LRU under hostile header flood |
| `audit-fpga-concentration-model.py` | A-6 | Gini coefficient of B3Miner-1 ownership at T+0/3/6/12 months |
| `audit-b3pow-cache-pinning.py` | A-7 | M-6 structural + behavioural verification |

`audit-51-attack-sim.py` (A-1) was extended to parameterise
`ATTACKER_LEAD` and `HONEST_CONFIRMATIONS`, and to emit cost tables
in CSV for `k ∈ [1, 12]` and `α ∈ [0.30, 0.60]`.

### Docs

- [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](security/B3POW-51-ATTACK-ANALYSIS.md)
  (new, ~13 k words) — full threat model.
- [`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](security/RESPONSE-RUNBOOK-51ATTACK.md)
  (new) — incident-response playbook.
- [`doc/SECURITY-AUDIT.md`](SECURITY-AUDIT.md) — audit rows A-2..A-7
  added.
- [`doc/SECURITY-INHERITANCE.md`](SECURITY-INHERITANCE.md) — BIP94,
  LWMA-3, and `max_reorg_depth` rows added.
- [`doc/SECURITY-ROADMAP.md`](SECURITY-ROADMAP.md) — items 4 and 7
  updated; new item 9 (continuous 51%-attack monitoring).

### Finding-to-fix-to-test map

(Mitigation IDs match `doc/security/B3POW-51-ATTACK-ANALYSIS.md` §1.2 M-1..M-13.)

| Finding | Severity | Fix (mitigation) | Test |
|---|---|---|---|
| **F-1** `ITER_MUL[1] == ITER_MUL[7]` | High (pre-genesis) | **M-1**: replace ITER_MUL[7] with `0x6E5C6F88AA5BDA77`; bump SPEC_VERSION → `0x00010101` and REG_ID_MAGIC → `0xB3110002` | `contrib/miner/b3miner-rtl/ref/tests/test_b3pow_ref.py` (23 PASS, including pairwise-distinct assertion); regenerated `src/test/data/b3pow_consensus_vectors.json` exercised by `b3pow_scratch_tests.cpp` |
| **F-2** `enforce_BIP94 = false` on mainnet | High | **M-2**: set `enforce_BIP94 = true` on mainnet/testnet/signet | `contrib/testing/audit/audit-timewarp-sim.py` (A-3 PASS, 10-window sweep); functional smoke `test/functional/feature_timewarp_bip94.py` |
| **F-3** No reorg-depth cap | High | **M-4**: `consensus.max_reorg_depth = 200`; new `BLOCK_DEEP_REORG` + `Misbehaving("deep-reorg-attempt")`; **M-5** depth-aware ban-score in HEADERS handler | `contrib/testing/audit/audit-bootstrap-reorg-sim.py` (A-4 PASS, 5/5 height scenarios); functional `test/functional/feature_reorg_depth_cap.py`; validation reject site `BLOCK_DEEP_REORG` in `src/validation.cpp::AcceptBlock` |
| **F-4** SPEC §8.E uniformity gate missing | Medium (pre-genesis) | **M-11** uniformity CI gate + **M-12** SPEC §8.F diffusion sketch | `contrib/miner/b3miner-rtl/ref/tests/test_address_uniformity.py` (1 PASS, 33 s, p > 1e-5 Bonferroni); wired in `.github/workflows/b3miner-rtl.yml` |
| **F-5** Cache evictable under hostile header flood | Medium | **M-6**: 2-tier pinned LRU (3 pinned slots); raise `b3pow_cache_depth` 4 → 8; pin tip + 2 ancestors on every `UpdateTip` | `src/test/b3pow_cache_tests.cpp` (4 new cases: `pin_protects_from_eviction`, `pin_capacity_overflow_demotes_oldest`, `pinned_capacity_clamped_below_depth`, `unpin_allows_eviction`); `contrib/testing/audit/audit-b3pow-cache-pinning.py` (A-7 PASS, 0 / 10 000 tip evictions); `contrib/testing/audit/audit-cache-eviction-dos.py` (A-5 PASS, 3/3 checks) |
| **F-6** `powLimit = 0x1e01ffff` (~10× wider than Bitcoin's) | Low–Medium | **M-13** (new): `consensus.powLimit` tightened 4× to `0x1d7fffff` on mainnet/testnet/signet/testnet4 (regtest unchanged); new `consensus.operating_pow_floor_bits = 0x1d3fffff` enforced by LWMA-3 once height > `nEarlyDifficultyGuardHeight` (a defence-in-depth post-bootstrap floor 2× stricter than `powLimit`). All four production genesis blocks re-mined at the new floor (pre-genesis, chain ID rolls). Continues to lean on **M-3** (LWMA-3 retargets every block) and **M-7** (depth-asymmetric verifier budget) for defence-in-depth. | `src/test/pow_tests.cpp::get_next_work_pow_limit` (updated expected_nbits) + new `operating_pow_floor_invariant`; `src/test/lwma3_tests.cpp` T7-T10 (`operating_pow_floor_steady_state`, `_disabled_in_bootstrap`, `_disabled_zero`, `_wider_than_powlimit_ignored`); `test/functional/feature_pow_floor.py` (smoke + bypass-path pin); `contrib/testing/audit/audit-bootstrap-reorg-sim.py` regenerated with `effective_floor_nbits` + per-board / honest min-diff solve time columns |

### Verifier budget (also added but not finding-driven)

| Mitigation | What it does | Test |
|---|---|---|
| **M-7** | `CheckBlockHeaderPoW(..., HeaderDepth)` scales the wall-clock budget by depth: Tip → 50 ms / 6 < depth ≤ 100 → 25 ms / depth > 100 → 10 ms.  Bounds the CPU bleed from V-9 (deep-fork header floods) | Extension of `src/test/pow_tests.cpp` `CheckBlockHeaderPoW_*` (existing budget tests cover the Tip case; depth-bucketing exercised via the dispatch from `validation.cpp::AcceptBlockHeader`) |
| **M-8** | `-assumevalidcheckpoints=<path>` JSON loader; binary ships ZERO checkpoints.  New `BlockValidationResult::BLOCK_CHECKPOINT` + `Misbehaving("checkpoint-mismatch")` | Structural: file is greppable in `src/node/emergency_checkpoints.{h,cpp}` and wired through `kernel/chainstatemanager_opts.h`.  Operational: `doc/security/RESPONSE-RUNBOOK-51ATTACK.md` §3.1 |
| **M-9** | `DEFAULT_MAX_PEER_CONNECTIONS` 125 → 200 | `src/net.h` (grep-only; default exposed to the existing connection-count tests) |
| **M-10** | `-paranoid-headers-sync` + `-paranoid-headers-quorum=N` (default 3, clamped \[1,16\]) | Argument parsing in `src/node/peerman_args.cpp`; the gate logic and observation table live in `src/net_processing.cpp::ProcessHeadersMessage` |

## v1.1 — B3PoW-Scratch consensus integration (in progress)

This release replaces the interim double-BLAKE3 PoW with **B3PoW-Scratch v1.1**
— a memory-hard BLAKE3 variant with a 1 MB scratchpad, 8 lanes, 2048
iterations, and a 50 ms verifier wall-clock budget. Block IDs (`GetHash()`)
remain SHA-256d; only PoW validation moves to B3PoW.

### Algorithm
- **Spec**: [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md) (`SPEC_VERSION=0x00010100`).
- **Reference**: [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py)
  is the byte-for-byte oracle; the C++ port at
  [`src/crypto/b3pow_scratch.{h,cpp}`](../src/crypto/) is required to agree.
- **Consensus vectors**: `src/test/data/b3pow_consensus_vectors.json`
  (regenerated by `contrib/miner/b3miner-rtl/ref/gen_vectors.py`).

### C++ changes
- **`CBlockHeader::GetPoWHash()`** now takes `(prev_block_hash, pad, budget,
  out_budget_exceeded)` and returns `std::optional<uint256>`; double-BLAKE3
  body removed.
- **`PoWResult`** enum (`Pass`, `Fail`, `BudgetExceeded`) and
  **`CheckBlockHeaderPoW()`** in `src/pow.{h,cpp}` consolidate
  pre-check → cache lookup → hash → target compare → result mapping.
- **`Consensus::Params`** gains `b3pow_verify_budget_ms` (50 ms mainnet /
  testnet, 1000 ms regtest) and `b3pow_cache_depth` (4 mainnet / testnet,
  1 regtest).
- **`b3pow::Cache`** (`src/crypto/b3pow_cache.{h,cpp}`) is an LRU
  scratchpad cache keyed by `prev_block_hash`, owned by
  `ChainstateManager::m_b3pow_cache`, shared-mutex protected.
- **`CheckBlockHeader` / `CheckBlock`** now take `prev_block_hash` and a
  `b3pow::Cache&`; `BlockValidationResult::BLOCK_POW_BUDGET` is a new
  validation result.

### DoS mitigations (Finding 4)
- **Pre-check + peer scoring**: nBits range is checked before any B3PoW
  hashing.  `BLOCK_POW_BUDGET` results route to
  `Misbehaving("b3pow-budget-exceeded")` in `net_processing.cpp`.
- **Per-`prev_block_hash` scratchpad cache** (depth 4) so miners and
  verifiers don't repay the ~5 ms pad-init cost on every nonce/header
  sharing a parent.
- **Headers-sync depth cap**: full B3PoW is deferred during presync;
  `MAX_B3POW_VERIFY_PER_BATCH=256` caps B3PoW CPU per `HEADERS` message,
  preventing a malicious peer from forcing 12.8 s of CPU in one batch.

### Disk-load path
- `LoadBlockIndexDB` and `ReadBlock` now do a cheap `DeriveTarget`
  (nBits range) check instead of full B3PoW. Re-running B3PoW on every
  block on startup would add ~5 minutes per 10k blocks; the local disk
  is already a trusted source.

### Tests
- `src/test/b3pow_scratch_tests.cpp` — vector parity against the Python
  reference; cache+oneshot agreement; nontrivial-prev sensitivity.
- `src/test/b3pow_cache_tests.cpp` — LRU correctness, eviction policy,
  thread-safety under concurrent access.
- `src/test/pow_tests.cpp` — extended with
  `CheckBlockHeaderPoW_budget_exceeded` and the new `GetPoWHash`
  signature; old `pow_hash_uses_blake3` test renamed to
  `pow_hash_uses_b3pow_scratch`.
- `src/test/crypto_tests.cpp` — `blake3_dual_hash_design` rewritten as
  `b3pow_dual_hash_design`; `blake3_rejects_sha256d_nonce` →
  `b3pow_rejects_sha256d_nonce` (reuses a pad across nonces to stay fast).
- `src/test/fuzz/pow.cpp` — new `b3pow_random_header` target exercising
  the hash, cache, and budget paths.
- `test/functional/feature_b3pow.py` — regtest mine-5-blocks + bad-nonce
  rejection + P2P header-spam scoring.
- `contrib/miner/b3miner-rtl/ref/tests/test_consensus_vectors.py` —
  schema lock for `consensus_vectors.json`.

### Memory footprint
- The cache adds **4 MB RSS** on mainnet/testnet (4 × 1 MB pads); see
  [`reduce-memory.md`](reduce-memory.md) for the knob.

## Status Summary

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Environment and Build Baseline | **COMPLETE** |
| Phase 1 | Chain Identity (Network Isolation) | **COMPLETE** |
| Phase 2 | PoW Replacement (SHA-256d -> B3PoW-Scratch v1.1; superseded the interim double-BLAKE3-256 swap) | **COMPLETE** |
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
  - **Stratum V1 pool mode (added 2026-05-15)**: `--stratum URL`,
    `--user`, `--pass` connect to the b3chain pool at port 3333. Each
    `mining.submit` is preceded by a comprehensive byte-level dump
    (job id, both extranonces, ntime, nonce, full coinbase tx,
    coinbase txid, merkle root, 80-byte header, PoW hash LE+BE, block
    hash, share target/difficulty, network target/difficulty,
    `is_block?`, server response, RTT) so pool implementers can
    cross-check share-validation byte-for-byte. Optional `--json-log`
    writes the same data plus connect/subscribed/notify/progress/
    disconnect/summary events as one JSON object per line.
    `--progress-interval` emits per-thread "best-hash-so-far"
    progress between shares. Solo mode is unchanged. End-to-end
    integration test at `contrib/miner/test_pool_miner.py` spins up a
    mock pool, runs the real miner, and verifies every recorded share
    by recomputing `BLAKE3(BLAKE3(header))` from the JSONL.
  - **Windows test UI (added 2026-05-16)**: PyQt6 application at
    `contrib/miner/tests/` (entry point
    `contrib/miner/tests/run_tests_ui.bat`) runs the full miner test
    suite with one click. Auto-detects `b3chaind`, `b3chain-cli`,
    `docker`, `npm`, internet, and `pool.b3chain.org` reachability;
    greys out tests whose prerequisites are missing. Includes nine
    tests (env check, helper unit asserts, argparse mutex,
    `--benchmark`, mock-pool E2E, JSONL re-derive, solo regtest, live
    pool reachability, and an opt-in local Docker pool stack), live
    streams every test's stdout to a monospace pane, and writes
    `report-*.json` + `report-*.md` on Save Report. The launcher
    bootstraps a private venv on first run; subsequent launches are
    instant.
  - **Live mining dashboard (added 2026-05-16)**: a separate window
    launched from a **Mine** toolbar button in the test UI. Drives
    `b3chain-cpuminer.py` against any Stratum V1 pool with
    `--json-log <tmp>`, parses the JSONL via a stateful tail reader
    (`mining_parsers.py`, with offset + partial-line buffer), and
    shows: a rolling 5-minute hashrate polyline chart (custom QWidget,
    no extra deps), big-number stats cards (current hashrate,
    submitted / accepted / rejected, attempts, blocks), a per-thread
    table (rate / attempts / best PoW BE), the last 200 shares, a
    last-share details panel (job, ntime, nonce, extranonces, PoW LE/BE,
    share + network targets, RTT, error), live status banner, and Raw
    stdout + JSONL events tabs. **Save Session** writes
    `mining-session-YYYYMMDD-HHMMSS/` containing `miner-stdout.log`,
    `shares.jsonl`, `session-summary.json`, and `session-summary.md`.
    Last-used pool URL / user / threads / useragent persist in
    `tests/.miner_settings.json` (gitignored). Closing the dashboard
    mid-mine cleanly terminates the miner subprocess.     Tier-3
    verification at `tests/verify_dashboard.py` exercises the JSONLTail
    (offset, partial-line, garbage, truncation), drives the runner
    against the in-process `MockStratumServer`, and checks the
    `closeEvent` cleanup path.
  - **Stable hashrate display (fix 2026-05-16)**: rebuilt
    `pool_mining_worker`'s rate emission so the per-thread `progress.
    hashrate` field is the instantaneous Δattempts/Δt over the
    inter-emit window (>=1s wall-clock cadence; attempt-count tick
    requires >=0.2s window) using cumulative counters that span
    `clean_jobs` outer-pass resets. Previously rate was
    `attempts_for_job / outer_elapsed`, an average over the current
    outer pass; with B3Chain pool sending `clean_jobs=true` on every
    notify (~2s cadence) the average snapshot was dominated by the
    first 100k attempts of each pass, so the same thread reported wild
    swings (e.g. 28 -> 318 -> 71 -> 226 kH/s within seconds). The
    dashboard's `HashrateRing.current_rate()` now also averages the
    aggregate over a short 5s window so per-thread emit-timing jitter
    doesn't ripple the big-stat card. Per-thread coefficient of
    variation under steady state dropped from ~0.7 to ~0.10.
  - **Stale-job breakout (fix 2026-05-16)**: the inner nonce loop's
    `clean_epoch` check now fires every iteration instead of every
    1024 nonces. The 1024-aligned check assumed every worker stayed
    near peak throughput; in practice GIL-starved workers (e.g. 30
    Python threads on a 16-core box) can drop to ~1 attempt/sec, so
    the next 1024-aligned check is up to ~17 minutes away and the
    thread keeps mining a stale job long after the pool sent
    `clean_jobs=true`. Per-iteration check cost is ~50 ns
    (one int read + compare), negligible vs the ~1 us BLAKE3
    double-hash. After the new instantaneous rate display this issue
    became visible as workers reporting `1 H/s` on a job several
    notifies in the past; with the breakout fixed those workers
    re-snapshot the current job within a single hash.
  - **Per-pass rate baseline reset (fix 2026-05-16)**: after the
    stale-job-breakout fix, GIL-starved workers still emitted
    `attempts=1 rate=1 H/s` once per `clean_jobs=true` notify. Cause:
    the cumulative-counter rate window stretched across the OLD
    pass's tail + outer-loop bookkeeping (state_lock contention,
    coinbase build, merkle compute) + the NEW pass's start. Under
    heavy GIL contention the inner loop barely ran in that window, so
    the very first emit in the new pass measured ~1 hash over ~1s of
    wall time. Each transition produced a burst of ~14 such emits
    that dragged the dashboard's smoothed total down by ~20% per
    notify. Fix: on every outer-pass entry, flush leftover
    cum_attempts to `state.total_attempts` (so global throughput
    stays accurate) and reset `last_progress_at` and
    `cum_at_last_emit`. The first emit in each new pass now measures
    inner-loop hashing within that pass only; cumulative state stats
    still reflect true wall-clock throughput.
  - **Lower default thread count (fix 2026-05-16)**: the live mining
    dashboard's `Threads` default dropped from `os.cpu_count() - 1`
    (which over-subscribes hyperthreaded boxes -- e.g. 31 threads on
    a 16C/32T CPU) to `os.cpu_count() // 2` (~physical core count on
    every Intel/AMD SMT desktop SKU since Nehalem). Each Python
    worker holds the GIL for the per-iteration overhead and only
    releases it during the BLAKE3 C call, so scheduling more workers
    than physical cores starves half of them and lowers the aggregate
    hashrate. The spinbox tooltip now explains this. Existing users
    can override via the spinbox; the value persists in
    `tests/.miner_settings.json`.
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

### Phase 6.4: NVIDIA CUDA GPU miner (added 2026-05-16)

Standalone Rust crate at `contrib/miner/b3chain-gpuminer/` that ports
the Python miner's hot path to CUDA. Targets a 200-500x speedup over
the Python reference (~6 MH/s -> 1-3 GH/s on midrange RTX) so the
testnet pool actually exercises real share-difficulty traffic without
needing dozens of CPU machines.

Architecture:

- **Stratum V1 client** (`src/stratum/`): direct port of
  `b3chain-cpuminer.py` 's `StratumPoolClient` to async tokio. Same
  newline-delimited JSON framing, same `clean_epoch` semantics, same
  reconnect/backoff behaviour. The mock server from
  `contrib/miner/test_pool_miner.py` is ported to a Rust integration
  test so the new client passes the same handshake scenarios.
- **CUDA kernel** (`kernels/blake3.cuh` + `kernels/miner.cu`): a
  ~250-line implementation of the BLAKE3 compression function with
  the chunk-tree / parent-node code paths stripped (both hashes are
  <=1024 bytes, single-chunk, ROOT-on-last-block). One thread per
  candidate nonce; thread patches its nonce into a copy of the
  80-byte header template, double-hashes, compares to share target
  little-endian, and atomicAdds into a small results buffer on hit.
- **GPU driver** (`src/gpu/driver.rs`): owns the device, the
  persistent buffers (header template, share target, results), and
  one extranonce2 counter. Pulls `MiningState` snapshots from a
  `tokio::sync::watch`, builds the coinbase + merkle root + 80-byte
  header on the host, dispatches 16M-nonce batches to the kernel,
  drains candidates into the Stratum client's submit channel.
- **JSONL log schema parity**: emits the same
  `connect`/`subscribed`/`authorized`/`set_difficulty`/`notify`/
  `progress`/`share_pre_submit`/`share_submit`/`submit_response`
  events as the Python miner so the live dashboard at
  `contrib/miner/tests/mining_dashboard.py` ingests the GPU miner's
  output unchanged.
- **Dashboard backend selector**: a new `Backend: CPU / GPU` combo
  in `mining_dashboard.py` chooses which binary to spawn. The GPU
  option auto-detects the built `b3chain-gpuminer` binary under
  `target/release/` (or `target/debug/` for development) and surfaces
  a clear "build the binary first" error if it's not present. The
  `Threads` spinbox is auto-disabled when GPU is selected since the
  GPU backend uses a single dispatcher task.
- **Phase-A correctness gate**: `tests/kernel_correctness.rs`
  generates 100k random 80-byte headers, hashes each on the host
  with the `blake3` crate and on the GPU with `double_blake3_dump`,
  asserts bytewise equality. This is the *primary* defence against
  the most insidious GPU-miner failure mode (a BLAKE3 endianness or
  constant mismatch that produces hashes the pool rejects 100% of).
  It must pass before any pool traffic happens.
- **Phase-B integration test**: `tests/stratum_handshake.rs` runs an
  in-process mock server that drives the client through subscribe ->
  authorize -> set_difficulty -> notify and asserts the watch-channel
  state landed correctly. No GPU required, runs on every dev box.

Build prerequisites (documented in `contrib/miner/b3chain-gpuminer/README.md`):
NVIDIA driver >= 535, CUDA Toolkit 12.x, MSVC 2022 Build Tools on
Windows, Rust stable 1.75+. The `cudarc` crate uses the runtime CUDA
driver API so the produced binary doesn't statically depend on
`nvcuda.dll` and ships across machines with just an NVIDIA driver.

Out of scope for v0.1 (deferred to a follow-up): multi-stream
pipelining, multi-GPU, AMD/Intel support, Stratum V2, TLS endpoints,
auto-tuning per compute capability.

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
- `contrib/testnet/electrs/install.sh` (new) stages
  [romanz/electrs](https://github.com/romanz/electrs) v0.10.6 (Rust
  toolchain + librocksdb-sys build deps + dedicated `electrs` system
  user in the `b3chain` group + systemd unit `electrs-testnet.service`
  on `127.0.0.1:50001`). The service is installed STOPPED+DISABLED
  pending an upstream fix or a local patch — see "electrs
  incompatibility" below — and is re-enabled by re-running the
  installer with `--enable`. A `tmpfiles.d` snippet keeps `blk*.dat`
  files group-readable across b3chaind restarts so a future indexer
  doesn't lose access to newly-created block files.
- `contrib/testnet/explorer/install.sh`: copies the two new overlay
  pug files into upstream's `views/`. `BTCEXP_PRIVACY_MODE` is
  flipped from `true` to `false` so the upstream address view renders
  the encoding-badge + QR section (both are gated on `!privacyMode`).
  `BTCEXP_ADDRESS_API` is deliberately left unset (see below).
- `contrib/testnet/explorer/overlay/public/css/b3-theme.css`: appends
  `b3-tx-*`, `b3-addr-*`, plus shared `b3-tag` and `b3-callout`
  building blocks. New layout primitives: stat-card grid (4 columns,
  collapses to 2 on `≤900px`), io grid (`1fr 48px 1fr` with arrow
  rotated to vertical on mobile), hero with right-aligned QR (drops
  below address on mobile), accordion built on native `<details>` so
  no JavaScript needed.

#### electrs incompatibility — root cause + path forward

While wiring up `romanz/electrs` v0.10.6 as the address indexer, two
escape hatches were enough to clear the network handshake (`network =
"signet"` + `signet_magic = "b3c1020e"` overrides the hardcoded
testnet magic, and `daemon_p2p_addr = "127.0.0.1:18533"` overrides
the testnet default p2p port). But the *third* hardcoded assumption
— the signet genesis block hash, pinned in `bitcoin-rs` and consumed
by electrs's chain-sync walk — cannot be overridden by config; it
fails with `missing prev_blockhash <b3chain-genesis>` the moment
electrs reaches the bottom of the chain.

Three viable next steps, in order of cost:

1. Patch electrs to accept `genesis_hash` from the toml config and
   plumb it through `Daemon::new()` + the index-walk validator.
   ~20 lines of Rust against `v0.10.6`. Maintained as a small fork
   under `b3chain/electrs` and pinned in the installer.
2. Replace electrs with an in-process address indexer in the
   explorer overlay (extend `b3-daily-aggregator.js`'s tip-poll loop
   to walk all `vin`/`vout` scriptPubKeys and persist an
   address→txid map). No external dependency, no fork to maintain,
   but ~300 LoC of new code.
3. Wait until a `bitcoin-rs` release exposes per-network genesis
   overrides upstream and electrs picks it up.

#### electrs fix landed — b3chain/electrs v0.10.6-b3chain-1

Path #1 above is now done. The b3chain/electrs fork
(<https://github.com/b3chain/electrs>) ships tag `v0.10.6-b3chain-1`,
which fetches the genesis block header from the connected daemon at
startup instead of asking `bitcoin-rs` for the network ident's
hardcoded one:

- `src/daemon.rs`: new `Daemon::get_genesis_header()` calls
  `getblockhash 0` + `getblockheader` on the daemon RPC.
- `src/chain.rs`: `Chain::new(network, genesis_header: Option<Header>)`
  uses the daemon-supplied header when `Some(...)`, falling back to
  the bitcoin-rs constant when `None` (so upstream tests still pass).
- `src/tracker.rs`: `Tracker::new` takes a `&Daemon` and feeds its
  `get_genesis_header()` result into `Chain::new`.
- `src/electrum.rs`: `Rpc::new` is reordered so the daemon is
  connected before the tracker is built (the tracker needs the daemon
  handle now).

`contrib/testnet/electrs/install.sh` repoints `ELECTRS_REPO` at the
fork and pins `ELECTRS_TAG=v0.10.6-b3chain-1`. The installer also
stashes the installed tag in `$ELECTRS_DIR/.installed-tag` (since the
fork keeps the upstream Cargo.toml version string) and wipes the
RocksDB on tag change so the new genesis takes effect on re-index.
`contrib/testnet/explorer/install.sh` re-enables
`BTCEXP_ADDRESS_API=electrum` + `BTCEXP_ELECTRUM_SERVERS=tcp://127.0.0.1:50001`.
The `--enable` flag is kept on the electrs installer for staged
rollouts; the address.pug "Address indexer not configured" branch
stays as a defensive fallback for the case where electrs is
intentionally stopped.

The "indexer not yet available" callout is now only reachable by
operator action (stopping electrs), not by upstream-incompat.

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
