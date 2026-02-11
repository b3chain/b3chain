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
| Phase 8 | Deployment and Launch | Pending |
| Phase 9 | Wallets, CLI, and API | Inherited from Bitcoin Core |
| Phase 10 | Maintenance and Upgrades | Ongoing |
| Phase 11 | Security | Pre-launch audit pending |

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
