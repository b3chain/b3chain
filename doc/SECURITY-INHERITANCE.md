# Bitcoin Security Inheritance

B3Chain is forked from Bitcoin Core 30.2.0. Every security property that
Bitcoin proves with its own test corpus is **inherited by construction** —
unless we changed the underlying code. This document is the inventory:

1. For each Bitcoin invariant, which upstream test proves it.
2. Whether B3Chain still passes that test (`inherited`), passes a renamed
   version (`inherited-with-rebrand`), is deliberately different
   (`diverged-by-design` — covered by a B3Chain-specific test), or has not
   yet been verified (`pending`).
3. The verifier:
   [`contrib/testing/audit/audit-bitcoin-inheritance.sh`](../contrib/testing/audit/audit-bitcoin-inheritance.sh)
   runs the full upstream suite and writes the results back into the table.

## Status legend

- `inherited` — Bitcoin's test passes unmodified on B3Chain.
- `inherited-with-rebrand` — Bitcoin's test passes after string rebranding
  (`bitcoind` → `b3chaind`, `bc1` → `b3` HRP, etc.) but the underlying
  invariant is unchanged.
- `diverged-by-design` — B3Chain intentionally differs (e.g. PoW algorithm,
  address HRP, BIP44 coin_type). A B3Chain-specific test covers the new
  behaviour and is named in the **B3Chain test** column.
- `failing-investigation` — the upstream test fails on B3Chain and we don't
  yet know whether it's a real regression or an expected divergence.
- `pending` — verifier hasn't run yet on this row.

## Why this exists

The original Phase 11 audit ([`SECURITY-AUDIT.md`](SECURITY-AUDIT.md)) covers
**B3Chain-specific** invariants: the B3PoW-Scratch v1.1 PoW swap (which
replaced an interim double-BLAKE3 swap as of v1.1), the rebranded address
prefix, the coin_type 9333, the 51% attack. It does **not** check that we
left Bitcoin's other security properties intact.

**Note on the PoW swap**: B3Chain replaces Bitcoin's SHA-256d PoW with
**B3PoW-Scratch v1.1** -- a memory-hard BLAKE3 variant with a 1 MB
scratchpad, 8 lanes, 2048 iterations, and a 50 ms wall-clock verifier
budget (`Consensus::Params::b3pow_verify_budget_ms`).  Block IDs (the
hash returned by `GetHash()` and `getblockhash`) remain SHA-256d --
only PoW validation uses B3PoW.  The authoritative spec lives in
[`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md),
the byte-for-byte reference is
[`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py),
and the C++ port is [`src/crypto/b3pow_scratch.{h,cpp}`](../src/crypto/).
Consensus parity between the two is enforced by
[`src/test/b3pow_scratch_tests.cpp`](../src/test/b3pow_scratch_tests.cpp)
against the JSON vector set in `src/test/data/b3pow_consensus_vectors.json`.

This document closes that gap. Every property below is one Bitcoin already
proves; the question is "do we still prove it?". The answer for almost every
row should be `inherited` — and when it isn't, we need a written reason.

## How to verify

```bash
# 1. Build B3Chain Core (Bitcoin Core's full test suite ships with us).
cmake -B build && cmake --build build -j$(nproc)

# 2. Run the inheritance audit. Times out if the upstream suite hangs.
bash contrib/testing/audit/audit-bitcoin-inheritance.sh

# 3. The script:
#    - runs the full ctest unit suite
#    - runs the full functional suite (test_runner.py --extended)
#    - classifies every result against the expected-divergence allowlist
#    - rewrites the status column of this file
#    - exits non-zero if any "should be inherited" test fails
```

Last full run: **2026-05-19 13:14** (144 PASS, 0 diverged, 0 FAIL, 0 SKIP)

---

## Consensus & block validation

