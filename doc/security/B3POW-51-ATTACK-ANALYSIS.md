# B3PoW-Scratch v1.1 — 51% Attack Evaluation

**Status:** draft v1.0
**Author:** b3chain
**Last updated:** 2026-05-19
**Companion documents:**
[`SECURITY-AUDIT.md`](SECURITY-AUDIT.md),
[`SECURITY-INHERITANCE.md`](SECURITY-INHERITANCE.md),
[`SECURITY-ROADMAP.md`](SECURITY-ROADMAP.md),
[`RESPONSE-RUNBOOK-51ATTACK.md`](RESPONSE-RUNBOOK-51ATTACK.md),
[`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md).

---

## 1. Executive summary

This document is the explicit 51%-attack threat model for **B3PoW-Scratch
v1.1** ([SPEC.md](../../contrib/miner/b3miner-rtl/SPEC.md)), the
memory-hard BLAKE3 proof-of-work that replaces Bitcoin's SHA-256d in
b3chain. It quantifies risk in both the **launch / bootstrap phase**
(weeks 0–12 after genesis, where honest hashrate is by definition low)
and the **steady-state phase** (mature network with diverse miners),
and lists the concrete mitigations that ship in this repo.

### 1.1 Bottom-line risk

| Phase | Worst-case attacker share | Confidence in honest survival | Mitigations status |
|---|---|---|---|
| Bootstrap (weeks 0–12) | Single competing FPGA bank can reorg arbitrarily deep | Low without mitigations | **Defended** by Phase 3 (this plan) |
| Maturity (months 6+) | 30–40% attacker share enables selfish mining; >50% trivially | Acceptable with mitigations | **Defended** by Phase 4 (this plan) |
| ASIC era (year 2+) | A 7 nm tape-out (~$5–20M NRE) produces ~4× the per-die hashrate of FPGA | Acceptable provided no monopoly tape-out | Mitigation = open ASIC reference design + on-chip-memory-bound algorithm |

The single biggest concrete risk is **launch-phase hashrate
concentration**: the algorithm is GPU-hostile by design (so GPU farms
cannot repurpose), and the only economic mining hardware on day 1 is the
b3chain reference board (B3Miner-1 / KU5P). For the first weeks the
honest hashrate is plausibly one to a handful of operators. Without the
mitigations below, a competitor with comparable FPGA inventory can reorg
arbitrarily deep. With them, deep reorgs cost both protocol-level ban
score (Phase 3.4) and a `max_reorg_depth = 200` consensus rejection
(Phase 3.3).

### 1.2 What we ship to defend

| ID | Mitigation | Scope | Lives in |
|---|---|---|---|
| M-1 | `ITER_MUL[7]` distinctness fix | Pre-genesis hard fork | [`src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp) |
| M-2 | BIP94 timewarp enforcement on mainnet | Pre-genesis hard fork | [`src/kernel/chainparams.cpp`](../../src/kernel/chainparams.cpp) |
| M-3 | LWMA-3 difficulty algorithm | Pre-genesis hard fork | `src/pow/lwma3.{h,cpp}` (new) |
| M-4 | `max_reorg_depth = 200` consensus rule | Pre-genesis hard fork | [`src/validation.cpp`](../../src/validation.cpp) + [`src/consensus/params.h`](../../src/consensus/params.h) |
| M-5 | Depth-aware ban-score in HEADERS handler | Network behavioural | [`src/net_processing.cpp`](../../src/net_processing.cpp) |
| M-6 | 2-tier pinned LRU cache | Behavioural | [`src/crypto/b3pow_cache.{h,cpp}`](../../src/crypto/b3pow_cache.h) |
| M-7 | Depth-asymmetric verifier budget (50 / 25 / 10 ms) | Network behavioural | [`src/pow.cpp`](../../src/pow.cpp) |
| M-8 | `-assumevalidcheckpoints=path` operator-controlled checkpoint stub (OFF by default) | Operational | [`src/validation.cpp`](../../src/validation.cpp) |
| M-9 | Default `-maxconnections` raised 125 → 200 on mainnet | Operational | [`src/net.h`](../../src/net.h) defaults |
| M-10 | `-paranoid-headers-sync` flag (3-peer confirmation requirement) | Operational | [`src/net_processing.cpp`](../../src/net_processing.cpp) |
| M-11 | Address-derivation uniformity CI gate | Pre-genesis hard gate | `ref/tests/test_address_uniformity.py` (new) |
| M-12 | Diffusion-bound sketch + SPEC §8.F | Documentation gate | [`SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) |

### 1.3 What we do not claim

- **Not "ASIC-proof"**. B3PoW-Scratch is FPGA-economical and
  on-chip-memory-bound, not magically ASIC-resistant. Section 3.4
  explicitly models the 7 nm tape-out break-even.
- **Not "unattackable"**. Any low-hashrate chain is reorganisable by
  someone with enough hashrate. We engineer to make the cost large and
  the blast radius bounded — not to make the cost infinite.
- **No federation / no checkpoint key ceremony**. Per
  [`SECURITY-ROADMAP.md §7`](SECURITY-ROADMAP.md), maintainer-signed
  checkpoints are deferred. Section 4.3 ships only the *code path*
  (off by default).

---

## 2. Scope and vocabulary

This document is the threat-model layer above the algorithm
specification. Definitions used throughout:

- **51% attack**: a strategy where a single party controls enough proof
  of work to reorder, censor, or rewrite history. The "51%" is the
  textbook majority threshold; selfish mining lowers the practical
  threshold to ~25–33%.
- **Hashrate share (α)**: attacker's fraction of total network hashrate.
- **Confirmation depth (k)**: number of blocks built atop a transaction
  the merchant requires before treating the payment as final.
- **Double-spend probability P(k, α)**: see Bitcoin §11 (Nakamoto 2008),
  approximating Poisson race between honest and attacker chains.
- **Selfish mining**: attacker withholds private chain, releases
  strategically; Eyal-Sirer 2014 (Financial Crypto, doi.org/10.1007/978-3-662-47854-7_28).
- **Time-warp attack**: manipulate `nTime` to lower difficulty over a
  retarget window; BIP94 mitigation by Murch and Zawy.
- **Eclipse attack**: monopolise a victim's P2P connections to feed
  false chain views; Heilman et al. 2015 (USENIX Security).
- **Selfish-mining propagation advantage (γ)**: fraction of honest
  miners that adopt the attacker's tip in a race (γ = 0 is worst-case
  for attacker, γ = 1 is best).
- **Finality**: probability that a confirmed block stays in the chain
  forever. Bitcoin-style PoW has no absolute finality; it has
  *probabilistic* finality that grows with depth.

References:
- Nakamoto, *Bitcoin: A Peer-to-Peer Electronic Cash System*, [bitcoin.org/bitcoin.pdf](https://bitcoin.org/bitcoin.pdf) §11.
- Eyal, Sirer, *Majority is not Enough: Bitcoin Mining is Vulnerable*, Financial Cryptography 2014.
- Bonneau, Felten et al., *SoK: Research Perspectives on Bitcoin and Cryptocurrencies*, IEEE S&P 2015.
- Heilman et al., *Eclipse Attacks on Bitcoin's Peer-to-Peer Network*, USENIX Security 2015.

---

## 3. Hashrate landscape (B3PoW-Scratch v1.1)

The algorithm's hardware ranking is the foundation of every cost
estimate below. Numbers extend [SPEC §8.D](../../contrib/miner/b3miner-rtl/SPEC.md):

### 3.1 Per-device hashrate

| Device | Per-iter latency | Hash time | Hashrate | Power | Cost (cap-ex) |
|---|---|---|---|---|---|
| CPU Ryzen 9 7950X (1 core) | ~80 ns × 8 = ~640 ns | ~1.3 ms | 770 H/s | ~6 W/core | n/a (existing) |
| CPU Ryzen 9 7950X (16-core) | parallel | — | ~12 KH/s | 230 W | $700 |
| GPU RTX 4090 (memory-stalled) | ~150 ns × 8 = ~1.2 µs | ~2.5 ms | ~400 H/s effective | 450 W | $1,800 |
| FPGA KU5P (B3Miner-1) | ~24 ns @ 250 MHz, 6 cycles | ~49 µs | 20.4 KH/s/board | ~75 W | $1,500–2,500 |
| ASIC 7 nm (projected) | ~6 ns | ~12 µs | 83 KH/s/die | ~30 W | $5–20M NRE + $50/die at volume |

CPUs and GPUs are not economic miners; FPGAs are; ASICs would dominate
if anyone tapes out. The asymmetry between FPGA and GPU is the
intended outcome: 1 MB > GPU L1 (128 KB on RTX 4090) and the 8-way
sequential read-modify-write breaks GPU warp parallelism.

### 3.2 Memory-hardness fallback

Per [SPEC §8.C](../../contrib/miner/b3miner-rtl/SPEC.md), reduced-memory
attackers pay a recompute penalty on every miss. Reproduced (per the
Phase 1 simulators, where applicable):

| Attacker memory | Expected miss penalty | Effective hashrate (vs 1 MB) |
|---|---|---|
| 1 MB (honest) | 0× | 1.0× |
| 512 KB | ~2× | ~0.5× |
| 256 KB | ~4× | ~0.25× |
| 128 KB | ~8× | ~0.125× |

This is **not** Argon2-strength memory hardness. It is sufficient to
make full-pad mining strictly more profitable than reduced-pad
mining, not sufficient to deny a determined attacker a workable cost
floor.

### 3.3 Network hashrate scenarios

Cost models below use three scenarios:

| Scenario | Network hashrate | Operator count (est.) | Description |
|---|---|---|---|
| Launch | 100 KH/s | 5 (≈25 FPGA boards) | Weeks 0–4 after genesis |
| Early growth | 1 MH/s | 30 (≈250 boards) | Months 1–6 |
| Maturity | 50 MH/s | 200 (mixed FPGA + ASIC) | Year 2+ |

These are not predictions, they are scenarios to attach $-cost numbers
to. The Phase 1 simulators emit raw CSVs at
[`contrib/testing/audit/results/r0/`](../../contrib/testing/audit/results) for
each.

### 3.4 ASIC break-even

A 7 nm ASIC with the [SPEC §8.D](../../contrib/miner/b3miner-rtl/SPEC.md)
projected 83 KH/s/die produces 4× the FPGA throughput at ~40% of the
power. Break-even depends on:

- NRE cost: $5M (low-end, mature 7 nm) to $20M+ (TSMC N5/N3 leading-edge).
- Mass cost: ~$50/die at high volume.
- Network hashrate at tape-out: at 1 MH/s the entire network is
  economically attackable by a single ASIC vendor; at 50 MH/s the same
  vendor can produce ~30–50% share.

The blast radius of an ASIC monopoly is bounded by `max_reorg_depth =
200` (M-4) and depth-aware ban score (M-5). It is **not** bounded by
the algorithm itself.

---

## 4. Threat model

### 4.1 Attacker capabilities

A capability is a triple (hashrate share, network position, time horizon, capital).

| Tier | Hashrate share | Network position | Time horizon | Capital | Realism |
|---|---|---|---|---|---|
| T0 — Sybil DoS | 0% | Many P2P peers | Hours | $1k | High |
| T1 — Eclipse | 0% | Surround one victim | Hours–days | $10k | Medium |
| T2 — Botnet miner | 1–5% | Many peers | Days | $100k | Low (GPU-hostile) |
| T3 — FPGA bank | 20–50% | Few peers | Weeks | $1M–$5M | High at launch |
| T4 — ASIC vendor | 50–80% | Pool position | Months | $10M+ | Medium post-tape-out |
| T5 — Nation-state | >80% | Network position | Open | Open | Out of scope |

### 4.2 Attacker goals

- **Double-spend a confirmed transaction** (most common motive; section 5.1)
- **Censor specific addresses** (selfish mining + censorship; section 5.2)
- **Extract maximum protocol revenue** (pure selfish mining; section 5.2)
- **Chain death** (denial of all progress; section 5.5)

### 4.3 Explicitly out of scope

- Cryptographic break of BLAKE3 (we inherit BLAKE3's 128-bit collision
  / 256-bit preimage resistance). If BLAKE3 falls, every fork of
  Bitcoin that adopted it falls together. Bitcoin's own SHA-256d
  collision attack would be a comparable event.
- Compromise of the b3chain release-signing key (covered by
  [`SECURITY-ROADMAP.md §2`](SECURITY-ROADMAP.md) reproducible Guix
  builds, not this document).
- Compromise of an individual miner's wallet (covered by Bitcoin's
  inherited wallet security).
- Out-of-protocol attacks (exchanges, custodians, regulators).

---

## 5. Attack vectors

Each vector below is presented in the same skeleton: **mechanism**,
**cost model**, **mitigations in this plan**, and **simulator
reference**. The 12 vectors cover the established literature plus the
two new vectors this document introduces (V-9 cache-eviction DoS, V-12
Stratum V2 misuse).

### V-1 Classic majority double-spend

**Mechanism.** Attacker mines a private chain that excludes a target
transaction or replaces it with a double-spend. When the private chain
overtakes the public chain in cumulative work, the attacker reveals
it. Bitcoin §11 gives the canonical probability formula:

```
P(double-spend) ≈ ( (1 - q) - q × Σ_{k=0..z} (...) ) for z confirmations and q = α
```

In practice: α = 0.5 gives P → 1 at any z; α = 0.4 gives P = 1.0% at z
= 6, ≪ 0.01% at z = 30; α = 0.3 gives P = 5.9% at z = 1 and < 0.001%
at z = 12.

**Cost model.** Marginal cost = wasted block subsidy on private chain
+ depreciation of equipment + power. At α = 0.5 and 100 KH/s network,
honest cost per block ≈ subsidy + fees. Attacker cost per replaced
block ≈ same (their share of subsidy is forfeit while mining
privately).

**Mitigations.**
- **M-3 (LWMA-3)**: a hashrate shock retargets in ~10 hours, not 14
  days. Limits the duration of cheap hashrate attacks during the
  retarget window.
- **M-4 (`max_reorg_depth = 200`)**: caps the deepest economical
  attack at 200 blocks ≈ 33 hours (regardless of attacker hashrate).
  Beyond that, the attacker chain is rejected and the attacker is
  banned.
- **M-5 (depth-aware ban)**: stale-tip headers cost progressively
  more peer score, so feeding the attack chain to honest nodes is
  metered.

**Simulator.** [`contrib/testing/audit/audit-51-attack-sim.py`](../../contrib/testing/audit/audit-51-attack-sim.py)
(extended in Phase 1).

### V-2 Selfish mining (Eyal-Sirer)

**Mechanism.** Attacker keeps mined blocks private; reveals
strategically to force honest miners to waste work on a stale chain.
Threshold α* below which selfish mining is unprofitable depends on γ
(network propagation advantage):

| γ | α* |
|---|---|
| 0   | 1/3 ≈ 0.333 |
| 0.5 | 0.25 |
| 1   | 0 (selfish mining always profitable) |

**Cost model.** Same equipment as honest mining; only strategy
differs. Reward gain is α(1−α)² / (1−2α) for γ=0 vs honest α — i.e.,
selfish wins when this exceeds α, which is the threshold above.

**Mitigations.**
- **M-3 (LWMA-3)**: faster retarget reduces the size of the window
  during which selfish-mining strategy compounds.
- **M-4 (`max_reorg_depth = 200`)**: caps the maximum number of
  "withheld" blocks before reveal is rejected.
- Cannot eliminate; only price up the attack.

**Simulator.** `contrib/testing/audit/audit-selfish-mining-sim.py` (new).

### V-3 Time-warp / Murch-Zawy

**Mechanism.** Manipulate block timestamps within the
median-time-past (MTP) tolerance to inflate the perceived inter-block
spacing within a retarget window, causing the next retarget to lower
difficulty more than reality warrants. After several retargets, an
attacker with minority hashrate may mine the chain.

**Status.** BIP94 mitigates this by validating retarget timestamps
against the MTP of the first block in the new window. **Currently
[`enforce_BIP94 = false`](../../src/kernel/chainparams.cpp) on b3chain
mainnet, testnet, and signet** (only testnet4 has it true — finding
**F-2**).

**Cost model.** Time-warp can theoretically depress difficulty by 5×
over 2–3 retarget periods (28–42 days under Bitcoin's 14-day retarget).
Under M-3 (LWMA-3, 10-hour response) the attack window shrinks
dramatically; even without M-2, time-warp on LWMA-3 is largely
ineffective. With **M-2 (BIP94 on mainnet)** it is closed entirely.

**Mitigations.**
- **M-2 (BIP94 on mainnet)** — closes the vector.
- **M-3 (LWMA-3)** — limits exposure window.

**Simulator.** `contrib/testing/audit/audit-timewarp-sim.py` (new).

### V-4 Difficulty manipulation under 2016-block retarget

**Mechanism.** Generic class — attacker mines fast, drops out, lets
difficulty fall, double-spends at low difficulty, repeats. Famously
exploited on Ethereum Classic (Aug 2020, ~$5.6M double-spent across
~7,000 reorgs). Bitcoin's 2016-block retarget is too slow for
low-hashrate chains.

**Mitigations.**
- **M-3 (LWMA-3)** — directly addresses this. LWMA-3 is the algorithm
  proposed *because* of this attack class.

**Simulator.** Compose `audit-bootstrap-reorg-sim.py` (new) with
`audit-51-attack-sim.py` (extended).

### V-5 Low-hashrate bootstrap reorg

**Mechanism.** During the bootstrap phase (weeks 0–12), total network
hashrate is by definition low. A single competitor with comparable
FPGA inventory has parity hashrate and can reorg arbitrarily.

**Cost model.** Per the Phase 1 simulator (`audit-bootstrap-reorg-sim.py`):

| Height | Honest H/s | Attacker H/s required (7-day overtake) | Attacker cost ($) |
|---|---|---|---|
| 100   | 10 KH/s   | 11 KH/s   | $1.5 K cap-ex + ~$0.1K op-ex |
| 500   | 50 KH/s   | 55 KH/s   | $8.0 K cap-ex + ~$0.5K op-ex |
| 1 000 | 100 KH/s  | 110 KH/s  | $15 K cap-ex + ~$1K op-ex |
| 5 000 | 500 KH/s  | 550 KH/s  | $80 K cap-ex + ~$5K op-ex |
| 10 000 | 1 MH/s   | 1.1 MH/s  | $150K cap-ex + ~$10K op-ex |

Numbers assume B3Miner-1 KU5P at ~$1.5k/board and 20 KH/s/board.

**Mitigations.**
- **M-3 (LWMA-3)** — limits retarget-exploitation window.
- **M-4 (`max_reorg_depth = 200`)** — caps blast radius at ~33 hours.
- **M-5 (depth-aware ban)** — prices feeding the attack chain.
- **M-8 (`-assumevalidcheckpoints=path`)** — operators may pin
  block-height heuristics during the most vulnerable weeks.
- **M-10 (`-paranoid-headers-sync`)** — high-value exchanges may
  require 3-peer confirmation.

**Simulator.** `contrib/testing/audit/audit-bootstrap-reorg-sim.py` (new).

### V-6 FPGA vendor concentration (B3Miner-1 supply)

**Mechanism.** GPU-hostile design means the only economic mining
hardware on day 1 is the b3chain reference board (B3Miner-1 / KU5P).
The b3chain team and the contract manufacturer have first-mover
inventory. This is structurally identical to "Bitmain making most
SHA-256d hashrate in 2014–2017" but compressed into months instead of
years.

**Cost model.** Not adversarial cost — instead a Gini coefficient over
board ownership at T = 0/3/6/12 months after genesis. Per
`audit-fpga-concentration-model.py`:

| Demand curve | Gini at T+0 | Gini at T+6mo | Gini at T+12mo |
|---|---|---|---|
| Sluggish | 0.85 | 0.78 | 0.72 |
| Linear   | 0.85 | 0.65 | 0.50 |
| Hype     | 0.85 | 0.45 | 0.30 |

**Mitigations.**
- **In-tree (code):** none possible; vendor concentration is a market
  problem, not a protocol problem.
- **In-tree (algorithm):** none possible; reducing GPU-hostility would
  flip the supply problem into a "buy 10,000 RTX 4090s" attack instead.
- **Out-of-tree (process):**
  - Open RTL (already done — `b3miner-rtl/`).
  - Multiple ODM hardware vendors (b3chain ships only the reference; encourages forks).
  - Documented BoM in [`b3miner-hardware/SCHEMATIC.md`](../../contrib/miner/b3miner-hardware/SCHEMATIC.md).
- **Defensive scope:** **M-4 (`max_reorg_depth`)** bounds the blast
  radius even under monopoly.

**Simulator.** `contrib/testing/audit/audit-fpga-concentration-model.py` (new).

### V-7 Pool collusion

**Mechanism.** Two or more pools coordinate (formally or otherwise) to
combine hashrate. Stratum V1 ([SECURITY-AUDIT.md P-1](SECURITY-AUDIT.md))
and Stratum V2 ([SECURITY-AUDIT.md P-2](SECURITY-AUDIT.md)) both leave
job-template control with the pool by default, so a pool with α miners
behind it acts as a unified α actor.

**Mitigations.**
- **Stratum V2 Job Declaration** ([SECURITY-AUDIT.md P-2](SECURITY-AUDIT.md))
  lets miners propose their own templates, dispersing template power.
- Public pool registry (off-chain; recommend in launch documentation).
- **M-4** caps the blast radius even under full pool collusion.

**Simulator.** Composes with `audit-51-attack-sim.py` — the existing
attack simulator treats the attacker hashrate as a black box; a colluding
pool is just a high-α attacker.

### V-8 Verifier DoS (already mitigated)

**Mechanism.** A malicious peer floods headers crafted to be expensive
to verify (e.g. each requires a full 1 MB pad init + 50 ms B3PoW).
Existing mitigations in the consensus integration plan (D1/D2/D3):

- **D1 (wall-clock budget)**: [`Consensus::Params::b3pow_verify_budget_ms = 50`](../../src/consensus/params.h);
  enforced by [`pow.cpp::CheckBlockHeaderPoW`](../../src/pow.cpp); failures
  route to [`Misbehaving("b3pow-budget-exceeded")`](../../src/net_processing.cpp)
  via `BlockValidationResult::BLOCK_POW_BUDGET`.
- **D2 (pad cache)**: [`b3pow::Cache`](../../src/crypto/b3pow_cache.h) LRU
  by `prev_block_hash`, sized from `b3pow_cache_depth = 4` on mainnet.
- **D3 (headers-sync depth cap)**: `MAX_B3POW_VERIFY_PER_BATCH = 256` in
  [`net_processing.cpp`](../../src/net_processing.cpp) caps per-batch
  verification cost at 256 × 50 ms ≈ 12.8 s.

**Status:** verified by [`audit-b3pow-budget.py`](../../contrib/testing/audit/audit-b3pow-budget.py),
[`audit-b3pow-cache.py`](../../contrib/testing/audit/audit-b3pow-cache.py),
[`audit-b3pow-headers-cap.py`](../../contrib/testing/audit/audit-b3pow-headers-cap.py).

**Additional mitigations this plan adds.**
- **M-7 (depth-asymmetric budget)**: 50 ms for tip ±6, 25 ms for
  6..100, 10 ms beyond. Prices speculative deep-reorg headers.

### V-9 Cache-eviction DoS (new vector this document surfaces)

**Mechanism.** Attacker submits many headers (each costs little —
they don't have to be valid PoW; the verifier is asked to compute the
pad before the check) with novel `prev_block_hash` values to force
evictions of legitimate cached pads. On the next legitimate
tip-extension, the verifier pays the 5 ms cold-init penalty.

**Cost model.** At `b3pow_cache_depth = 4` (current mainnet), an
attacker needs only 4 distinct novel headers to fully cycle the cache.
For each cycle (~tens of µs of attacker work), the next honest
validation pays a 5 ms penalty — a ~100× amplification.

**Mitigations.**
- **M-6 (2-tier pinned cache)**: tip-pad + 2 ancestors are pinned and
  cannot be evicted. Hostile peers can churn only the LRU tier.
- Raising `b3pow_cache_depth` from 4 → 8 (8 MB resident on mainnet)
  reduces the eviction rate further.

**Simulator.** `contrib/testing/audit/audit-cache-eviction-dos.py` (new).

### V-10 Memory-hardness shortcut

**Mechanism.** SPEC §8.C explicitly acknowledges B3PoW-Scratch is
"not Argon2-strength". A mining rig that economises on memory (e.g.
256 KB instead of 1 MB scratchpad) pays a ~4× recompute penalty per
the SPEC table. If recompute is implemented in custom silicon, the
penalty can be amortised by clock rate, and a small-memory ASIC may
beat a large-memory FPGA on $-per-hash.

**Cost model.** Open. SPEC §8.E lists this as an open audit item.
This document does not produce numbers; the Phase 3 external audit
(SECURITY-ROADMAP §4) is the appropriate venue.

**Mitigations.**
- **M-11 (uniformity gate)**: `test_address_uniformity.py` (Phase 2.2)
  validates that the address sequence is uniform — a precondition for
  the recompute-penalty argument.
- **Limit:** no in-tree defence against an actually-cheaper-than-FPGA
  ASIC implementation exists. If one is built, **M-4** still caps the
  blast radius.

### V-11 Eclipse + minority hashrate

**Mechanism.** Heilman et al. 2015: an attacker monopolises a
victim's peer connections, feeding only their chain. Combined with α
< 0.5 hashrate, the victim sees only the attacker chain even if
honest network has more cumulative work.

**Cost model.** Eclipse requires ~$10k of IP-address rental + sustained
P2P churn. Combined with α = 10–20% hashrate, an attacker can sustain
fork-feeding to a specific victim for days.

**Mitigations.**
- **M-9 (`-maxconnections` default 125 → 200)**: more peers = harder
  eclipse.
- **M-10 (`-paranoid-headers-sync`)**: high-value nodes require 3-peer
  confirmation of headers, ruling out single-peer eclipse.
- Inherited Bitcoin Core eclipse mitigations (anchor connections,
  block-relay-only peers, Tor support).

### V-12 Stratum V2 Job Declaration misuse

**Mechanism.** Stratum V2 ([SECURITY-AUDIT.md P-2](SECURITY-AUDIT.md))
lets miners declare their own block templates. A malicious miner can
declare templates that censor specific addresses or insert specific
transactions. With α = 30% via miner-declared templates, they can
*choose* what to include in 30% of blocks.

**Mitigations.**
- **Inherent:** miner-declared templates require the *pool* to sign;
  pool can reject obviously malicious templates.
- **Out-of-tree:** transparent pool template-rejection policy.
- **Defensive scope:** **M-4** caps the blast radius.

---

## 6. Per-vector cost summary

Compact reference table — see each vector section for derivation.
"Cost" is order-of-magnitude USD to mount once at the given attacker share.

| Vector | Bootstrap (α=30%) | Maturity (α=30%) | Notes |
|---|---|---|---|
| V-1 double-spend, k=6 | $5–15K | $5–20M/day | Cap-ex amortises across many attempts; M-4 caps depth |
| V-2 selfish mining | $0 (free if you have α) | $0 | M-3 reduces compounding window |
| V-3 time-warp | $0 (free pre-M-2) | $0 (impossible post-M-2) | M-2 closes |
| V-4 difficulty manipulation | $5K | infeasible post-M-3 | M-3 closes |
| V-5 bootstrap reorg | $1.5–150K | n/a | Most pressing pre-launch risk |
| V-6 FPGA monopoly | inherent | erodes over time | Out-of-protocol problem |
| V-7 pool collusion | $0 (organisational) | $0 | M-4 caps blast |
| V-8 verifier DoS | bandwidth-limited | bandwidth-limited | Defended |
| V-9 cache-eviction | $10s | $10s | M-6 closes |
| V-10 memory shortcut | open | open | External audit |
| V-11 eclipse | $10K | $10K | M-9, M-10 |
| V-12 Stratum V2 abuse | organisational | organisational | M-4 caps blast |

---

## 7. Recommendations matrix (prioritised)

Risk-Reduction × Cost × Deployability matrix. Items not in this plan
are listed as **deferred** with the appropriate roadmap pointer.

| # | Mitigation | Risk reduction | Cost | Deployability | Status |
|---|---|---|---|---|---|
| R-1 | M-1: ITER_MUL[7] distinctness | Low (defects, not attacks) but mandatory hygiene | Hours | Pre-genesis hard fork | **Ship in this plan** |
| R-2 | M-2: BIP94 on mainnet | High (closes V-3) | Minutes | Pre-genesis hard fork | **Ship in this plan** |
| R-3 | M-3: LWMA-3 | High (closes V-4, mitigates V-1/V-5) | Days | Pre-genesis hard fork | **Ship in this plan** |
| R-4 | M-4: max_reorg_depth=200 | Critical (caps every attack's blast radius) | Days | Pre-genesis hard fork | **Ship in this plan** |
| R-5 | M-5: depth-aware ban | Medium | Hours | Network behavioural | **Ship in this plan** |
| R-6 | M-6: 2-tier pinned cache | High (closes V-9) | Days | Behavioural | **Ship in this plan** |
| R-7 | M-7: depth-asymmetric budget | Medium | Hours | Network behavioural | **Ship in this plan** |
| R-8 | M-8: checkpoint stub OFF | Low (just a knob) | Days | Operator opt-in | **Ship in this plan** |
| R-9 | M-9, M-10: anti-eclipse | Medium | Hours | Operational | **Ship in this plan** |
| R-10 | M-11: uniformity gate | Mandatory pre-genesis | Days | CI gate | **Ship in this plan** |
| R-11 | M-12: diffusion sketch | Documentation | Hours | Documentation | **Ship in this plan** |
| R-12 | External audit | Mandatory pre-launch | $40–120K, 4–8 weeks | External party | **Deferred** to [SECURITY-ROADMAP §4](SECURITY-ROADMAP.md) |
| R-13 | Maintainer-signed checkpoints | High (caps adversarial reorg absolutely) | Ceremony + ongoing | External key ceremony | **Deferred** to [SECURITY-ROADMAP §7](SECURITY-ROADMAP.md) |
| R-14 | Federation / ChainLocks | Absolute (deterministic finality) | Months + governance | Federation governance | **Out of scope** (would require new governance layer) |
| R-15 | Continuous benchmark CI | Catches regressions | Already in progress | Internal | **In progress** ([SECURITY-ROADMAP §3](SECURITY-ROADMAP.md)) |

---

## 8. Defended already (status reference)

The previous consensus-integration plan
([`.cursor/plans/b3pow_consensus_integration_*.plan.md`](../../.cursor/plans/))
shipped three DoS-mitigation layers that defend the verifier itself.
This document records them as **defended**:

| ID | Defence | Verified by |
|---|---|---|
| D1 | Verifier wall-clock budget | [`audit-b3pow-budget.py`](../../contrib/testing/audit/audit-b3pow-budget.py) |
| D2 | Per-`prev_block_hash` pad LRU cache | [`audit-b3pow-cache.py`](../../contrib/testing/audit/audit-b3pow-cache.py) |
| D3 | Headers-sync depth cap (256/batch) | [`audit-b3pow-headers-cap.py`](../../contrib/testing/audit/audit-b3pow-headers-cap.py) |

This plan augments D2 with M-6 (2-tier pinned cache) addressing V-9
which D2 alone did not cover.

---

## 9. What we do not claim

Final restatement of the unstated assumptions other coin launches gloss
over.

1. **B3PoW-Scratch is not "ASIC-proof"**. It is *FPGA-economical* and
   *on-chip-memory-bound*. An ASIC port is feasible. The bound is
   economic (NRE cost vs network reward), not algorithmic.
2. **A low-hashrate chain is reorganisable**. That is true of every
   PoW chain regardless of algorithm. We engineer cost and blast
   radius, not impossibility.
3. **No PoW chain has absolute finality**. Confirmation count is a
   probabilistic guarantee, not a deterministic one. `max_reorg_depth
   = 200` (M-4) introduces a *consensus-level* finality cap at 200
   blocks (~33 hours), which is a deliberate trade-off — operators
   who reject this trade-off can opt out via the `-no-max-reorg-depth`
   build flag (see Phase 6 doc updates).
4. **No checkpoints ship**. Operators who want pinned-block
   protection during the vulnerable bootstrap weeks must opt in via
   `-assumevalidcheckpoints=path/to/json` and curate the list
   themselves (see [`RESPONSE-RUNBOOK-51ATTACK.md`](RESPONSE-RUNBOOK-51ATTACK.md)).
5. **External audit pending**. The recommendations in §7 R-12 onwards
   require a contracted auditor that the project must engage before
   mainnet. This document is a self-assessment, not a substitute for
   that engagement.

---

## 10. Provenance and reproducibility

Every number in this document either:
- Quotes [SPEC §8](../../contrib/miner/b3miner-rtl/SPEC.md), or
- Is produced by a simulator under [`contrib/testing/audit/`](../../contrib/testing/audit/), or
- Is explicitly labelled as a scenario / order-of-magnitude estimate.

Raw CSVs from the Phase 1 simulators live at
`contrib/testing/audit/results/r0/`. To reproduce:

```bash
cd b3chain
bash contrib/testing/audit/run-all.sh        # all 17 + 6 new audits
python3 contrib/testing/audit/audit-51-attack-sim.py --output-csv
python3 contrib/testing/audit/audit-selfish-mining-sim.py
python3 contrib/testing/audit/audit-timewarp-sim.py
python3 contrib/testing/audit/audit-bootstrap-reorg-sim.py
python3 contrib/testing/audit/audit-cache-eviction-dos.py
python3 contrib/testing/audit/audit-fpga-concentration-model.py
```

Last full simulator run: pending first execution.

---

## Appendix A — Glossary

- **α**: attacker hashrate share.
- **γ**: selfish-mining propagation advantage.
- **k**: confirmation depth.
- **MTP**: median time past.
- **LWMA-3**: Linear-Weighted Moving Average difficulty algorithm, window N=60.
- **BIP94**: time-warp mitigation soft fork.
- **B3Miner-1**: the b3chain reference FPGA mining board (KU5P).
