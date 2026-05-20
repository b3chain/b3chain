# PoW Peers Competitive Analysis — B3Chain vs Top-10 PoW Chains

**Status:** draft v1.0
**Last updated:** 2026-05-19
**Scope:** Head-to-head comparison of b3chain (B3PoW-Scratch v1.1) against the
ten chains it actually competes with on PoW-design merit. Stablecoins,
delegated PoS chains, and pure smart-contract L1s are out of scope on purpose —
they are not in the same market segment, and including them dilutes the
parts of the analysis that drive engineering decisions.

**Companion documents.**
[`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) (prioritised in-tree work items
to close the gaps identified here),
[`../security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md)
(51%-attack threat model, M-1 .. M-14),
[`../whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md)
(algorithm spec & security argument),
[`../CHANGELOG.md`](../CHANGELOG.md) (project history),
[`../../contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md)
(formal PoW spec).

---

## Table of contents

- [§1. Executive summary](#1-executive-summary)
- [§2. Methodology](#2-methodology)
- [§3. Per-axis comparison matrices](#3-per-axis-comparison-matrices)
  - [§3.1 Consensus algorithm & primitive](#31-consensus-algorithm--primitive)
  - [§3.2 Block production parameters](#32-block-production-parameters)
  - [§3.3 Throughput & latency](#33-throughput--latency)
  - [§3.4 Programmability](#34-programmability)
  - [§3.5 Privacy](#35-privacy)
  - [§3.6 Decentralization](#36-decentralization)
  - [§3.7 Security & 51%-attack posture](#37-security--51-attack-posture)
  - [§3.8 Tokenomics](#38-tokenomics)
  - [§3.9 Governance](#39-governance)
  - [§3.10 Ecosystem](#310-ecosystem)
  - [§3.11 Operator / UX surface](#311-operator--ux-surface)
- [§4. Per-chain pros / cons relative to b3chain](#4-per-chain-pros--cons-relative-to-b3chain)
  - [§4.1 Bitcoin (BTC)](#41-bitcoin-btc)
  - [§4.2 Litecoin (LTC)](#42-litecoin-ltc)
  - [§4.3 Dogecoin (DOGE)](#43-dogecoin-doge)
  - [§4.4 Bitcoin Cash (BCH)](#44-bitcoin-cash-bch)
  - [§4.5 Ethereum Classic (ETC)](#45-ethereum-classic-etc)
  - [§4.6 Zcash (ZEC)](#46-zcash-zec)
  - [§4.7 Monero (XMR)](#47-monero-xmr)
  - [§4.8 Dash (DASH)](#48-dash-dash)
  - [§4.9 Kaspa (KAS)](#49-kaspa-kas)
  - [§4.10 Ravencoin (RVN)](#410-ravencoin-rvn)
- [§5. Cross-cutting recommendations](#5-cross-cutting-recommendations)
- [§6. Path-to-top-10 scoreboard](#6-path-to-top-10-scoreboard)
- [§7. References](#7-references)

---

## §1. Executive summary

### §1.1 Thesis

B3Chain is a **conservative Bitcoin-Core 30.2.0 fork whose only consensus
departure from Bitcoin is the proof-of-work function** — B3PoW-Scratch v1.1,
a 1 MiB memory-hard BLAKE3 construction designed to be FPGA-economical and
GPU-hostile. Against the PoW peer cohort it stacks up as follows:

- **Where we are already top-cohort:** algorithmic threat-model rigour
  (fourteen named, code-located mitigations M-1 .. M-14 in
  [`B3POW-51-ATTACK-ANALYSIS.md §1.2`](../security/B3POW-51-ATTACK-ANALYSIS.md));
  four independent in-tree implementations CI-gated against one set of
  consensus vectors (Python ref, C++ consensus, TypeScript pool validator,
  SystemVerilog RTL); inheritance of every non-PoW Bitcoin property
  (UTXO, Taproot, 21 M cap, P2P wire format); zero premine, zero founders'
  reward, zero dev tax; MIT license; explicit operator-pinned finality RPCs
  (M-14 in v1.1.3, see [`../CHANGELOG.md`](../CHANGELOG.md)) without the
  partition-amplification footgun of BCH-N-style auto-finalisation.
- **Where we are bottom-cohort or absent:** circulating hashrate
  (pre-launch / bootstrap, by definition); exchange liquidity (zero
  centralised-exchange listings at time of writing); on-chain privacy
  (none — same as BTC, behind XMR / ZEC / DASH / LTC-MWEB); programmable
  asset issuance (none — same as BTC / LTC / DOGE / XMR, behind ETC /
  RVN / BCH-CashTokens); brand recognition and developer community
  density (early — no public BIP-equivalent process, no foundation
  treasury, no public security disclosure history).
- **Where we have made a deliberate choice not to compete:** smart
  contracts (rejected; we are Bitcoin-script + Taproot), high TPS L1
  (rejected; we mirror Bitcoin's monetary-policy-over-throughput
  trade-off), automatic finality (rejected; partition footgun
  documented in `B3POW-51-ATTACK-ANALYSIS.md §4.4`), masternode-style
  permissioned overlay (rejected; centralisation cost > finality
  benefit), BlockDAG (rejected; verification cost on commodity nodes
  and explorer / wallet UX cost exceed the throughput benefit for the
  segment we target).

### §1.2 Where we already beat the median PoW peer

| # | Strength | Why it's above-cohort | Reference |
|---|---|---|---|
| 1 | Codified threat model with M-1 .. M-14 each pointing to a file & line | Most PoW peers do not publish a mitigation-by-mitigation 51%-attack threat model; ETC's `MESS` and DASH's `ChainLocks` are the only comparable public artefacts. | [`B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md) |
| 2 | Four independent implementations CI-gated against one vector set | Reduces "one-implementation-bug = consensus split" risk that has hurt BCH, ETC, DOGE in the past. | [`SPEC.md §11`](../../contrib/miner/b3miner-rtl/SPEC.md), [`src/test/data/b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json) |
| 3 | Zero premine / zero founders' reward / zero dev tax | Only BTC, LTC, DOGE, BCH, RVN match this; ZEC (8 % dev fund), DASH (10 % treasury), ETC (none — same as us), XMR (none), KAS (none) split on this axis. | [`README.md`](../../README.md), genesis block coinbase |
| 4 | Operator-pinned finality (M-14) without auto-finality footgun | Mirrors BCH-N RPC surface (`finalizeblock` / `parkblock`) but explicitly rejects depth-10 auto-final; documented rationale beats any peer's. | [`../CHANGELOG.md`](../CHANGELOG.md) v1.1.3, [`B3POW-51-ATTACK-ANALYSIS.md §4.4`](../security/B3POW-51-ATTACK-ANALYSIS.md) |
| 5 | LWMA-3 + `max_reorg_depth = 200` + BIP94 timewarp + depth-asymmetric verifier budget | A four-layer stack against the dominant failure modes of every small-cap PoW chain (ETC-2020, BTG-2018, VTC-2018, ETC-2019, GRIN-2020). | M-2/M-3/M-4/M-7 in [`B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md) |

### §1.3 Where we are behind

| # | Gap | Closest peer benchmark | Roadmap pointer |
|---|---|---|---|
| 1 | Hashrate (bootstrap phase — by definition) | LTC merge-mining with DOGE gave both chains a permanent hashrate floor by 2014 | [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) R-04, R-09 |
| 2 | Exchange liquidity | LTC, BCH, DOGE on every tier-1 CEX; XMR delistings show even mature listings are volatile | [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) R-01, R-02 |
| 3 | On-chain privacy | XMR (default RingCT), ZEC (Halo 2 shielded), LTC (MWEB extension block), DASH (PrivateSend) | [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) R-12 |
| 4 | Asset issuance / programmable tokens | RVN (assets, sub-assets, restricted assets), BCH (CashTokens, May 2023), ETC (full EVM) | [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) R-11 |
| 5 | Public BIP-equivalent process & foundation | BTC (BIPs + Core maintainers + multiple funders), ZEC (ECC + ZF), ETC (ECIPs + ETC Coop), XMR (MRL + CCS) | [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) R-05, R-06 |
| 6 | Hardware-wallet support | BTC / LTC / BCH / DOGE / DASH on Ledger + Trezor; RVN partial; KAS recent | [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) R-03 |
| 7 | Production block explorer + multi-region SLA | BTC dozens, LTC several; small chains often single-explorer (single point of failure) | [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) R-07 |

### §1.4 Top-3 immediate moves

In priority order, the highest-leverage moves identified by this analysis
and tracked in [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md):

1. **R-01: Exchange-grade RPC parity & integration kit** (P0).
   Without this every other gain is unrealised because there is no
   liquidity path. Bitcoin-Core fork inheritance gives us 90 % for
   free; the missing 10 % (ZMQ topics, WebSocket push, REST
   parity, address-index daemon, RBF / replace-by-fee policy doc)
   is well-understood work.
2. **R-04: Hashrate-bootstrap policy** (P1).
   Pick *one* of: (a) AuxPoW-style merge-mining with another
   B3PoW-Scratch-compatible chain, (b) NiceHash-marketplace-aware
   short-window difficulty smoothing, or (c) faucet-funded mining
   subsidy curve over weeks 0–12. The "do nothing" option is the
   ETC-2020 failure mode (small chain + cheap rentable hashrate =
   open-the-door 51%-attack).
3. **R-11: Asset-issuance RFC** (P1).
   The single biggest "what does b3chain do that BTC doesn't?"
   feature an exchange listing committee asks for. Decide
   Ravencoin-style asset opcodes vs covenants-only vs CashTokens-
   style commitment vs "no, defer to L2", and ship a written
   decision either way.

## §2. Methodology

### §2.1 Data sources

Per-chain factual data in §3 and §4 is sourced from the primary
artefact for each chain, in this priority order:

1. The chain's reference-client source repo and its consensus
   parameters file (e.g.
   [`bitcoin/src/kernel/chainparams.cpp`](https://github.com/bitcoin/bitcoin/blob/master/src/kernel/chainparams.cpp),
   [`litecoin/src/chainparams.cpp`](https://github.com/litecoin-project/litecoin/blob/master/src/chainparams.cpp),
   [`dogecoin/src/chainparams.cpp`](https://github.com/dogecoin/dogecoin/blob/master/src/chainparams.cpp),
   [`bitcoin-cash-node/src/chainparams.cpp`](https://gitlab.com/bitcoin-cash-node/bitcoin-cash-node/-/blob/master/src/chainparams.cpp),
   [`core-geth`](https://github.com/etclabscore/core-geth) for ETC,
   [`zcash/src/chainparams.cpp`](https://github.com/zcash/zcash/blob/master/src/chainparams.cpp),
   [`monero/src/cryptonote_config.h`](https://github.com/monero-project/monero/blob/master/src/cryptonote_config.h),
   [`dash/src/chainparams.cpp`](https://github.com/dashpay/dash/blob/master/src/chainparams.cpp),
   [`rusty-kaspa`](https://github.com/kaspanet/rusty-kaspa) consensus
   crate, [`ravencoin/src/chainparams.cpp`](https://github.com/RavenProject/Ravencoin/blob/master/src/chainparams.cpp)).
2. The chain's improvement-proposal repo (BIPs / LIPs / DIPs / ZIPs /
   ECIPs / CashIPs / KIPs) for any post-genesis consensus change.
3. The chain's public RPC / explorer for live-data point cells
   (network hashrate, difficulty, supply, fee market).
4. Third-party tracking sites (CoinGecko, CoinMarketCap, Crypto51.app,
   miningpoolstats.stream) for market-cap, exchange-count, and
   pool-concentration cells.

### §2.2 Snapshot date

Live-data cells (hashrate, market cap, exchange count, pool
concentration, average tx fee) are snapshotted as of **2026-05-19**
and re-snapshotting them is an explicit todo in
[`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) R-08.

### §2.3 Citation format

Every fact-bearing cell in §3 / §4 carries a footnote marker `[X-NN]`
mapping to §7 (References). Soft-classified cells (e.g. "GPU-friendly",
"high decentralization") are quoted directly from the chain's own
documentation where possible; subjective bullets in §4 ("does well",
"does badly") are the report author's interpretation and are flagged
as such in the section preamble.

### §2.4 Caveats

- **Market-data volatility.** All market-cap and exchange-count cells
  may move by >10 % within a week. They are recorded for relative
  ordering of peer chains, not as absolute reference.
- **Hashrate is heterogeneous.** Comparing TH/s across SHA-256d,
  Scrypt, RandomX, kHeavyHash, KawPow, Equihash, B3PoW-Scratch is a
  category error — joules-per-hash and dollars-per-hash differ by
  orders of magnitude. We report each chain in its native unit and
  add a USD-cost-to-attack column where Crypto51-style estimates
  exist.
- **B3Chain is pre-mainnet at snapshot date.** B3Chain cells with
  "n/a — pre-mainnet" are honest; we do **not** project optimistic
  launch numbers into this comparison.
- **"Decentralization" is a contested measurement.** We report
  reproducible proxies (top-2 / top-3 pool share, Nakamoto
  coefficient for mining) and explicitly do not score it
  qualitatively in §3.6.

## §3. Per-axis comparison matrices

Each matrix has the eleven chains as rows (10 peers + b3chain). Cell
sources are footnoted `[X-NN]` and expanded in §7. Bullet list under
each matrix calls out where b3chain wins / loses on that axis.

### §3.1 Consensus algorithm & primitive

| Chain | Algorithm | Primitive | Working set | Target hardware | ASIC status |
|---|---|---|---|---|---|
| BTC | SHA-256d [BTC-1] | SHA-256 | ~256 B | ASIC | mature ASIC monoculture |
| LTC | Scrypt [LTC-1] | Salsa20/8 + SHA-256 | 128 KiB N=1024 (reduced) | ASIC | mature ASIC (Antminer L-series) |
| DOGE | Scrypt (AuxPoW merge-mined with LTC) [DOGE-1] | Salsa20/8 + SHA-256 | 128 KiB | ASIC | inherits LTC ASIC fleet via AuxPoW |
| BCH | SHA-256d [BCH-1] | SHA-256 | ~256 B | ASIC | shares BTC ASIC fleet |
| ETC | Etchash (Ethash + 4 GB DAG cap) [ETC-1] | Keccak-256 + FNV mixing | 4 GB DAG | GPU (8 GB+) | several ASIC vendors (Antminer E9, Innosilicon A11) |
| ZEC | Equihash (200,9) pre-Halo / **Halo 2** post-NU5 [ZEC-1] | BLAKE2b + tree search | ~144 MB Equihash | ASIC pre-Halo; under transition | Equihash ASIC (Antminer Z15); Halo 2 transition reshuffles |
| XMR | RandomX [XMR-1] | AES + Argon2 + JIT VM | 2 GB dataset / 256 MB cache | **CPU** (random code execution) | hostile to ASIC by design; no production ASIC |
| DASH | X11 (chain of 11 hash functions) [DASH-1] | BLAKE, BMW, Groestl, JH, Keccak, Skein, Luffa, CubeHash, SHAvite, SIMD, Echo | ~negligible | ASIC | mature ASIC (Antminer D-series) |
| KAS | kHeavyHash [KAS-1] | Keccak with optical-friendly matrix multiply | ~256 B | ASIC | ASIC mature (Antminer KS-series, IceRiver) |
| RVN | KawPow (ProgPoW variant) [RVN-1] | Keccak + program-generation | 4 GB DAG | GPU (8 GB+) | ASIC-resistant by design; partial FPGA |
| **b3chain** | **B3PoW-Scratch v1.1** [B3-1] | **BLAKE3 (2-round reduced)** | **1 MiB scratchpad, 8 lanes, 2048 iter** | **FPGA (Kintex UltraScale+ KU5P @ ~10 W)** | **GPU-hostile; ASIC possible but bounded — see [`SPEC.md §8`](../../contrib/miner/b3miner-rtl/SPEC.md)** |

**Where b3chain wins on this axis:**
- Only chain in the cohort whose reference economical miner is a
  low-power FPGA (~10 W). Every other chain is either dominated by
  high-power ASICs (BTC, LTC, DOGE, BCH, DASH, KAS) or by GPU farms
  (ETC, RVN) or by general-purpose CPU (XMR).
- BLAKE3 is the only modern (2020) primitive in the cohort. Most
  peers use 2008-vintage (SHA-256, Scrypt) or 2013-vintage (Equihash,
  Keccak) primitives.
- Four CI-gated reference implementations (Python / C++ / TypeScript /
  SystemVerilog) — no peer ships this level of cross-implementation
  parity (BTC has Core + secp256k1; the rest typically have one
  reference client).

**Where b3chain loses on this axis:**
- Zero deployed mining hardware in the wild at snapshot date. XMR's
  RandomX runs on any modern x86/ARM CPU instantly; RVN runs on every
  GPU made since 2018; we need a $1k+ FPGA card or a 100 H/s Python
  reference.
- B3PoW-Scratch is novel — no third-party cryptanalysis exists yet.
  XMR's RandomX has had ~5 years of academic scrutiny; ZEC's Halo 2
  has been audited by NCC and Trail of Bits; we have neither yet
  (external audit RFP in
  [`p3_audit`](../../.cursor/plans/b3pow-scratch_launch_package_c6f10175.plan.md)).

### §3.2 Block production parameters

| Chain | Target block time | Supply cap | Halving cadence | Retarget algorithm | Retarget window | Current inflation |
|---|---|---|---|---|---|---|
| BTC | 600 s [BTC-1] | 21,000,000 [BTC-1] | 210,000 blocks (~4 yr) [BTC-1] | EMA-of-2016 (DigishieldBitcoin) [BTC-1] | 2016 blocks (~14 d) | ~0.84 %/yr (post-Apr-2024 halving, subsidy 3.125 BTC) |
| LTC | 150 s [LTC-1] | 84,000,000 [LTC-1] | 840,000 blocks (~4 yr) [LTC-1] | same as BTC scaled | 2016 blocks (~3.5 d) | ~0.84 %/yr (subsidy 6.25 LTC post-Aug-2023 halving) |
| DOGE | 60 s [DOGE-1] | **unbounded** (10,000 DOGE/block forever) [DOGE-1] | none after block 600,000 | DigiShield v3 (per-block) [DOGE-1] | 1 block | ~3.7 %/yr (5.256 B DOGE/yr / 145 B circulating, decreasing as base grows) |
| BCH | 600 s [BCH-1] | 21,000,000 [BCH-1] | 210,000 blocks (~4 yr) [BCH-1] | **ASERT3-2d** (per-block exponential) [BCH-2] | 1 block (vs 2 d half-life) | ~0.84 %/yr (subsidy 3.125 BCH) |
| ETC | ~13 s [ETC-1] | 210,700,000 (Thanos schedule, "5M20" — 20 % reduction every 5M blocks) [ETC-2] | every 5,000,000 blocks (~2.3 yr) | none (PoW difficulty adjusts per-block via formula) | per-block | ~2.4 %/yr (subsidy 2.048 ETC post-block 19,250,000) |
| ZEC | 75 s post-Blossom [ZEC-2] | 21,000,000 [ZEC-1] | 1,680,000 blocks (~4 yr at 75 s post-Blossom adjustment) | DigiShield v3 [ZEC-1] | ~17 blocks (averaging) | ~5 %/yr (subsidy 1.5625 ZEC post-NU5 halving Nov 2024, of which 20 % to dev fund) |
| XMR | 120 s [XMR-1] | **unbounded** — tail emission 0.6 XMR/block forever after main curve ended ~May 2022 [XMR-2] | smooth emission curve, then flat tail | LWMA-1 [XMR-3] | ~720 blocks (1 d) | ~0.9 %/yr at snapshot (declining toward asymptote ~0.4 %) |
| DASH | 157.5 s (2 m 37.5 s) [DASH-1] | ~18,900,000 [DASH-1] | every 210,240 blocks (~383 d), **7.14 %** decrement (not 50 %) [DASH-1] | DGW v3 (Dark Gravity Wave) [DASH-1] | 24 blocks | ~3.2 %/yr (subsidy ~1.1 DASH/block; of that 60 % miner, 20 % masternodes, 20 % treasury after DIP-24) |
| KAS | **1000 ms** (1 block/s) post-Crescendo [KAS-2] | 28,704,026,601 [KAS-1] | "**chromatic phase**" smooth monthly decay (×1/√2 every 12 months) [KAS-1] | DAA per second [KAS-1] | per-block | ~6 %/yr (declining smoothly) |
| RVN | 60 s [RVN-1] | 21,000,000,000 (21 B) [RVN-1] | every 2,100,000 blocks (~4 yr) [RVN-1] | DGW v3 [RVN-1] | ~150 blocks | ~7.7 %/yr (subsidy 2,500 RVN, halves Jan 2026 to 1,250) |
| **b3chain** | **600 s** [B3-1] | **21,000,000** [B3-1] | **210,000 blocks (~4 yr)** [B3-1] | **LWMA-3** [B3-3] | **per-block** (LWMA window ≈ 60) | **n/a pre-mainnet** (subsidy 50 B3 at genesis, identical curve to BTC) |

**Where b3chain wins on this axis:**
- LWMA-3 retarget per block is strictly better than BTC's 2016-block
  retarget against hashrate-shock attacks (the failure mode that
  killed VTC, BTG, ETC retroactively). Among peers only DASH (DGW),
  ZEC (DigiShield), BCH (ASERT), XMR (LWMA-1), KAS (DAA per-second)
  match this responsiveness; we are in the top half.
- Hard 21 M cap (BTC parity) — XMR, DOGE, KAS abandon the cap in
  exchange for perpetual inflation. Whether this is a strength
  depends on whether you ask a Bitcoin maximalist or a Modern
  Monetary Theory advocate; the cohort splits cleanly.

**Where b3chain loses on this axis:**
- 600 s blocks are the longest in the cohort (tied with BTC / BCH).
  Cross-chain bridges, exchange deposit times, retail UX are all
  worse than KAS (1 s), ETC (13 s), DOGE (60 s), RVN (60 s).
- "n/a pre-mainnet" everywhere is the honest answer at snapshot date;
  closing this requires actually running mainnet, which is downstream
  of the launch package, not this analysis.

### §3.3 Throughput & latency

| Chain | Base-layer TPS (sustained) | Block size / weight | Mempool model | Confirmations to settlement (typical exchange policy) | L2 / scaling layer |
|---|---|---|---|---|---|
| BTC | ~7 tps [BTC-3] | 1 MB base / 4 M weight units (Segwit) [BTC-1] | Bitcoin Core mempool + RBF | 1–6 (varies $-> $50k threshold for high) | Lightning Network (mature); Liquid; ARK; statechains |
| LTC | ~28 tps theoretical [LTC-1] | 1 MB base / 4 MW (MWEB extension block adds optional) | Core mempool | 6 | Lightning; MWEB (extension block, March 2022) |
| DOGE | ~33 tps theoretical [DOGE-1] | 1 MB | Core mempool | 6 (or higher on tier-1 CEXs) | Lightning (limited); RadioDoge experimental |
| BCH | ~100 tps sustained, ~1000+ burst (32 MB blocks) [BCH-1] | 32 MB | Core mempool + RBF disabled by default | 10 (post 2018 split, exchanges raised) | CashTokens (May 2023, on-chain); SmartBCH (EVM sidechain) |
| ETC | ~15 tps [ETC-1] | gas-limited (~30 M gas/block) | EVM mempool | 14,000 confirmations (~50 h) on Coinbase post-2020 attacks [ETC-3] | none mature (Layer Zero, Hyperlane bridges) |
| ZEC | ~6 tps transparent / ~3 tps shielded [ZEC-1] | 2 MB | Core mempool | 6 transparent / 6 shielded | Zashi mobile wallet; no general L2 |
| XMR | ~4–6 tps [XMR-1] | dynamic (median × 2 cap) | Core mempool | 10 | none — rejected on privacy grounds; payment channels research |
| DASH | ~28 tps theoretical, ~1 tps actual [DASH-1] | 2 MB | Core mempool + InstantSend | **InstantSend = 1 confirmation** (≤1 s via ChainLocks LLMQ) [DASH-2] | InstantSend / ChainLocks (built-in); Platform (sidechain) |
| KAS | **~100–500 tps measured; design target 3,000 tps** [KAS-2] | BlockDAG, gas-limited | DAG mempool | "**~10 s settlement**" (DAA + GHOSTDAG selected parent depth) | none — base-layer scaling via DAG |
| RVN | ~110 tps theoretical [RVN-1] | 1 MB → 2 MB (RIP-2) | Core mempool | 60 (high — exchanges treat assets cautiously) | none mature |
| **b3chain** | **~7 tps** (identical to BTC) [B3-1] | **1 MB base / 4 MW** (identical to BTC) [B3-1] | **Core mempool + RBF + package relay** (inherits BTC 30.2.0) | **6 (provisional, matches BTC)** | **Lightning compatible by construction** (Taproot + script identical to BTC); no in-tree channel-factory work yet |

**Where b3chain wins on this axis:**
- L2 inheritance for free: anything that runs on BTC base-layer
  script + Taproot runs on b3chain, including Lightning. No peer
  fork that broke Bitcoin script compatibility (BCH after 2017,
  BSV, etc.) has this property.
- 4 MW block weight is fine for Lightning channel opens / closes;
  no peer in the cohort except BCH (32 MB) materially beats BTC
  on base-layer throughput, and BCH paid for it with hashrate carve-out
  and tier-1 exchange caution.

**Where b3chain loses on this axis:**
- 7 tps base layer is bottom-cohort tied with BTC, BCH-pre-2017,
  ZEC, XMR. KAS is two orders of magnitude ahead; DASH (with
  InstantSend) ships subsecond settlement; DOGE / RVN are 4× ahead
  on raw tps.
- Lightning is "compatible by construction" but **not deployed** —
  no public LN node on testnet, no channel-opening UX in the
  reference wallet, no documentation. Closing this is R-13 in the
  roadmap.

### §3.4 Programmability

| Chain | Script language | Turing-complete | Native asset issuance | Covenants / introspection | Privacy opcodes |
|---|---|---|---|---|---|
| BTC | Bitcoin Script (stack VM, ~200 opcodes) + Taproot/Schnorr | no (loop-free, bounded) | none (workarounds: Ordinals, Runes, BRC-20) | partial (`OP_CHECKTEMPLATEVERIFY` deferred, `OP_CAT` re-proposal active) | none (CoinJoin / silent-payments are wallet-level) |
| LTC | Bitcoin Script (BTC parity) + Taproot + **MWEB** | no | none | partial via Taproot | **MWEB extension block** (March 2022, BIP MWEB) |
| DOGE | Bitcoin Script (DOGE-1.14.x inherits BTC 0.21.x) | no | none | very limited | none |
| BCH | **CashScript** (extended Script: `OP_DSV`, native introspection, `OP_RETURN` extended, **CashTokens** opcodes May 2023) [BCH-3] | no | **CashTokens** (fungible + non-fungible, May 2023) [BCH-3] | yes — introspection opcodes since 2022 | none |
| ETC | **EVM** (full Ethereum Virtual Machine) [ETC-1] | **yes** | **ERC-20 / ERC-721 / ERC-1155** (via contracts) | n/a (EVM = full programmability) | none on base layer; Aztec-style L2 efforts |
| ZEC | Bitcoin-derived script + **shielded Sprout/Sapling/Orchard pools** | no | none | partial | **zk-SNARK shielded payments** (Halo 2 post-NU5) |
| XMR | minimal (output script effectively `0` / `1` proof-of-knowledge) | no | none | none | **RingCT + stealth addresses default-on** |
| DASH | Bitcoin Script + DASH-specific masternode messages | no | none on L1; DAPI on Platform sidechain | none | **PrivateSend** (CoinJoin via masternodes; opt-in, several rounds) |
| KAS | minimal script (subset of Bitcoin Script) [KAS-1] | no (currently); planned full smart contracts post-Crescendo via `kOS` initiative | none currently | none | none |
| RVN | Bitcoin Script + **asset opcodes** (`OP_RVN_ASSET`, sub-assets, restricted assets, messaging, voting) [RVN-2] | no | **rich asset layer** (fungible, non-fungible, restricted with KYC tagging, sub-assets, messaging, voting) | partial via asset metadata | none |
| **b3chain** | **Bitcoin Script + Taproot/Schnorr (full BTC parity, no modifications)** [B3-1] | no | **none** (BTC parity — Ordinals-equivalent inscriptions work but are not first-class) | partial via Taproot (`OP_CHECKSIGADD`); no `OP_CTV`/`OP_CAT` (BTC parity) | none |

**Where b3chain wins on this axis:**
- BTC parity means every wallet that supports BTC Taproot supports
  us with a one-line `--hrp b3` patch. No fork-specific opcodes to
  maintain, no fork-specific audit surface, no "is this an asset or
  a satoshi" UX confusion (the RVN, BCH-CashTokens, and BSV
  experience).
- No "we built our own script extension" maintenance burden. BCH's
  `OP_DSV` and CashTokens, RVN's asset opcodes, and ETC's EVM all
  have to track upstream evolution; we track BTC for free.

**Where b3chain loses on this axis:**
- No native asset issuance is the single most common "what does this
  do that BTC doesn't?" exchange-listing-committee question. Need a
  written decision (R-11 in roadmap): Ravencoin-style assets vs
  covenants-via-`OP_CTV` vs CashTokens-style commitment vs "no, defer
  to L2 / Ordinals-equivalent".
- No on-chain privacy (see §3.5).
- No Turing-complete contracts means DeFi / NFT marketplace / L2
  bridge developers have no story; that's most of the post-2020
  developer community. We are explicitly not chasing this segment
  but should say so in writing.

### §3.5 Privacy

| Chain | Default transparency | Optional privacy | Wallet address format | Notes |
|---|---|---|---|---|
| BTC | transparent | wallet-level CoinJoin (Wasabi, JoinMarket); silent payments (BIP352, 2024) | P2PKH / P2SH / Bech32 / Bech32m | no protocol-level privacy |
| LTC | transparent | **MWEB extension block** (Mimblewimble; opt-in; March 2022) | legacy / Bech32 / MWEB peg-in | several CEX delisted LTC over MWEB |
| DOGE | transparent | none protocol-level | DOGE legacy | — |
| BCH | transparent | none protocol-level (CashFusion is wallet-level CoinJoin) | CashAddr / legacy | — |
| ETC | transparent | none protocol-level (no Tornado-Cash-style on-chain mixer) | 0x address (EVM) | — |
| ZEC | transparent + **shielded** | **Halo 2 zk-SNARK shielded pool** (Orchard, post-NU5; no trusted setup) [ZEC-3] | t-address (transparent) / u-address (unified — Orchard + Sapling + transparent) | shielded usage ≪ transparent usage; some exchanges only support t-addresses |
| XMR | **shielded by default** | n/a — there is no transparent option | XMR address (stealth + ring) | RingCT + Bulletproofs+ + stealth + ring signatures, all default-on |
| DASH | transparent | **PrivateSend** (CoinJoin via masternodes; opt-in, 2–16 rounds) | DASH legacy + masternode messages | several CEX delisted DASH over PrivateSend |
| KAS | transparent | none | KAS Bech32 ("kaspa:") | — |
| RVN | transparent | none protocol-level (asset metadata is transparent by design — required for compliance) | RVN legacy | restricted-asset KYC tagging is opposite of privacy |
| **b3chain** | **transparent** [B3-1] | **none in v1** (CoinJoin / silent-payments-equivalent work at wallet level for free, BTC parity) | **Bech32 (`b3` HRP)** [B3-1] | **explicit non-goal in v1**; see R-12 in roadmap |

**Where b3chain wins on this axis:**
- Listing-friendly. Exchange delisting risk on the XMR / ZEC / DASH /
  LTC-MWEB pattern is zero because there is nothing privacy-specific
  to delist. This is a real competitive advantage in 2024–2026
  regulatory climate (US Patriot Act / EU MiCA / Travel Rule).

**Where b3chain loses on this axis:**
- We have no privacy story whatsoever for "I want to use B3 to buy
  something without my employer / spouse / nation-state seeing it".
  XMR / ZEC have the full pitch. LTC-MWEB has an opt-in pitch. We
  have a BTC-equivalent (wallet-level only) pitch.
- A future privacy upgrade has to clear the audit bar of zk-SNARKs
  (ZEC), Mimblewimble (LTC), or ring signatures (XMR). None of
  these are small projects. R-12 frames the decision tree.

### §3.6 Decentralization

Reproducible proxies only. We avoid qualitative "is this chain
decentralized?" scoring on principle; the literature
([Bitcoin SoK 2015 §VI](https://www.ieee-security.org/TC/SP2015/papers/6949a104.pdf))
does not settle the question.

| Chain | Top-2 pool share (mining) | Top-3 pool share (mining) | Mining-Nakamoto coef | Client diversity | Reachable nodes |
|---|---|---|---|---|---|
| BTC [BTC-4] | ~50 % (Foundry + AntPool) | ~70 % | 3 | high (Core, Knots, btcd, …) | ~15,000 |
| LTC [LTC-2] | ~70 % (F2Pool + ViaBTC; AuxPoW concentrates) | ~85 % | 2 | medium | ~1,500 |
| DOGE [DOGE-2] | inherited from LTC | inherited from LTC | 2 (via LTC AuxPoW) | medium (Core fork) | ~1,300 |
| BCH [BCH-4] | ~60 % | ~80 % | 2 | high (BCHN, Knuth, BU, BCHD) | ~1,000 |
| ETC [ETC-4] | ~45 % | ~65 % | 3 | high (Hyperledger Besu, Core-Geth, Multi-Geth) | ~2,000 |
| ZEC [ZEC-4] | ~55 % | ~75 % | 2 | medium (zcashd, zebra) | ~150 |
| XMR [XMR-4] | **distributed via P2Pool** (~10 % via P2Pool); rest split across small pools | ~40 % across top-3 | 5+ | medium (monerod, P2Pool) | ~3,000 |
| DASH [DASH-4] | ~55 % | ~80 % | 2 | low (dashd dominant) | ~5,000 (incl. masternodes) |
| KAS [KAS-4] | ~50 % | ~70 % | 2 | medium (rusty-kaspa, kaspad Go) | ~10,000 |
| RVN [RVN-4] | ~55 % | ~75 % | 2 | low (Ravencoin Core dominant) | ~3,000 |
| **b3chain** | **n/a pre-mainnet**; testnet is 1 reference pool (`pool.b3chain.org`) | n/a | n/a | **medium at genesis** (Core + four-implementation-parity in `SPEC.md`) | **3 seed nodes** at snapshot (seed1/seed2/seed3 per `.cursor/rules/git-push-policy.mdc`) |

**Where b3chain wins on this axis:**
- FPGA reference-design economics specifically targets the
  "hobbyist + small operator" segment that BTC / LTC / BCH / DASH /
  KAS lost to industrial-scale farms. If the design goal lands, the
  mining Nakamoto coefficient ought to be higher than the cohort
  median.
- Four implementations (Python, C++, TypeScript, SystemVerilog) is
  better client-diversity baseline than DASH / RVN / KAS.

**Where b3chain loses on this axis:**
- Three seed nodes is the smallest reachable-node count in the
  cohort by a factor of ~100. This is expected for pre-mainnet but
  needs aggressive seed growth in weeks 0–12 — tracked as R-09.
- One reference mining pool is a single point of failure for
  hashrate during bootstrap. Mitigated only by R-04
  (hashrate-bootstrap policy) plus R-10 (third-party pool
  onboarding).

### §3.7 Security & 51%-attack posture

| Chain | Network hashrate (snapshot 2026-05-19) | Cost-to-attack 1 h ($ rented) | Documented 51%-attack history | Reorg-depth cap | Finality mechanism | Defensive RPC surface |
|---|---|---|---|---|---|---|
| BTC | ~650 EH/s [BTC-5] | ~$2.5 M/h [Crypto51] | none successful at >1-confirm depth | none (longest-chain only) | probabilistic | `invalidateblock` / `reconsiderblock` (manual; not consensus) |
| LTC | ~1.0 PH/s (scrypt) [LTC-5] | ~$60k/h [Crypto51] | none deep | none | probabilistic | BTC-equivalent |
| DOGE | ~1.0 PH/s (merge-mined with LTC) [DOGE-5] | shared with LTC | none deep | none | probabilistic | BTC-equivalent |
| BCH | ~3.5 EH/s [BCH-5] | ~$15k/h [Crypto51] | none successful; multiple shallow reorgs | **none — but BCH-N ships `finalizeblock` / `parkblock` operator RPCs** [BCH-N] | probabilistic + opt-in operator-pinned finality | **`finalizeblock`, `unfinalizeblock`, `parkblock`, `unparkblock`** (BCHN) |
| ETC | ~245 TH/s [ETC-5] | ~$80k/h [Crypto51] | **Jan 2019, Aug 2020 (×3, 7000-block reorg)** [ETC-Att] | none (consensus); **MESS** behavioural [ETC-MESS] | probabilistic + MESS (subjective penalty for deep reorgs) | MESS in Core-Geth (deprecated 2022 after gas issues, partially restored) |
| ZEC | ~10 GS/s (Equihash; transitioning post-Halo) [ZEC-5] | ~$2k/h pre-Halo [Crypto51] | none deep | none | probabilistic | none beyond Bitcoin-equivalent |
| XMR | ~5 GH/s (RandomX) [XMR-5] | ~$10k/h via rented CPU clouds (very approximate — XMR has no NiceHash equivalent) | none deep on canonical chain; multiple shallow disturbances | none | probabilistic | none beyond Bitcoin-equivalent |
| DASH | ~7 PH/s (X11) [DASH-5] | ~$15k/h [Crypto51] | none successful since 2017 | **none at consensus** — **`ChainLocks` finalises at depth 1** [DASH-CL] | **deterministic at depth 1 via LLMQ ChainLocks** | ChainLocks (consensus-enforced via masternode LLMQ quorum) |
| KAS | ~1.3 EH/s (kHeavyHash) [KAS-5] | ~$50k/h [Crypto51] | none deep | DAG-pruning horizon (≈14400 blocks ≈ 4 h pre-Crescendo) | probabilistic + DAG pruning | DAG-specific (`getVirtualSelectedParent`, etc.) |
| RVN | ~6 TH/s (KawPow) [RVN-5] | **~$5k/h [Crypto51]** — extremely cheap to rent | **Jan 2020 ($2k attack), July 2020, Nov 2020** [RVN-Att] | none consensus | probabilistic | none beyond Bitcoin-equivalent |
| **b3chain** | **n/a pre-mainnet** (testnet only) | **n/a** (depends on FPGA fleet size at mainnet, see [`B3POW-51-ATTACK-ANALYSIS.md §3`](../security/B3POW-51-ATTACK-ANALYSIS.md)) | **none — pre-launch** | **`max_reorg_depth = 200`** (consensus, M-4) [B3-2] | **probabilistic + operator-pinned finality (`finalizeblock`)** + `max_reorg_depth` cap | **`finalizeblock`, `unfinalizeblock`, `parkblock`, `unparkblock`, `getfinalizedblockhash`** (M-14, v1.1.3) [B3-CHL] |

**Where b3chain wins on this axis:**
- We are the **only chain in the cohort** with a hard consensus
  `max_reorg_depth` rule (M-4). BCH-N's `finalizeblock` is operator-
  pinned, not consensus; DASH's ChainLocks needs masternode quorum;
  ETC's MESS is subjective. M-4 is a no-human-in-the-loop rejection
  of >200-block reorgs.
- We ship the BCH-N operator RPC surface (`finalizeblock`,
  `parkblock`) **plus** the consensus floor, **plus** the depth-aware
  ban-score (M-5), **plus** the depth-asymmetric verifier budget
  (M-7). No peer ships all four.
- We explicitly publish the threat model
  ([`B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md))
  and the response runbook
  ([`RESPONSE-RUNBOOK-51ATTACK.md`](../security/RESPONSE-RUNBOOK-51ATTACK.md)).
  Only DASH (ChainLocks paper) and BCH (BCH-N docs) match this depth.

**Where b3chain loses on this axis:**
- Pre-mainnet hashrate is zero, so cost-to-attack-1h is zero too.
  M-4 caps the *damage* but not the *attempt*. R-04
  (hashrate-bootstrap policy) is the only structural answer.
- We have no automatic-finality overlay equivalent to DASH's
  ChainLocks. This is a **deliberate** non-goal (documented in
  `B3POW-51-ATTACK-ANALYSIS.md §4.4`) but it is a thing exchanges
  ask for.

### §3.8 Tokenomics

| Chain | Premine | Founders' / dev reward | Dev tax | Treasury | Vesting | Total supply curve |
|---|---|---|---|---|---|---|
| BTC | 0 | 0 | 0 | none | n/a | asymptotic to 21 M |
| LTC | 150 LTC (negligible) | 0 | 0 | none | n/a | asymptotic to 84 M |
| DOGE | 0 | 0 | 0 | none | n/a | linear forever (5.256 B/yr) |
| BCH | 0 (BTC fork) | 0 (post 2020 IFP failure) | 0 | none | n/a | asymptotic to 21 M |
| ETC | 0 (ETH fork) | 0 | 0 | none | n/a | asymptotic to ~210.7 M |
| ZEC | 0 | **20 % of subsidy to dev fund** (post-NU5; previously Founders' Reward 20 % first 4 yr) | 20 % | yes (Major Grants, ECC, ZF) | n/a | asymptotic to 21 M |
| XMR | 0 | 0 | 0 (Community Crowdfunding System is voluntary) | none | n/a | asymptotic, then tail 0.6/block forever |
| DASH | "instamine" Jan 2014 (~1.9 M minted in first 2 d) [DASH-IM] | **20 % of block subsidy to masternode operators** + 10 % treasury | 10 % | yes (treasury votes) | n/a | asymptotic to ~18.9 M |
| KAS | 0 | 0 | 0 | none | n/a | asymptotic to ~28.7 B |
| RVN | 0 | 0 | 0 | none | n/a | asymptotic to 21 B |
| **b3chain** | **0** | **0** | **0** | **none** | **n/a** | **asymptotic to 21 M (BTC parity)** |

**Where b3chain wins on this axis:**
- We are in the small group (BTC, BCH, DOGE, ETC, KAS, RVN, XMR,
  b3chain) with zero premine + zero dev tax. That's a real
  exchange-listing differentiator vs ZEC (20 % dev fund) and DASH
  (instamine + 30 % masternode/treasury).
- Hard cap matches BTC, which is the strongest narrative anchor in
  the cohort.

**Where b3chain loses on this axis:**
- Zero dev fund means R&D is funded out-of-pocket. ZEC has ECC + ZF
  budgets; DASH has voted treasury; XMR has CCS; we have nothing
  documented. R-05 in the roadmap is the *funding model statement*
  (which can still conclude "donations + sponsorships only", but the
  decision needs to be in writing).

### §3.9 Governance

| Chain | Improvement-proposal process | Foundation / sponsor | Fork history | Change-control velocity |
|---|---|---|---|---|
| BTC | **BIPs** (https://github.com/bitcoin/bips); rough consensus + miner signaling for consensus changes | Bitcoin Core volunteers + multiple sponsors (Spiral, Brink, MIT-DCI, …) | Segwit (2017), Taproot (2021); BCH/BSV/etc. spin-offs | slow & deliberate; Taproot took ~4 yr |
| LTC | LIPs (https://github.com/litecoin-project/lips); Charlie Lee + LF | **Litecoin Foundation** | MWEB (2022) | medium |
| DOGE | informal; DOGE Foundation revived 2021 | **Dogecoin Foundation** (Vitalik, Jared Birchall, …) | revival of Core 1.14 maintenance | slow |
| BCH | **CHIPs** (CashIPs); 6-month "May upgrade" cadence; multi-client coordination | **BCHN, Bitcoin Cash Network** + Knuth + BU | BSV (2018) split | medium — fast cadence but contentious |
| ETC | **ECIPs** (https://ecips.ethereumclassic.org); ETC Cooperative | **ETC Cooperative** | DAO fork (2016) = original split | slow |
| ZEC | **ZIPs** (https://zips.z.cash); ECC + ZF | **ECC + Zcash Foundation** (two organisations) | Sapling, Heartwood, Canopy, NU5 (~yearly NU) | medium — yearly Network Upgrade cadence |
| XMR | **MRL + MoneroResearchLab papers**; community workgroups; **CCS** funding | none corporate (CCS = Community Crowdfunding) | RingCT (2017), Bulletproofs (2018), Bulletproofs+ (2022), RandomX (2019) | medium — hard-fork roughly every 6 months |
| DASH | **DIPs** (https://github.com/dashpay/dips); **masternode votes** for treasury | **Dash Core Group** (funded by treasury votes) | InstantSend (2014), ChainLocks (2018), Platform (2023) | medium — masternode vote gives a real veto |
| KAS | **KIPs** (https://github.com/kaspanet/kips); active discord | none corporate | Crescendo upgrade (2025) | fast |
| RVN | **RIPs**; informal community + Magalis / Tron influences | **Ravencoin Foundation** | asset layer rollout (2018), KawPow (2020), restricted assets (2021) | slow recent years |
| **b3chain** | **none yet** — no published improvement-proposal repo; consensus-change discipline inherited from Bitcoin Core (BIP-process expectations); see R-06 | **none yet** — no foundation, no sponsor list, no published funding statement (see R-05) | **none — pre-genesis at snapshot** | **n/a** |

**Where b3chain wins on this axis:**
- Inheriting Bitcoin Core's review discipline, commit hygiene, and
  conservative-changes culture is a real strength most peers can't
  claim (KAS, BCH, BSV all moved fast and broke things).

**Where b3chain loses on this axis:**
- No published improvement-proposal process. Even DOGE has a
  Foundation now; KAS has KIPs; BCH has CHIPs. R-06 in the roadmap
  is "publish `doc/bips/README.md` with the b3chain-specific BIP
  process" (likely "we adopt BTC BIPs + a `B3IP-NNNN` namespace for
  PoW-specific changes").
- No published funding model. R-05.

### §3.10 Ecosystem

| Chain | CEX listings (tier-1) | Wallet support (hardware + software) | Mining pools (count) | Hashrate marketplace | Dev tooling / SDKs | RPC parity with bitcoind |
|---|---|---|---|---|---|---|
| BTC | every CEX | every wallet | hundreds | NiceHash, MiningRigRentals, etc. | every language | n/a (it *is* bitcoind) |
| LTC | every tier-1 CEX | Ledger, Trezor, Electrum-LTC, etc. | dozens (LTC + DOGE merge) | NiceHash | most languages | high (Bitcoin Core fork) |
| DOGE | every tier-1 CEX | Ledger, Trezor, MyDoge, Electrum-DOGE | shared with LTC via AuxPoW | NiceHash | most languages | high (Bitcoin Core fork) |
| BCH | most tier-1 CEX (some 2018-split caution) | Ledger, Trezor, Electron Cash, BCHN | ~10 | NiceHash | most languages | medium (BCH-N divergence) |
| ETC | most tier-1 CEX (Coinbase requires 14,000 conf post-2020) | Ledger, Trezor, MetaMask (EVM) | ~15 | NiceHash, MRR | every language (EVM tooling) | EVM toolchain (web3.js, ethers, viem, hardhat) |
| ZEC | most tier-1 CEX (a few delisted in privacy crackdown) | Ledger (transparent only on most), Trezor, Zashi (mobile), zcashd, zebra | several | NiceHash (Equihash) | several languages | medium (zcashd fork of bitcoind) |
| XMR | **delisted from Binance, Kraken (EU), OKX, Bitfinex**; still on Kraken (non-EU), Coinbase Wallet (custodial), DEXs | Cake Wallet, Monerujo, official GUI; **Ledger + Trezor support** | many small pools + **P2Pool** decentralised | none (RandomX not on NiceHash) | several languages | XMR-specific (not bitcoind-compatible) |
| DASH | most tier-1 CEX | Ledger, Trezor, Dash Core, Dash Electrum | ~15 | NiceHash (X11) | several languages | high (Bitcoin Core fork) |
| KAS | most tier-1 CEX (post-2024) | Tangem, Kasware, Onekey; **no Ledger native (2026)** | many (IceRiver / Bitmain) | NiceHash (kHeavyHash) | Rust, Go, TypeScript | KAS-specific (DAG model — not bitcoind) |
| RVN | mid-tier CEX; KuCoin, Gate, Bittrex (pre-2023 closure) | Ledger, Trezor (limited), Raven Core | ~10 | NiceHash (KawPow) | Bitcoin-tooling-compatible mostly | high (Bitcoin Core 0.16.x fork) |
| **b3chain** | **zero CEX listings at snapshot** (R-02) | **zero hardware-wallet support; reference QT wallet only** (R-03) | **1 reference pool** (`pool.b3chain.org`) | **zero NiceHash listing** (R-04) | **bitcoind-equivalent RPC inherited from Core 30.2.0** | **very high — Bitcoin Core 30.2.0 fork** [B3-1] |

**Where b3chain wins on this axis:**
- bitcoind-RPC parity is genuinely useful: any existing Bitcoin
  custodian / exchange / explorer / monitoring tool works against us
  with at most a chain-params patch. ZEC, DASH share this; XMR, ETC,
  KAS don't.
- No legacy hardware-wallet integration debt: we can ship correct
  BIP44/49/84/86 paths from day one (R-03).

**Where b3chain loses on this axis:**
- Every cell of this row except RPC parity is zero/empty at
  snapshot. This is the single largest gap and drives almost every
  P0 item in the roadmap.

### §3.11 Operator / UX surface

| Chain | Address format(s) | Bech32 HRP | Default P2P port | Default RPC port | Fee market | Avg tx fee USD (snapshot) | Time-to-first-block on consumer HW |
|---|---|---|---|---|---|---|---|
| BTC | P2PKH, P2SH, Bech32, Bech32m | `bc` | 8333 | 8332 | mature, RBF, package relay | $1–10 | days (ASIC required) |
| LTC | P2PKH, P2SH, Bech32, MWEB | `ltc` | 9333 | 9332 | mature | $0.01 | hours (ASIC) |
| DOGE | P2PKH (legacy), Bech32 not standard | none | 22556 | 22555 | floor-fee + spam controls (DOGE-specific) | $0.30 | shared with LTC |
| BCH | CashAddr + legacy | `bitcoincash` | 8333 | 8332 | low (32 MB capacity) | $0.001 | hours (ASIC) |
| ETC | 0x address (EVM) | n/a | 30303 | 8545 (JSON-RPC) | gas market (EIP-1559 NOT adopted) | $0.10 | hours (GPU) |
| ZEC | t-address + u-address (unified) | unified-address format | 8233 | 8232 | low-throughput | $0.001 | minutes–hours (varies post-Halo) |
| XMR | XMR address (95 chars, stealth) | n/a | 18080 | 18081 | dynamic block-weight-based | $0.005 | minutes (CPU, but variance) |
| DASH | DASH legacy | none | 9999 | 9998 | low | $0.001 | minutes (with masternode quorum) |
| KAS | Bech32 `kaspa:` | `kaspa` | 16110 | 16111 | low | $0.0001 | seconds (with KS ASIC); minutes (CPU PoW reference) |
| RVN | RVN legacy + RVN asset addresses | none | 8767 | 8766 | low | $0.005 | hours (GPU) |
| **b3chain** | **Bech32 + Bech32m (full BTC parity, no legacy)** | **`b3`** [B3-1] | **8533** [B3-1] | **8534** [B3-1] | **inherited from BTC (RBF + package relay)** | **n/a pre-mainnet** | **n/a pre-mainnet** (FPGA only economical; CPU reference ≈ hours) |

**Where b3chain wins on this axis:**
- Bech32+Bech32m only (no legacy P2PKH) is the cleanest cohort
  position. Eliminates the "old vs new address" UX confusion that
  hurt DOGE and BCH adoption.
- Distinct P2P / RPC ports (8533 / 8534) and distinct HRP (`b3`)
  mean no accidental cross-chain replay or wallet confusion. Some
  peers (BCH at fork) had real problems here.

**Where b3chain loses on this axis:**
- "n/a pre-mainnet" everywhere. Time-to-first-block on consumer
  hardware is the single most-asked question by retail miners and
  we have no answer except "buy a $1k+ FPGA card or run a Python
  reference and find a block in days". XMR's "any laptop, minutes"
  pitch is the gold standard.

## §4. Per-chain pros / cons relative to b3chain

Per-chain preamble: "does well" / "does badly" bullets in this section
are the report author's interpretation of widely-reported public
behaviour, not the chain's own self-description. The "in-tree work
item it suggests" line is the single most actionable lesson and is
indexed into [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md).

### §4.1 Bitcoin (BTC)

**What BTC does well that we should learn from:**
- **BIP process discipline.** Every consensus and policy change goes
  through a public, numbered, reviewed proposal at
  [`github.com/bitcoin/bips`](https://github.com/bitcoin/bips).
  Listing committees and exchanges read these to evaluate fork
  safety. We get this for free by inheriting Bitcoin Core's culture
  but need a public B3IP-NNNN namespace for the PoW-specific
  changes (M-1 .. M-14 already qualify).
- **Bug-bounty and responsible-disclosure pipeline.** Bitcoin Core
  has a published security contact, a bug-bounty page, and
  retroactive disclosure of fixed vulnerabilities (CVE-2018-17144,
  etc.). The optics matter to exchanges.
- **Long-term-stable reference miner / pool stack.** btcd, cgminer
  era → BFGMiner → ASIC firmware ecosystem. Anyone can run a
  solo-mining setup against a 30-year-old protocol unchanged.
- **No premine, no foundation tax** — the *narrative anchor* of the
  whole asset class.

**What BTC does badly that we explicitly avoid (or accept the same
trade-off knowingly):**
- **2016-block retarget window** is too slow for small-cap chains;
  it caused VTC / BTG / ETC the most damage during their 51%-
  attacks. We use LWMA-3 instead (M-3).
- **ASIC monoculture and geographic concentration** is the
  long-standing decentralization complaint. We accept the
  conceptual trade-off (PoW = some hardware specialisation is
  inevitable) but B3PoW-Scratch's FPGA-target is an attempt at a
  different equilibrium.
- **No native asset issuance** has been forced on by Ordinals /
  Runes / BRC-20 in a way that produced "fee market dysfunction"
  complaints and forks. We get to learn from that mess before
  deciding R-11.

**One concrete in-tree work item it suggests for us:**
**R-06 — publish `doc/bips/README.md` with the b3chain BIP process
and renumber M-1 .. M-14 as B3IPs** (e.g. M-3 LWMA-3 = B3IP-0003,
M-14 finalize/park = B3IP-0014). This is a documentation move only,
zero consensus impact.

### §4.2 Litecoin (LTC)

**What LTC does well that we should learn from:**
- **Boring-stable maintenance over 13 years.** LTC has shipped
  faithful upstream merges from Bitcoin Core continuously
  (Segwit 2017, Taproot 2022) without a contentious fork. Our
  cherry-pick discipline should match this.
- **MWEB extension-block design** is the cleanest "add privacy
  without breaking everything" pattern in the cohort. It opted
  into Mimblewimble via a peg-in/peg-out extension block, so
  pre-MWEB nodes simply ignore MWEB blocks. R-12 (privacy) should
  evaluate MWEB-as-a-pattern even if not the algorithm.
- **AuxPoW merge-mining with DOGE** gave both chains a permanent
  hashrate floor by 2014. Whether b3chain can do anything analogous
  is R-04.

**What LTC does badly that we explicitly avoid:**
- **Lost differentiation.** "Silver to Bitcoin's gold" stopped
  meaning anything once BTC scaled fees down post-bear-market. LTC
  is shrinking in market-share for lack of a story. We need a story
  beyond "BTC fork" — B3PoW-Scratch *is* that story, but only if
  the FPGA-economics claim holds up under independent audit
  (`p3_audit` in launch plan).
- **MWEB rollout was rough on exchanges.** Several CEX delisted LTC
  citing AML concerns. If R-12 lands on a privacy upgrade, the
  rollout path needs to be explicit (opt-in pool with view keys,
  not default-shielded).

**One concrete in-tree work item it suggests for us:**
**R-04 — hashrate-bootstrap policy must include a written decision
on AuxPoW.** Either: (a) reserve coinbase-tx commitment bytes for
AuxPoW header now (cheap, future-proof), or (b) write a public "no,
because" memo explaining why merge-mining with another chain doesn't
fit our threat model. Either decision in writing is better than the
current silence.

### §4.3 Dogecoin (DOGE)

**What DOGE does well that we should learn from:**
- **Culture / brand carry.** A meme-coin with no premine, no
  founder reward, perpetual inflation, and a coherent culture has
  outperformed nine out of ten "serious" PoW projects on market
  cap. The lesson isn't "be funny", it's "ship a chain that is
  pleasant to use and let the community own the brand". The DOGE
  Foundation's revival in 2021 (Vitalik Buterin, Jared Birchall on
  the board) is a serious example of how to do this.
- **AuxPoW with LTC** is the textbook how-to for a small chain to
  get permanent hashrate. The technical mechanism is well-
  documented in DOGE 1.14.x source.
- **Per-block DigiShield retarget** has held difficulty stable
  through 100×-hashrate swings.

**What DOGE does badly that we explicitly avoid:**
- **Unbounded supply** — perpetual 10,000 DOGE/block forever was an
  early design accident that became politically unrevisable. Hard
  cap remains our position (BTC parity).
- **Maintenance lag.** DOGE was on Bitcoin Core 0.12 for years.
  Upstream cherry-pick velocity is a quiet but important
  competitive advantage and we should commit to BTC-Core-quarterly
  re-base.
- **No first-class Bech32.** DOGE addresses are still legacy
  P2PKH/P2SH. We start at Bech32 / Bech32m only.

**One concrete in-tree work item it suggests for us:**
**R-15 — quarterly upstream-rebase commitment (`doc/MAINTENANCE.md`
with a published schedule).** Pick a calendar (e.g. within 90 d of
each BTC-Core minor release we evaluate and either cherry-pick or
publish a "why not" memo). This is a process commitment, not code.

### §4.4 Bitcoin Cash (BCH)

**What BCH does well that we should learn from:**
- **BCH-N's `finalizeblock` / `parkblock` operator RPC surface**
  is the model we adopted in v1.1.3 (M-14). The BCH-N
  implementation
  ([`src/rpc/blockchain.cpp` finalizeblock](https://gitlab.com/bitcoin-cash-node/bitcoin-cash-node/-/blob/master/src/rpc/blockchain.cpp))
  is well-tested in production since 2018. Our M-14 implementation
  was deliberately patterned after BCH-N (documented in
  [`B3POW-51-ATTACK-ANALYSIS.md §4.4`](../security/B3POW-51-ATTACK-ANALYSIS.md)).
- **CashTokens** (May 2023) is the cleanest "tokens on top of
  Bitcoin" the cohort has produced. UTXO-native, no separate
  token database, fungible + non-fungible in one design. R-11 must
  consider CashTokens-as-a-pattern.
- **ASERT3-2d retarget** is the most-praised difficulty algorithm
  in the cohort post-2020. Our LWMA-3 is on the same axis.

**What BCH does badly that we explicitly avoid:**
- **Auto-finalization-at-depth-10** was proposed and rejected for
  BCH-N specifically because of the partition-amplifies-to-
  permanent-split footgun. We made the same call and documented
  it. (Confirms our position rather than suggesting a change.)
- **IFP / Infrastructure Funding Plan saga (2020).** A 5 %
  miner-tax-for-dev-fund proposal caused a near-fork and was
  withdrawn. Our zero-dev-tax position is reinforced.
- **Hashrate share with BTC** — same algorithm means the chain
  is permanently in a hashrate-shadow of BTC. This is the
  cautionary tale for *not* picking BTC's algorithm. B3PoW-Scratch
  is the structural answer.
- **BSV / ABC / NODE community fragmentation** — multiple full-
  node implementations diverging led to a hard split. Cherry-pick
  discipline is the hedge.

**One concrete in-tree work item it suggests for us:**
**R-11 — asset-issuance RFC must evaluate CashTokens** alongside
Ravencoin assets and covenants-via-`OP_CTV`. CashTokens has the
maturity advantage and the cleanest UTXO model fit.

### §4.5 Ethereum Classic (ETC)

**What ETC does well that we should learn from:**
- **MESS (Modified Exponential Subjective Scoring)** was the first
  in-production behavioural defence against deep reorgs. The 2020
  attacks killed the chain's reputation but the *defence* design
  is a serious comparative artefact for our M-3 / M-4 / M-5 stack.
- **ECIP process** (https://ecips.ethereumclassic.org) is a
  workable improvement-proposal mechanism for a community without
  a single corporate sponsor. R-06 should look at ECIP as a model
  alongside BIPs.

**What ETC does badly that we explicitly avoid:**
- **Three successful deep-reorg 51%-attacks in 2019–2020** with
  the longest at ~7000 blocks. This is *exactly* the failure mode
  M-4 (`max_reorg_depth = 200`) is designed to prevent. ETC at the
  time had:
  - No reorg-depth cap.
  - Pre-Thanos Ethash with 4 GB+ DAG addressable by rented
    NiceHash hashrate.
  - 13-second blocks (so 7000 blocks ≈ 25 hours of trade-clearing
    history rewritten).
  - Slow exchange reaction (Coinbase eventually moved to 14,000
    confirmations).
- **MESS was eventually disabled** because it interacted badly with
  EIP-1559 gas changes. A behavioural defence that has to be
  removed to ship a feature is fragile. Our defences are
  consensus-level (M-4) plus orthogonal behavioural (M-5, M-7) —
  this layering is the lesson.
- **EVM = perpetual security audit surface.** Every contract is a
  new attack surface; the Parity multisig disasters wiped out
  $300M+. Our "no EVM" position is reinforced.

**One concrete in-tree work item it suggests for us:**
**R-16 — publish a public *post-attack response* tabletop exercise**
based on a hypothetical ETC-style 7000-block reorg attempt against
b3chain. Walk through the runbook
([`RESPONSE-RUNBOOK-51ATTACK.md`](../security/RESPONSE-RUNBOOK-51ATTACK.md))
step by step against a fabricated incident timeline so the team
(and exchanges) see the defences in action. This is a tabletop
exercise document, not code.

### §4.6 Zcash (ZEC)

**What ZEC does well that we should learn from:**
- **Two-organisation governance (ECC + ZF)** provides checks and
  balances most peers lack. Even if we go single-foundation (R-05),
  the ZF "Major Grants" model is a useful template for a *funded*
  improvement process.
- **NU5 / Halo 2 trusted-setup elimination** is the highest-
  craftsmanship cryptographic upgrade any PoW chain has shipped.
  The audit trail (NCC, Trail of Bits) is the gold standard our
  `p3_audit` RFP should target.
- **ZIPs** (https://zips.z.cash) are a clean fork of the BIP
  process focused on consensus changes.

**What ZEC does badly that we explicitly avoid:**
- **20 % dev fund.** Politically unrevisable, regulator-visible,
  exchange-relevant. We maintain 0 %.
- **Default-transparent + opt-in shielded** means most ZEC supply
  sits in transparent addresses — the privacy is theoretical. If
  we ever add privacy (R-12), it must include a UX-and-economics
  analysis of "why would users opt in".
- **Equihash → Halo 2 algorithm transition** stranded the existing
  Equihash ASIC fleet. We commit to *not* doing an algorithm
  transition post-genesis except to fix a documented critical
  cryptographic break.

**One concrete in-tree work item it suggests for us:**
**R-17 — external-audit RFP must explicitly name NCC / Trail of
Bits / Cure53 / Quarkslab as bidders, with a published budget
range.** Currently `p3_audit` produces an RFP package but the bid
solicitation step is not bounded.

### §4.7 Monero (XMR)

**What XMR does well that we should learn from:**
- **Default-on privacy + ASIC-hostile + community-funded** is the
  most ideologically coherent PoW stack in the cohort. Whether or
  not we ever do privacy (R-12), the *coherence* is the lesson:
  every design decision reinforces every other.
- **RandomX (2019)** is the only widely-deployed algorithm in the
  cohort that has held off ASICs for >5 years. The technique is
  random-code-generation against a JIT VM. B3PoW-Scratch chose the
  different (memory-bandwidth-bound) defence; we should still
  reference RandomX in our SPEC's "alternatives considered" section
  as a serious option we did not take.
- **P2Pool (decentralised mining pool)** sidechain-mines XMR
  blocks and decentralises pool concentration without protocol
  changes. R-10 (third-party pool onboarding) should consider
  porting P2Pool to b3chain — the design is open-source.
- **CCS funding model** — community crowdfunding individual work
  items — is the cleanest "no premine, no tax, still get things
  done" pattern in the cohort. R-05 should reference CCS as a
  serious option.

**What XMR does badly that we explicitly avoid:**
- **CEX delistings** (Binance, Kraken-EU, OKX, Bitfinex) over
  privacy compliance is the *forecast* for any chain that adds
  default-shielded privacy in 2024+ regulatory climate. If R-12
  recommends privacy, it must address this with eyes open.
- **Bitcoind-incompatible RPC** means every CEX integration is
  hand-rolled. We inherit bitcoind RPC for free.

**One concrete in-tree work item it suggests for us:**
**R-10 — third-party-pool onboarding kit must include a feasibility
study for porting P2Pool to b3chain.** P2Pool is GPL-2.0; the
adaptation is mostly difficulty-adjustment and PoW hash plumbing.
This is the highest-leverage decentralisation win in the cohort.

### §4.8 Dash (DASH)

**What DASH does well that we should learn from:**
- **ChainLocks** (LLMQ masternode quorum signing the
  longest-chain at depth 1) is the most effective on-chain
  deterministic-finality mechanism in the cohort and effectively
  closes the 51%-attack window. The masternode-collateral
  requirement (1000 DASH ≈ $30k) keeps quorum membership
  Sybil-resistant.
- **Treasury voting** (10 % of subsidy to a masternode-voted
  treasury) is a working example of on-chain governance funding
  R&D without an ICO. Mixed track record but it *works*.
- **DGW v3** difficulty algorithm influenced LWMA-3 design.

**What DASH does badly that we explicitly avoid:**
- **Instamine.** ~1.9 M DASH minted in the first two days due to a
  difficulty-algorithm bug at genesis. Permanent reputational
  drag. Our pre-genesis discipline includes: published deterministic
  genesis-block recipe, public genesis nonce search, and
  third-party verification before mainnet.
- **Masternode collateral = $30k entry barrier** centralises
  consensus-finality power among capitalised holders.
  Philosophically incompatible with our "FPGA hobbyist" positioning.
- **30 % of subsidy not going to miners** (60 % miner / 20 %
  masternode / 20 % treasury) hurts mining economics; this is part
  of why X11 ASIC investment dried up.

**One concrete in-tree work item it suggests for us:**
**(Not building) ChainLocks.** We deliberately reject the
masternode-overlay-for-finality pattern: the 1000-coin collateral,
the quorum politics, and the auto-finalization-at-depth-1 footgun
all violate our threat-model commitments. Documented in **"What we
explicitly are not building"** in
[`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md). The
*operator-pinned* equivalent (M-14) is what we ship.

### §4.9 Kaspa (KAS)

**What KAS does well that we should learn from:**
- **GHOSTDAG BlockDAG** ships sub-second confirmation at the cost
  of explorer / wallet / SPV-client UX complexity that BTC-cohort
  tooling assumes a linear chain. Whether the trade-off is worth it
  is contested; the *engineering* is real.
- **Rust reference client** (`rusty-kaspa`) — written from scratch
  for performance, with `Tokio` async runtime. The b3chain testnet
  monitoring (`contrib/testnet/status-monitor/`) could benefit from
  a similar Rust rewrite eventually (R-19, P2 nice-to-have).
- **KIPs** are an active improvement-proposal process.

**What KAS does badly that we explicitly avoid:**
- **BlockDAG breaks every Bitcoin-tooling assumption** — block
  explorers, SPV wallets, hardware-wallet PSBT, BIP44 derivation,
  all need rework. Tooling-ecosystem cost is enormous. Our linear-
  chain commitment is reinforced.
- **kHeavyHash ASIC adoption** was as rapid as SHA-256d (IceRiver,
  Bitmain KS-series within 18 months of mainnet). "ASIC-resistant"
  was not the design goal but the marketing implied it. Our SPEC's
  "FPGA-economical, not ASIC-proof" honesty (per
  [`README.md`](../../README.md)) is the contrast.

**One concrete in-tree work item it suggests for us:**
**(Not building) BlockDAG / GHOSTDAG.** We deliberately reject DAG
consensus: the linear-chain assumption is load-bearing for
Bitcoin tooling parity (BIPs, BIP-PSBTs, SPV wallets, hardware
wallets, block explorers, accounting software, …). Documented in
**"What we explicitly are not building"** in
[`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md).

### §4.10 Ravencoin (RVN)

**What RVN does well that we should learn from:**
- **Asset issuance UX** is the most thought-through "tokens on a
  Bitcoin-style chain" experiment in the cohort. The
  fungible / non-fungible / restricted / sub-asset / messaging /
  voting taxonomy is good design.
- **Fair launch (no premine)** carried real cultural weight in the
  RVN community and tier-1 exchanges noted it positively. Our zero-
  premine commitment should be marketed the same way.

**What RVN does badly that we explicitly avoid:**
- **51%-attack-vulnerable to NiceHash.** ~$5k/h rented KawPow
  hashrate is enough to attack RVN (Crypto51 estimate). The chain
  was attacked three times in 2020. Our M-4 (`max_reorg_depth =
  200`) is the structural answer.
- **Algorithm tweaks under attack.** RVN changed PoW algorithm
  (X16R → X16Rv2 → KawPow) multiple times in response to
  ASIC/FPGA pressure. Every change strands hardware and adds
  consensus-implementation risk. Our SPEC discipline (single
  algorithm, four CI-gated implementations, no in-flight
  redesign) is the contrast.
- **Restricted-asset KYC tagging** is centralisation creep.

**One concrete in-tree work item it suggests for us:**
**R-11 — asset-issuance RFC must evaluate the Ravencoin asset
opcode model** as one of the alternatives (alongside CashTokens
commitment-based, covenants-via-`OP_CTV`, and "no, defer to
inscriptions / L2"). RVN's UX is the best evidence either way of
"what users actually need from base-layer asset issuance".

## §5. Cross-cutting recommendations

This section restates the recommendation classes that emerged from
§4, organised by theme, with one-line rationale and a pointer into
[`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md). Numbering inside
each subsection is rationale-ordered, not priority-ordered (priorities
live in the roadmap's P0 / P1 / P2 tiers).

### §5.1 Hashrate-bootstrap mechanisms

**Theme.** Every small-cap PoW chain in the cohort that survived
weeks 0–12 did so by either: (a) merge-mining with a larger chain
that shares the algorithm (DOGE on LTC), (b) hostile-environment-
hardened consensus (ETC after the attacks, with MESS and exchange
confirmations), or (c) being unattackable-by-default because the
algorithm has no rentable hashrate (XMR via RandomX). b3chain falls
into category (c) by construction (B3PoW-Scratch is not on
NiceHash, no FPGA rental marketplace at b3chain-relevant scale) but
"unattackable by default" is true only as long as the *attacker*
also has to bootstrap an FPGA fleet.

**Recommendations:**

1. **(R-04) Hashrate-bootstrap policy.** Pick one of:
   (a) AuxPoW with another B3PoW-Scratch-compatible chain
       (would require coordinating launch with a peer — high cost,
       high payoff, low feasibility);
   (b) Faucet-funded mining-subsidy curve over weeks 0–12 —
       reference miner gets a tracked top-up out of testnet faucet
       budget to keep aggregate hashrate above a floor;
   (c) "Do nothing structural — rely on M-4 + algorithm uniqueness"
       — written decision documenting the bet.
   *Whichever is picked, the decision must be in writing before
   mainnet genesis.*
2. **(R-09) Seed-node growth target.** Mainnet genesis should
   ship with ≥8 geographically-distributed seed nodes (vs 3
   testnet). Distribute via the conventional DNS-seeder mechanism
   (`src/kernel/chainparams.cpp::vSeeds`).
3. **(R-10) Third-party-pool onboarding kit.** Operator-facing
   docs + Docker compose for `b3pool` reference fork + P2Pool
   feasibility study (per §4.7).

### §5.2 Finality / 51%-defense additions

**Theme.** Our M-1 .. M-14 stack is competitive with or ahead of
every peer on documented threat-model rigour. The recommendations
here are about *operational* extensions, not new consensus rules.

**Recommendations:**

1. **(R-16) Public tabletop exercise** walking through an ETC-style
   7000-block reorg attempt against b3chain step by step (per §4.5).
2. **(R-17) Bound the audit RFP** with named bidders and a
   published budget range (per §4.6).
3. **(R-18) Watcher-detector deployment runbook.** The
   `contrib/monitoring/51attack-watch.py` script needs a
   "production deployment on the seed-host fleet" runbook —
   systemd unit, alerting channel, on-call rotation.
4. **(Not building) ChainLocks** (per §4.8) — masternode overlay
   rejected. Logged in roadmap "not building" section.
5. **(Not building) BlockDAG / GHOSTDAG** (per §4.9) — linear chain
   load-bearing. Logged in roadmap.
6. **(Not building) Auto-finalization-at-depth-10** (per §4.4) —
   partition-amplifies-to-permanent-split footgun. Logged in
   roadmap. M-14 (operator-pinned) is the alternative we shipped.

### §5.3 Privacy posture

**Theme.** No privacy in v1 is the right call for launch (listing
risk, audit surface, novelty stacking). The recommendation is to
*publish the decision* and *publish the upgrade decision tree* so
prospective users know what they're getting.

**Recommendations:**

1. **(R-12) Privacy upgrade RFC.** Evaluate Confidential
   Transactions (a la Elements / Liquid), Mimblewimble extension
   block (a la LTC-MWEB), Taproot+CoinJoin patterns (BTC-style,
   wallet-level only), silent-payments (BIP352 on b3chain). Decide
   in writing — either "we ship X in v2.0" or "we deliberately
   defer indefinitely because Y".
2. **(R-12a) Document "no privacy" as a feature.** For 2024–2026
   regulatory environment, "listing-friendly transparent chain
   with strong settlement guarantees" is itself a sellable
   positioning. Say it on the homepage and link to the RFC.

### §5.4 Programmability / asset issuance

**Theme.** This is the single most-asked exchange-listing-committee
question b3chain will face. A written decision either way is far
more valuable than the current silence.

**Recommendations:**

1. **(R-11) Asset-issuance RFC.** Evaluate:
   (a) Ravencoin-style asset opcodes (rich, mature, but
       consensus-level surface area);
   (b) CashTokens-style UTXO commitments (clean, BCH-tested since
       2023);
   (c) Covenants-via-`OP_CTV` / `OP_CAT` (would require BIP
       activation on b3chain ahead of BTC — risky);
   (d) "Inscriptions-equivalent" (no consensus change — fits BTC
       parity philosophy but cedes UX ground to RVN / BCH).
2. **(R-13) Lightning compatibility statement + reference channel
   demo on testnet.** Lightning works on b3chain in principle (full
   BTC script + Taproot parity); proving it works in practice with
   one published channel-open + sample HTLC payment on testnet
   pre-mainnet would be a major credibility move.

### §5.5 Throughput

**Theme.** Defer. Mirror Bitcoin. Do not increase block size /
weight in v1.

**Recommendations:**

1. **(Not building, by default) Base-layer block-size increase.**
   BCH's 32 MB blocks did not deliver tier-1 exchange parity. Our
   answer to "is 7 tps enough?" is "Lightning" (R-13).
2. **(R-13) Lightning compatibility proof point** — see §5.4.

### §5.6 Ecosystem accelerants

**Theme.** Bitcoin-Core fork status gives us 90 % of bitcoind
compatibility for free; the remaining 10 % is what an
integration-engineer at a tier-1 CEX will ask about on day one of
listing review.

**Recommendations:**

1. **(R-01) Exchange-grade RPC parity & integration kit.**
   Single most important P0 item. Includes: ZMQ topic compatibility
   audit, REST API parity vs bitcoind, address-index daemon
   (`addrindex` / `electrs` port), Replace-By-Fee policy
   documentation, mempool eviction documentation, fee-estimation
   documentation, ChainTip notification webhook (or doc'd
   alternative), example custody integration code in Python +
   TypeScript.
2. **(R-02) Exchange-listing handbook.** A `doc/exchanges/`
   directory: ticker (`B3`), decimals (8), HRP (`b3`), genesis
   block hash, checkpoint hash, contact for listing security
   review, network upgrade calendar.
3. **(R-03) Hardware-wallet support matrix + integration PRs.**
   Ledger BOLOS app and Trezor firmware are open-source; b3chain
   needs a fork PR for each, with derivation path BIP-44/49/84/86
   coin type registered at SLIP-0044
   ([slip-0044 GitHub](https://github.com/satoshilabs/slips/blob/master/slip-0044.md)).
4. **(R-07) Production block-explorer SLA.** At least two
   independent explorers, multi-region, ≥99 % uptime SLA. Today:
   one explorer co-located on `seed1` per `.cursor/rules/git-push-policy.mdc`
   — a single point of failure.
5. **(R-08) Live-data snapshot refresh discipline.** This document's
   §3 cells should be re-snapshotted quarterly. Add to maintenance
   calendar.

### §5.7 Governance & funding

**Theme.** No premine is a strength we keep. No published process
or funding is a question mark we should remove.

**Recommendations:**

1. **(R-05) Funding-model statement.** A short
   `doc/FUNDING.md` saying explicitly: (a) no premine, no founders'
   reward, no dev tax (current state); (b) how ongoing development
   is funded (sponsorships, grants, voluntary CCS-style work-item
   funding, …); (c) what the conflict-of-interest policy is for
   contributors paid by external sponsors. Even "we are
   unsponsored volunteers" is a sellable statement once written
   down.
2. **(R-06) BIP / B3IP process.** Publish
   `doc/bips/README.md` describing the b3chain improvement-proposal
   process. Renumber existing M-1 .. M-14 as B3IPs (B3IP-0001
   `ITER_MUL` fix, B3IP-0003 LWMA-3, B3IP-0014 finalize/park, …).
3. **(R-14) Security disclosure policy + security.txt.**
   Already partially in `p3_audit` launch-package todo; this
   recommendation is the *exchange-visible* surface — security.txt
   hosted at `https://b3chain.org/.well-known/security.txt`, GPG
   key for security@b3chain.org, ≤72h acknowledgement SLA, public
   CVE-issuance commitment for fixed vulnerabilities.

## §6. Path-to-top-10 scoreboard

Single closing table. Each row is one of the eleven axes from §3.
Scoring is 0–5, with the calibration:

- **0** = absent / not implemented.
- **1** = minimum-viable / pre-mainnet / experimental.
- **2** = shipped but bottom-quartile vs peer cohort.
- **3** = peer-median.
- **4** = peer-cohort top-quartile.
- **5** = best-in-cohort, with no peer ahead of us on this axis.

Three columns:

- **B3 today** — b3chain at snapshot date (2026-05-19, pre-mainnet,
  pre-launch).
- **B3 post-roadmap** — b3chain after executing all P0+P1 items in
  [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md). P2 items are
  ignored (their impact on the score is by definition minor).
- **Cohort median** — the median score across the 10 peers at
  snapshot date.

Sources for the cohort-median scoring are the same matrices in §3.
Scoring is unavoidably subjective; the row-rationale notes are
provided so the reader can re-score from their own priors.

| # | Axis | B3 today | B3 post-roadmap | Cohort median | Row rationale |
|---|---|---|---|---|---|
| 1 | Consensus algorithm rigour (§3.1) | **5** | 5 | 3 | Four CI-gated implementations, FPGA-economical novel primitive; ahead at baseline; roadmap doesn't move this further. |
| 2 | Block production parameters (§3.2) | **3** | 3 | 3 | LWMA-3 + 21M cap + BTC-parity halving is solidly median. KAS / DASH / ZEC retargets are equivalent. |
| 3 | Throughput & latency (§3.3) | **2** | 3 | 3 | 7 tps base layer + Lightning compatible. R-13 (LN proof point) moves us to median. KAS / BCH stay ahead. |
| 4 | Programmability (§3.4) | **2** | 3 | 3 | BTC parity = median (no native assets). R-11 lands either at "asset issuance shipped" (4) or "explicit defer published" (3). Conservative: 3. |
| 5 | Privacy (§3.5) | **1** | 2 | 3 | No privacy = below median (XMR / ZEC / DASH / LTC-MWEB pull median up). R-12 + R-12a publishes the position; small score uptick from "absent" to "deliberate". |
| 6 | Decentralization (§3.6) | **1** | 3 | 3 | Pre-mainnet at snapshot; post-roadmap brings us to median via R-04 + R-09 + R-10. Reaching 4 (top-quartile) requires sustained mainnet operation, out of roadmap scope. |
| 7 | Security & 51%-attack posture (§3.7) | **4** | 5 | 2 | M-1 .. M-14 already top-quartile on documented threat-model rigour. R-16 (tabletop) + R-18 (watcher deployment) close the gap to "best in cohort". |
| 8 | Tokenomics (§3.8) | **4** | 4 | 3 | Zero premine + zero dev tax + hard cap is top-quartile; no roadmap items needed. |
| 9 | Governance (§3.9) | **1** | 3 | 3 | No published process at snapshot; R-05 + R-06 + R-14 bring us to median (BIP + funding + security disclosure). Top-quartile requires multi-org governance (ZEC pattern) — out of scope. |
| 10 | Ecosystem (§3.10) | **1** | 3 | 3 | Zero CEX / wallet / pool / market at snapshot. R-01 + R-02 + R-03 + R-07 + R-10 close to median. Top-quartile = mainnet operational + multi-year listings, out of scope. |
| 11 | Operator / UX surface (§3.11) | **3** | 4 | 3 | Bech32-only + distinct ports/HRP is already top-half; R-03 (hardware-wallet derivation paths) finalises the UX surface to top-quartile. |

**Aggregate (mean across 11 axes):**

| | Score |
|---|---|
| B3 today | **2.5 / 5** |
| B3 post-roadmap | **3.5 / 5** |
| Cohort median | **2.9 / 5** |

**Interpretation.**

- "B3 today" is *below* the cohort median because three high-weight
  ecosystem axes (privacy, decentralization, ecosystem) are at 1 — a
  pre-mainnet chain by definition.
- "B3 post-roadmap" is *one full tier above* cohort median — the
  axis where we go from "absent" to "deliberate" plus the axis where
  our threat-model rigour goes from "top-quartile" to "best in cohort"
  do most of the work.
- Reaching "best in cohort" overall (≥4.0) would require either
  (a) a sustained mainnet operating record over multiple years
  (decentralization, ecosystem axes) or (b) shipping a privacy
  upgrade (R-12 outcome dependent). Neither is in the roadmap by
  design; the roadmap is what we can do *before* needing operating
  history.

## §7. References

Citation tags used in §3 / §4. URLs were live at snapshot date
(2026-05-19); R-08 in the roadmap is the recurring re-snapshot
discipline.

### Per-chain reference docs

- **[BTC-1]** Bitcoin Core, [`src/kernel/chainparams.cpp`](https://github.com/bitcoin/bitcoin/blob/master/src/kernel/chainparams.cpp); [bitcoin.org/bitcoin.pdf](https://bitcoin.org/bitcoin.pdf) (Nakamoto 2008).
- **[BTC-3]** Bitcoin throughput estimate from average tx size (~250 vB) × Segwit weight (4M / 250) ≈ 16k tx/block / 600 s ≈ 27 tps theoretical; ~7 tps observed sustained per [statoshi.info](https://statoshi.info).
- **[BTC-4]** Mining pool concentration: [mempool.space/mining](https://mempool.space/mining).
- **[BTC-5]** Hashrate: [blockchain.info/charts/hash-rate](https://www.blockchain.com/explorer/charts/hash-rate).
- **[LTC-1]** Litecoin Core, [`src/chainparams.cpp`](https://github.com/litecoin-project/litecoin/blob/master/src/chainparams.cpp); [LIP-0002 MWEB](https://github.com/litecoin-project/lips/blob/master/lip-0002.mediawiki).
- **[LTC-2]** Pool concentration: [litecoinpool.org/stats](https://www.litecoinpool.org/stats).
- **[LTC-5]** Hashrate: [bitinfocharts.com/litecoin](https://bitinfocharts.com/litecoin/).
- **[DOGE-1]** Dogecoin Core, [`src/chainparams.cpp`](https://github.com/dogecoin/dogecoin/blob/master/src/chainparams.cpp); [Dogecoin AuxPoW BIP](https://en.bitcoin.it/wiki/Merged_mining_specification).
- **[DOGE-2]** Pool concentration inherited from LTC AuxPoW; [miningpoolstats.stream/dogecoin](https://miningpoolstats.stream/dogecoin).
- **[DOGE-5]** Hashrate: [bitinfocharts.com/dogecoin](https://bitinfocharts.com/dogecoin/).
- **[BCH-1]** Bitcoin Cash Node, [`src/chainparams.cpp`](https://gitlab.com/bitcoin-cash-node/bitcoin-cash-node/-/blob/master/src/chainparams.cpp).
- **[BCH-2]** ASERT3-2d difficulty algorithm, [`upgrade activation Nov 2020`](https://gitlab.com/bitcoin-cash-node/bitcoin-cash-node/-/blob/master/doc/release-notes/release-notes-22.2.0.md).
- **[BCH-3]** CashTokens (BCH May 2023), [CHIP-2022-02-CashTokens](https://github.com/cashtokens/cashtokens).
- **[BCH-4]** Pool concentration: [coin.dance/blocks](https://coin.dance/blocks).
- **[BCH-5]** Hashrate: [bitinfocharts.com/bitcoin%20cash](https://bitinfocharts.com/bitcoin%20cash/).
- **[BCH-N]** BCH-N `finalizeblock` / `parkblock` RPC reference: [`src/rpc/blockchain.cpp`](https://gitlab.com/bitcoin-cash-node/bitcoin-cash-node/-/blob/master/src/rpc/blockchain.cpp).
- **[ETC-1]** Etchash spec [ECIP-1099](https://ecips.ethereumclassic.org/ECIPs/ecip-1099); [core-geth](https://github.com/etclabscore/core-geth).
- **[ETC-2]** ECIP-1017 "5M20" Thanos monetary policy: [ECIP-1017](https://ecips.ethereumclassic.org/ECIPs/ecip-1017).
- **[ETC-3]** Coinbase ETC confirmation policy post-attacks: [Coinbase blog Sept 2020](https://www.coinbase.com/blog/ethereum-classic-51-attack).
- **[ETC-4]** Pool concentration: [2miners.com/etc-pools](https://2miners.com/etc-mining-pools).
- **[ETC-5]** Hashrate: [bitinfocharts.com/ethereum%20classic](https://bitinfocharts.com/ethereum%20classic/).
- **[ETC-Att]** ETC 51%-attack history: [Coinbase post-mortem Sept 2020](https://www.coinbase.com/blog/ethereum-classic-51-attack), [Slowmist Aug 2020 report](https://slowmist.medium.com/the-analysis-and-q-a-of-etc-51-attack-c0ce1c8cd998).
- **[ETC-MESS]** MESS (Modified Exponential Subjective Scoring): [ECIP-1100](https://ecips.ethereumclassic.org/ECIPs/ecip-1100).
- **[ZEC-1]** Zcash, [`src/chainparams.cpp`](https://github.com/zcash/zcash/blob/master/src/chainparams.cpp).
- **[ZEC-2]** Blossom NU2 reduced block time to 75 s: [ZIP-208](https://zips.z.cash/zip-0208).
- **[ZEC-3]** Halo 2 / NU5 (May 2022): [ZIP-224](https://zips.z.cash/zip-0224), [Halo paper](https://eprint.iacr.org/2019/1021).
- **[ZEC-4]** Pool concentration: [miningpoolstats.stream/zcash](https://miningpoolstats.stream/zcash).
- **[ZEC-5]** Hashrate: [bitinfocharts.com/zcash](https://bitinfocharts.com/zcash/).
- **[XMR-1]** Monero, [`src/cryptonote_config.h`](https://github.com/monero-project/monero/blob/master/src/cryptonote_config.h); [RandomX spec](https://github.com/tevador/RandomX/blob/master/doc/specs.md).
- **[XMR-2]** Tail emission: [Monero StackExchange tail emission Q](https://monero.stackexchange.com/questions/61/tail-emission); [`src/cryptonote_config.h` `FINAL_SUBSIDY_PER_MINUTE`](https://github.com/monero-project/monero/blob/master/src/cryptonote_config.h).
- **[XMR-3]** LWMA-1: [Zawy12 GitHub LWMA](https://github.com/zawy12/difficulty-algorithms/issues/3).
- **[XMR-4]** P2Pool: [github.com/SChernykh/p2pool](https://github.com/SChernykh/p2pool); pool concentration [miningpoolstats.stream/monero](https://miningpoolstats.stream/monero).
- **[XMR-5]** Hashrate: [bitinfocharts.com/monero](https://bitinfocharts.com/monero/).
- **[DASH-1]** Dash, [`src/chainparams.cpp`](https://github.com/dashpay/dash/blob/master/src/chainparams.cpp); X11 spec [`src/crypto/`](https://github.com/dashpay/dash/tree/master/src/crypto).
- **[DASH-2]** ChainLocks (DIP-0008): [DIP-0008 ChainLocks](https://github.com/dashpay/dips/blob/master/dip-0008.md).
- **[DASH-4]** Pool concentration: [miningpoolstats.stream/dash](https://miningpoolstats.stream/dash).
- **[DASH-5]** Hashrate: [bitinfocharts.com/dash](https://bitinfocharts.com/dash/).
- **[DASH-IM]** Instamine 2014: [Evan Duffield post-mortem on Bitcointalk](https://bitcointalk.org/index.php?topic=421615.msg4641991#msg4641991).
- **[DASH-CL]** ChainLocks: see [DASH-2].
- **[KAS-1]** Kaspa whitepaper and rusty-kaspa source: [github.com/kaspanet/rusty-kaspa](https://github.com/kaspanet/rusty-kaspa); [research paper "GHOSTDAG"](https://eprint.iacr.org/2018/104).
- **[KAS-2]** Crescendo 1-block/second activation: [KIP-9 / KIP-10](https://github.com/kaspanet/kips).
- **[KAS-4]** Pool concentration: [miningpoolstats.stream/kaspa](https://miningpoolstats.stream/kaspa).
- **[KAS-5]** Hashrate: [kas.fyi/network](https://kas.fyi/network).
- **[RVN-1]** Ravencoin, [`src/chainparams.cpp`](https://github.com/RavenProject/Ravencoin/blob/master/src/chainparams.cpp); [KawPow spec](https://github.com/RavenCommunity/kawpowminer).
- **[RVN-2]** RVN asset opcodes: [Ravencoin asset issuance docs](https://github.com/RavenProject/Ravencoin/blob/master/assets/asset_docs.md).
- **[RVN-4]** Pool concentration: [miningpoolstats.stream/ravencoin](https://miningpoolstats.stream/ravencoin).
- **[RVN-5]** Hashrate: [bitinfocharts.com/ravencoin](https://bitinfocharts.com/ravencoin/).
- **[RVN-Att]** RVN 51%-attack history: [Bittrex Nov 2020 incident report](https://bittrex.zendesk.com/hc/en-us/articles/360057354791); [Crypto51 RVN page](https://www.crypto51.app/coins/rvn.html).
- **[Crypto51]** Hashrate-rental cost-to-attack estimates: [crypto51.app](https://www.crypto51.app).

### b3chain reference docs

- **[B3-1]** [`README.md`](../../README.md), [`src/kernel/chainparams.cpp`](../../src/kernel/chainparams.cpp), [`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md).
- **[B3-2]** `max_reorg_depth = 200` (M-4): [`B3POW-51-ATTACK-ANALYSIS.md §1.2`](../security/B3POW-51-ATTACK-ANALYSIS.md).
- **[B3-3]** LWMA-3 retarget (M-3): `src/pow/lwma3.{h,cpp}` per [`B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md).
- **[B3-CHL]** v1.1.3 operator-pinned chain recovery RPCs (`finalizeblock` / `unfinalizeblock` / `parkblock` / `unparkblock` / `getfinalizedblockhash`): [`../CHANGELOG.md`](../CHANGELOG.md).

### Cross-cutting references

- Eyal & Sirer, *Majority is not Enough: Bitcoin Mining is Vulnerable*, [Financial Crypto 2014](https://www.cs.cornell.edu/~ie53/publications/btcProcFC.pdf).
- Heilman et al., *Eclipse Attacks on Bitcoin's Peer-to-Peer Network*, [USENIX Security 2015](https://www.usenix.org/conference/usenixsecurity15/technical-sessions/presentation/heilman).
- Bonneau, Felten et al., *SoK: Research Perspectives on Bitcoin and Cryptocurrencies*, [IEEE S&P 2015](https://www.ieee-security.org/TC/SP2015/papers/6949a104.pdf).
- SatoshiLabs SLIP-0044 (coin-type registry): [github.com/satoshilabs/slips](https://github.com/satoshilabs/slips/blob/master/slip-0044.md).

### Internal b3chain documents cited from this report

- [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md) — 51%-attack threat model (M-1 .. M-14).
- [`doc/security/51-ATTACK-RESPONSE-SUMMARY.md`](../security/51-ATTACK-RESPONSE-SUMMARY.md) — one-page condensed response.
- [`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](../security/RESPONSE-RUNBOOK-51ATTACK.md) — incident-response runbook.
- [`doc/security/51-MONITORING-OPS.md`](../security/51-MONITORING-OPS.md) — detection wiring.
- [`doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md) — algorithm spec + security argument.
- [`doc/CHANGELOG.md`](../CHANGELOG.md) — project history including v1.1.3 finalize/park RPCs.
- [`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) — formal B3PoW-Scratch v1.1 spec.
- [`contrib/monitoring/51attack-watch.py`](../../contrib/monitoring/51attack-watch.py) — watcher detector script.
- `.cursor/plans/b3pow-scratch_launch_package_c6f10175.plan.md` — in-flight launch-package plan (de-dupe reference for roadmap).

### Companion deliverable

- [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) — prioritised in-tree work items closing the gaps identified in this report.