| Bitcoin invariant | Upstream test | B3Chain status | B3Chain test | Notes |
|---|---|---|---|---|
| Block subsidy halving schedule | `feature_block.py` | `inherited` | `audit-supply-cap.py`, `consensus_invariants_tests::audit_subsidy_*` | Halving interval unchanged at 210 000. |
| 21M total supply cap | analytic + `feature_block.py` | `inherited` | `audit-supply-cap.py` C-2 | Cap is `2 099 999 997 690 000` sat. |
| Subsidy returns 0 after halving 64 (UB guard) | `validation_tests.cpp` | `inherited` | `consensus_invariants_tests::audit_subsidy_*` | Guards against `x >> 64` UB. |
| Difficulty retarget enforces 4× bounds | `pow_tests.cpp::CalculateNextWorkRequired` | `diverged-by-design` | `lwma3_tests.cpp`, `feature_lwma3.py`, `audit-supply-cap.py` C-4 | b3chain M-3: Bitcoin's 2016-block linear retarget is replaced by **LWMA-3** (window=60, solve-time clamp +6×spacing / −5×spacing). Why LWMA-3 not LWMA-1: [`B3POW-51-ATTACK-ANALYSIS.md` §2.1](security/B3POW-51-ATTACK-ANALYSIS.md#21-m-3-design-note-why-lwma-3-not-lwma-1). See [`src/pow/lwma3.{h,cpp}`](../src/pow/) and V-4. Regtest retains the legacy retarget for functional-test compatibility. |
| `consensus.powLimit` floor + post-bootstrap operating floor | `pow_tests.cpp::get_next_work_pow_limit` | `diverged-by-design` | `pow_tests.cpp::operating_pow_floor_invariant`, `lwma3_tests.cpp` T7-T10, `feature_pow_floor.py`, `audit-bootstrap-reorg-sim.py` | b3chain M-13 (F-6 fix): consensus floor tightened 4× from the original `0x1e01ffff` to `0x1d7fffff` (still wider than Bitcoin's `0x1d00ffff` because B3PoW-Scratch targets a smaller miner base, but no longer ≈10× wider).  Adds a stricter post-bootstrap **operating floor** `0x1d3fffff` enforced by LWMA-3 once height > `nEarlyDifficultyGuardHeight`.  Closes the F-6 min-difficulty exploit window.  See [`src/pow/lwma3.cpp`](../src/pow/lwma3.cpp) step 5 and `B3POW-51-ATTACK-ANALYSIS.md` V-5 / F-6. |
| Timewarp attack mitigation (BIP94 block-storm rule) | `feature_block_storm.py`, upstream `enforce_BIP94` | `diverged-by-design` (matches upstream) | `audit-timewarp-sim.py`, `feature_timewarp_bip94.py` | b3chain F-2 fix (M-2): `enforce_BIP94 = true` on **mainnet/testnet/signet** (Bitcoin Core's default is mainnet-off, testnet-on). Caps the minimum timestamp at a difficulty boundary to the parent's `nTime - 600s`. See `B3POW-51-ATTACK-ANALYSIS.md` V-3. |
| Reorg depth cap (consensus-enforced max_reorg_depth) | n/a (Bitcoin has no equivalent) | `diverged-by-design` (new) | `feature_reorg_depth_cap.py`, validation rejection `BlockValidationResult::BLOCK_DEEP_REORG` | b3chain M-4 / F-3: `consensus.max_reorg_depth = 200` (≈ 33 h at 600 s).  Blocks proposing a reorg deeper than this below the active tip are rejected with `Misbehaving("deep-reorg-attempt")`.  Bypassed during IBD / assumevalid / regtest.  See `B3POW-51-ATTACK-ANALYSIS.md` V-5. |
| Median-time-past rule | `feature_block.py` | `inherited` | — | Unchanged. |
| Coinbase maturity (100 blocks) | `feature_block.py` | `inherited` | — | Unchanged. |
| Block weight / sigops limits | `feature_block.py`, `feature_segwit.py` | `inherited` | — | Unchanged. |
| BIP30 (duplicate coinbase ban) | `feature_bip68_sequence.py` | `inherited` | — | |
| BIP34 (height in coinbase) | `feature_csv_activation.py` | `inherited` | — | |
| BIP65 (CLTV) | `feature_cltv.py` | `inherited` | — | |
| BIP66 (strict DER) | `feature_dersig.py` | `inherited` | — | |
| BIP68/112/113 (CSV) | `feature_csv_activation.py`, `feature_bip68_sequence.py` | `inherited` | — | |
| BIP141/143/147 (SegWit) | `feature_segwit.py`, `feature_nulldummy.py` | `inherited` | — | |
| BIP341/342 (Taproot) | `feature_taproot.py` | `inherited` | — | |
| Assume-valid block validation | `feature_assumevalid.py` | `inherited` | — | |
| `assumeutxo` snapshot loading | `feature_assumeutxo.py` | `pending` | — | Snapshots are Bitcoin-mainnet UTXO commitments; not yet generated for B3Chain. Expected `diverged-by-design` once verifier runs. |

## Hash function & PoW

| Bitcoin invariant | Upstream test | B3Chain status | B3Chain test | Notes |
|---|---|---|---|---|
| SHA-256 correctness (FIPS 180-4 vectors) | `crypto_tests.cpp::sha256_*` | `inherited` | — | Still used for block ID / txid / merkle. |
| SHA-256d correctness | `crypto_tests.cpp::sha256d_*` | `inherited` | — | Block ID + txid construction unchanged. |
| HMAC-SHA-256 / -512 | `crypto_tests.cpp::hmac_*` | `inherited` | — | Used by BIP32 derivation and BIP39 seeds. |
| RIPEMD-160 | `crypto_tests.cpp::ripemd160_*` | `inherited` | — | Address hashing unchanged. |
| **PoW algorithm (SHA-256d for nonce)** | `pow_tests.cpp::*difficulty*` | **`diverged-by-design`** | `audit-pow-isolation.py`, `b3pow_scratch_tests.cpp`, `b3pow_cache_tests.cpp`, `feature_b3pow.py` | Replaced with **B3PoW-Scratch v1.1** -- memory-hard BLAKE3 variant with a 1 MB scratchpad and 50 ms verifier budget; see [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md). |
| BLAKE3 hashing (no upstream Bitcoin equivalent) | n/a | `diverged-by-design` (new) | `audit-simd-blake3.py` (B-1) | SIMD-vs-portable differential test. |
| **B3PoW verifier budget enforcement (DoS mitigation)** | n/a | `diverged-by-design` (new) | `pow_tests::CheckBlockHeaderPoW_budget_exceeded`, `b3pow_cache_tests.cpp` | Headers that exceed `b3pow_verify_budget_ms` return `BLOCK_POW_BUDGET` and trigger `Misbehaving("b3pow-budget-exceeded")` for the offending peer; headers-sync caps full B3PoW verification at `MAX_B3POW_VERIFY_PER_BATCH=256` per `HEADERS` message. |
| `getblockhash` returns SHA-256d | `rpc_tests.cpp` | `inherited` | — | Block ID hash unchanged; only the PoW hash differs. |

## Script & transaction

| Bitcoin invariant | Upstream test | B3Chain status | B3Chain test | Notes |
|---|---|---|---|---|
| Script verification — P2PK / P2PKH | `script_tests.cpp` | `inherited` | — | |
| Script verification — P2SH | `script_p2sh_tests.cpp` | `inherited` | — | |
| Script verification — SegWit v0 | `script_segwit_tests.cpp` | `inherited` | — | |
| Script verification — Taproot v1 | `feature_taproot.py` | `inherited` | — | |
| Standardness rules | `script_standard_tests.cpp` | `inherited` | — | |
| Sigop counting | `sigopcount_tests.cpp` | `inherited` | — | |
| Sighash computation | `sighash_tests.cpp` | `inherited` | — | |
| Schnorr signatures | `script_assets_tests.cpp` | `inherited` | — | |
| Miniscript parsing | `miniscript_tests.cpp` | `inherited` | — | |

## Mempool & policy

| Bitcoin invariant | Upstream test | B3Chain status | B3Chain test | Notes |
|---|---|---|---|---|
| Mempool ordering & eviction | `mempool_tests.cpp` | `inherited` | — | |
| RBF (BIP125 + full-RBF) | `feature_rbf.py` | `inherited` | — | |
| Package validation | `txpackage_tests.cpp` | `inherited` | — | |
| Ancestor / descendant limits | `mempool_tests.cpp` | `inherited` | — | |
| Fee estimation | `policy_fee_tests.cpp`, `feature_fee_estimation.py` | `inherited` | — | |
| Min relay fee floor | `policyestimator_tests.cpp` | `inherited` | — | |
| Coin selection (`bnb`, `srd`) | `wallet_*` tests | `inherited` | — | |

## P2P network

| Bitcoin invariant | Upstream test | B3Chain status | B3Chain test | Notes |
|---|---|---|---|---|
| BIP155 addrv2 | `feature_addrman.py` | `inherited` | — | |
| BIP324 v2 transport | `bip324_tests.cpp` | `inherited` | — | |
| Peer eviction logic | `net_peer_eviction_tests.cpp` | `inherited` | — | |
| DoS scoring | `denialofservice_tests.cpp` | `inherited` | — | |
| Header sync chainwork limits | `headers_sync_chainwork_tests.cpp` | `inherited` | — | |
| Tor (onion) connectivity | `feature_proxy.py` | `inherited` | — | |
| I2P connectivity | `i2p_tests.cpp` | `inherited` | — | |
| **Network magic bytes** | n/a (constant) | **`diverged-by-design`** | `audit-network-isolation.py` (N-1) | Bitcoin's `f9beb4d9` is rejected at handshake. |
| **DNS seed list** | n/a (constant) | **`diverged-by-design`** | `audit-network-isolation.py` (N-1) | Bitcoin seeds removed; B3Chain seeds (when set) are isolated. |

## Wallet

| Bitcoin invariant | Upstream test | B3Chain status | B3Chain test | Notes |
|---|---|---|---|---|
| BIP32 derivation | `bip32_tests.cpp` | `inherited` | — | Algorithm unchanged. |
| BIP39 mnemonic seed (3rd party convention) | `wallet_keypool*` | `inherited` | — | |
| **BIP44 coin_type** | `bip32_tests.cpp` | **`diverged-by-design`** | `audit-hd-coin-type.py` (W-2) | `9333` (mainnet) instead of Bitcoin's `0`. |
| Descriptor wallet | `descriptor_tests.cpp` | `inherited` | — | |
| PSBT (BIP174) round-trip | `psbt_*` functional tests | `inherited` | — | Format unchanged. |
| Watch-only / multisig | `multisig_tests.cpp` | `inherited` | — | |
| Hardware-wallet external signer | `feature_external_signer*` | `inherited` | — | |
| BDB legacy wallet read | various | `pending` | — | Likely `diverged-by-design` if BDB isn't compiled in; verifier will report. |

## Address format

| Bitcoin invariant | Upstream test | B3Chain status | B3Chain test | Notes |
|---|---|---|---|---|
| Base58Check P2PKH/P2SH | `base58_tests.cpp`, `key_io_tests.cpp` | `inherited-with-rebrand` | `audit-address-rejection.py` (W-1) | Implementation unchanged; just a different version byte. |
| Bech32 / Bech32m encoding & decoding | `bech32_tests.cpp` | `inherited-with-rebrand` | — | Encoding logic unchanged; HRP differs. |
| **HRP (human-readable part)** | n/a | **`diverged-by-design`** | `audit-address-rejection.py` (W-1) | `b3` instead of `bc`; `tb3` instead of `tb`. |
| `validateaddress` rejects cross-chain inputs | `key_io_tests.cpp` | `diverged-by-design` | `audit-address-rejection.py` (W-1) | 36 Bitcoin samples rejected. |

## Build, RPC, infrastructure

| Bitcoin invariant | Upstream test | B3Chain status | B3Chain test | Notes |
|---|---|---|---|---|
| ZMQ notifications | `zmq_*` functional tests | `inherited` | — | |
| REST interface | `rest_tests.cpp`, `interface_rest.py` | `inherited` | — | |
| RPC framework correctness | `rpc_tests.cpp` | `inherited` | — | |
| `getblockchaininfo` shape | `rpc_blockchain.py` | `inherited-with-rebrand` | — | Network names: `b3chain-main` instead of `main`. |
| `validateaddress` shape | `rpc_psbt.py` | `inherited` | — | |
| Reproducible Guix builds | manual + `contrib/guix` | `pending` | — | Guix scripts inherited unchanged; B3Chain-specific verification on the roadmap (`SECURITY-ROADMAP.md`). |

---

## Findings

The verifier appends to this section every time it runs. When a row that
should be `inherited` reports `failing-investigation`, it is a real
regression and must be filed as an issue with label `inheritance-regression`.

<!-- INHERIT-FINDINGS-START -->
## Bitcoin Test Suite — Inheritance Run

Generated: 2026-05-19 13:14

| Category | Count |
|---|---:|
| PASS | 144 |
| DIVERGED-EXPECTED | 0 |
| FAIL | 0 |
| SKIP | 0 |
| **Total** | **144** |


<!-- INHERIT-FINDINGS-END -->

## Out of scope

- This document does not re-audit Bitcoin Core itself; we trust Bitcoin's own
  reviewers and CI for properties we did not touch. We only verify that we
  did not break those properties.
- Tests that depend on Bitcoin mainnet network resources (e.g. specific block
  hashes, mainnet checkpoints) are listed as `diverged-by-design` because
  B3Chain has its own genesis and chain.
- "Should we add a new property Bitcoin doesn't have?" is the job of
  [`SECURITY-ROADMAP.md`](SECURITY-ROADMAP.md), not this file.
