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
  - BLAKE3 test vectors
  - `getblocktemplate` workflow
  - Stratum protocol notes for pool implementers
  - Network port reference
- **PoW design document**: `doc/b3chain-pow-design.md`
  - Dual-hash architecture rationale
  - SIMD acceleration details
  - Security considerations

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
- `contrib/testnet/explorer/` — `btc-rpc-explorer` Docker installer
  pointed at the local RPC.
- `contrib/testnet/monitor/`  — cron-driven seed status snapshot
  exported as `/testnet-status.txt`.

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
- Faucet (when DNS lands): <https://faucet.b3chain.org>
- Block explorer (when DNS lands): <https://explorer.b3chain.org>

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
  mining.md                   # Mining and stratum documentation
  CHANGELOG.md                # This file

src/crypto/blake3/            # Vendored BLAKE3 library (C + x86-64 ASM)
```
