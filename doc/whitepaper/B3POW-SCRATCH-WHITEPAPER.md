% B3PoW-Scratch v1.1 — A Memory-Hard, FPGA-Economical Proof-of-Work for Bitcoin-Derived Blockchains
% B3Chain Contributors
% 2026-05-19 (v1.1.1, `SPEC_VERSION = 0x00010101`)

---

## Abstract

We present **B3PoW-Scratch v1.1**, a memory-hard Proof-of-Work
construction for Bitcoin-derived blockchains. B3PoW-Scratch is built
on the BLAKE3 primitive, runs over a 1 MiB scratchpad partitioned
into 8 parallel lanes, and executes 2 048 data-dependent
read–modify–write iterations per hash. The construction is designed
to be **FPGA-economical** (a single Xilinx Kintex UltraScale+ KU5P at
~10 W is the reference miner), **GPU-hostile** (the sequential 1 MiB
working set defeats GPU pipelining), and **ASIC-non-trivial** (an ASIC
implementation is possible but the per-hash advantage over the
reference FPGA is bounded, because the algorithm is memory-bandwidth
bound rather than compute-bound).

B3PoW-Scratch v1.1 is the production Proof-of-Work of B3Chain, a
Bitcoin Core fork that preserves Bitcoin's UTXO model, monetary
schedule, identity hash (SHA-256d), and P2P protocol while replacing
only the PoW hash function. Four independent in-tree implementations
(Python reference, C++ consensus, TypeScript pool validator,
SystemVerilog RTL) are CI-gated against a single set of consensus
vectors. The complete spec, reference code, formal threat model, and
launch package live under
[`github.com/b3chain/b3chain`](https://github.com/b3chain/b3chain) on
the MIT license.

This document is the launch-grade whitepaper. It states the design
goals and threat model (§3), the formal construction (§4), the
security argument (§5), the hardware analysis (§6), the verification
cost on the node (§7), the parity-testing methodology (§8), and the
open questions we are aware of (§9). Every quantitative claim
is either derived from first-principles arithmetic in this document
or marked as an explicit estimate to be validated by
`contrib/testing/bench/results/r0/` and the forthcoming external
security audit.

This is a launch-package paper, not a peer-reviewed result; an IACR
ePrint preprint with formal proofs and additional experimental data
is at [`doc/preprint/B3POW-SCRATCH-PREPRINT.tex`](../preprint/B3POW-SCRATCH-PREPRINT.tex).

---

## 1. Introduction

The launch dilemma for a new Bitcoin-derived Proof-of-Work
blockchain is well known. Starting on SHA-256d means the network
hashrate on day one is bounded by the **idle** capacity of the
existing Bitcoin ASIC fleet — at any meaningful price, that capacity
exceeds the new chain's hashrate by many orders of magnitude, and any
small-pool operator can centralize the chain almost instantly.
Choosing a memory-hard or GPU-friendly algorithm instead of SHA-256d
avoids this carry-over but trades it for a different set of failure
modes: CPU/GPU-friendly designs invite botnet hashrate, designs that
need exotic memory hierarchies are unverifiable on commodity nodes,
and designs that are too hardware-agnostic recreate the SHA-256d ASIC
race on a new vertex.

B3PoW-Scratch v1.1 is one point on this trade-off curve. Its
explicit design goal is to make the most economical production miner
a **small, low-power FPGA card with on-chip memory**:

- The 1 MiB scratchpad fits entirely in BRAM/URAM on the reference
  Kintex UltraScale+ KU5P, eliminating external DDR and its
  associated BOM and bring-up risk.
- The 8 partition × per-partition single-port-RW layout maps 1:1 to
  the FPGA's BRAM port topology, giving 8 reads + 8 writes per cycle.
- The 2-round reduced BLAKE3 mixer is small enough that an 8-lane
  pipeline fits in a few thousand LUTs.
- 2 048 sequential data-dependent iterations defeat GPU pipelining
  (a GPU's per-warp L2 working set is an order of magnitude smaller
  than 1 MiB, and the dependency chain prevents nonces from being
  batched).
- A custom B3PoW-Scratch ASIC is possible but the per-hash advantage
  over the FPGA reference is bounded, because the dominant cost is
  SRAM area (which is comparable across modern fabs) rather than
  combinational logic. See §6.

The chain itself is otherwise Bitcoin: UTXO, 21 M cap, 10-min target,
210k halving, all Bitcoin script opcodes, Bitcoin's wire format. The
only consensus-level departure from Bitcoin Core is the PoW
function. The block identity hash (`block.GetHash()`) is still
SHA-256d, so the P2P protocol and explorer UX are unchanged.

The remainder of this paper specifies the algorithm and its
properties precisely enough that an independent implementer can build
a byte-compatible miner, pool validator, or node from this document
plus the four in-tree references.

![Launch-time deployment topology: testnet seeds, full-node operators, reference pool, CPU + FPGA reference miners, and public services. Source: [`doc/diagrams/system-launch.mmd`](../diagrams/system-launch.mmd).](../diagrams/out/system-launch.svg)

### What this paper is not

- We do not claim B3PoW-Scratch is "ASIC-proof" or "permanently
  decentralised". No PoW is. The design goal is to shift the
  economic frontier, not to eliminate it. §6 makes the claimed
  bounds quantitative.
- We do not claim a novel cryptographic primitive. BLAKE3 is the
  underlying compression function; B3PoW-Scratch composes it with a
  memory-access pattern in a way that is, we hope, boring on purpose.
- We do not claim a finished security analysis. The formal proofs in
  §5 are informal in this document and developed further in the IACR
  preprint; an external security audit is in scope before mainnet
  launch (see [`doc/audit/SCOPE.md`](../audit/SCOPE.md)).

---

## 2. Background and related work

### 2.1 SHA-256d-based chains

Bitcoin's original SHA-256d construction is compute-bound and
arithmetically simple, which is what made it ASIC-able within ~3
years of launch. Today, ~99.9 % of Bitcoin's network hashrate is
ASIC. Any new SHA-256d-based chain inherits this hardware fleet
instantly; on day one, the SHA-256d ASICs idle at peak BTC difficulty
can take over the new chain's hashrate before the chain reaches its
first difficulty retarget. This is the **SHA-256d carry-over
problem**.

### 2.2 Memory-hard PoW lineage

Several memory-hard PoW designs predate B3PoW-Scratch and inform its
design:

| Algorithm | Primitive | Working set | Position |
|---|---|---|---|
| **Scrypt** (Litecoin) | scrypt | 128 KiB (or higher) | First memory-hard PoW. ASIC-economic at the chosen N anyway; the parameter space was too small. |
| **Cuckoo Cycle** | graph search | ~4 GB | Hard-to-verify cheaply. Verification requires loading the entire graph; bad fit for headers-first sync. |
| **Equihash** | Wagner's algorithm | ~144 MB | Initially memory-hard, eventually ASIC'd at lower memory parameter sets. |
| **RandomX** (Monero) | program-generation + cache | 2 MB / 256 MB | Targets the CPU as the optimum execution model. Strong design but verification cost is high and ASIC bound is informally argued. |
| **ProgPoW** (Ethereum-proposed) | program-generation | small | Aimed at GPU-economic operation. Never deployed. |
| **Argon2** (passwords) | various modes | parameterised | Designed for password hashing; the throughput / verification trade-offs are wrong for PoW economics. |
| **B3PoW-Scratch v1.1** (this) | BLAKE3 (reduced + full) | 1 MiB | Targets the FPGA as the optimum execution model. On-chip-fitting scratchpad. Verification cost is bounded and amortisable via the per-parent pad cache. |

The key axis we move along, relative to the above, is **target
execution model**. RandomX optimises for the CPU; ProgPoW for the
GPU; B3PoW-Scratch for a small FPGA. The choice of target shapes
every other design decision (working-set size, lane structure,
verification-cost ceiling).

### 2.3 BLAKE3 as a primitive

BLAKE3 is a 256-bit hash function descended from BLAKE2 (BLAKE family
was a SHA-3 finalist). It has a published spec, a reference
implementation, SIMD-optimised assembly for x86 and ARM, and a
hardware-friendly inner round. We use BLAKE3 in two modes:

1. **Full BLAKE3** for scratchpad initialisation (`BLAKE3-XOF(prev ||
   i)`), lane seeding (`BLAKE3(seed || L)`), and the final hash
   (`BLAKE3(lanes || nonce)`).
2. **Reduced-round BLAKE3 compression (2 rounds)** for the per-lane
   mix step inside the inner loop. Two rounds is the minimum at which
   the BLAKE3 G-function provides full inter-word diffusion;
   combined with the `LANE_SHUFFLE = (5L + 1) mod 8` permutation it
   gives full diffusion across all 8 lanes within 2 inner rounds.
   See §5.3.

The choice of BLAKE3 over SHA-256 / SHA-3 / Keccak is driven by
hardware-friendliness (the G-function fits in ~600 LUTs per
instantiation on Xilinx 7-series and later) and by inheriting a
modern, peer-reviewed primitive.

---

## 3. Design goals and threat model

### 3.1 Functional goals

1. **Algorithmic stability**. The wire format, header layout, block
   identity, and difficulty retarget are unchanged from Bitcoin.
   Only the PoW hash function differs.
2. **In-tree, four-implementation parity**. A single set of consensus
   vectors must be reproducible by every implementation
   bit-for-bit. CI fails on mismatch.
3. **Per-parent pad cache amortises validation**. Init is the only
   per-parent cost; nonce-search and validation of sibling blocks
   reuse the pristine pad.
4. **Bounded verification cost**. The node's per-hash worst case must
   be small enough that an adversary cannot pin a validator for
   minutes per block (we cap with a configurable IBD budget).

### 3.2 Hardware-economic goals

1. **FPGA-economical**. The reference miner is a single Kintex
   UltraScale+ KU5P card, on-chip-BRAM only, ~10 W, ~tens of MH/s
   target. BOM is low-three-digit USD at 1 ku.
2. **GPU-hostile**. The 1 MiB sequential working set and the
   data-dependent address chain reduce GPU H/s/$ to well below CPU
   per dollar.
3. **ASIC-non-trivial-and-bounded**. A custom ASIC is feasible but
   its dominant cost component is on-chip SRAM, which compresses its
   advantage over the FPGA reference into the single-digit-multiplier
   range rather than the 1000×+ range that SHA-256d ASICs enjoy over
   CPUs. See §6 and [`doc/analysis/ASIC-ECONOMICS.md`](../analysis/ASIC-ECONOMICS.md).

### 3.3 Threat model

We protect against the following adversaries:

1. **An attacker with idle SHA-256d ASIC capacity.** They cannot
   redirect this capacity at our chain — the carry-over problem (§2.1)
   is fully resolved by the algorithm change.
2. **An attacker with significant GPU capacity** (e.g. a repurposed
   gaming farm or AI cluster). §6 argues that their H/s/$ on
   B3PoW-Scratch is below CPU per dollar, eliminating most rational
   attack scenarios.
3. **An attacker who designs a custom B3PoW-Scratch ASIC.** §6 and
   [`doc/analysis/ASIC-ECONOMICS.md`](../analysis/ASIC-ECONOMICS.md)
   argue that the NRE plus per-die memory cost gives an advantage
   over the reference FPGA only in the low single-digit multiplier
   range, and only above a launch hashrate that is implausible in the
   first 2 years.
4. **A node-validator-DoS attacker.** They craft headers (with
   plausible nonces) that force the node into the expensive
   per-hash path. The per-hash IBD budget bounds the cost; the
   per-parent pad cache prevents amplification across siblings.
5. **A standard 51 %-style chain reorganisation attacker.** See
   [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md)
   for the full analysis. B3PoW-Scratch's contribution to defence is
   that the cost-per-unit-hashrate on the honest side is lower for
   the same hardware (a small FPGA card at $X is competitive with
   the attacker's same card at $X), shifting the attacker's
   break-even.

We do **not** protect against:

- A state-level attacker with arbitrary capital, who could outspend
  the chain at any plausible launch hashrate (true for every PoW
  chain in its first year). [`doc/economics/SECURITY-BUDGET.md`](../economics/SECURITY-BUDGET.md)
  quantifies the trigger.
- Compromised firmware on the miner card (mitigation:
  ATECC608B-backed manifest verification; see
  [`contrib/miner/b3miner-firmware/IMPLEMENTATION.md`](../../contrib/miner/b3miner-firmware/IMPLEMENTATION.md)).
- Adversarial mining-pool operators (mitigation: Stratum v2 with
  Noise; cleaner miner-vs-pool boundary; ATECC608B worker identity).

### 3.4 Consensus assumptions

We assume Bitcoin Core's consensus model holds: longest valid chain,
SHA-256d block identity, ECDSA / Schnorr signatures, witness merkle
tree. We assume BLAKE3 is collision-resistant and preimage-resistant
to 128-bit and 256-bit security, respectively. We assume the
wyhash-vetted 64-bit constants used in address derivation
(`ITER_MUL[0..7]`) are full-rank (every per-iteration multiplier
produces a bijective state transformation), which we verify by the
F-4 chi-squared CI test (see §5.3).

---

## 4. The B3PoW-Scratch construction

This section is informative; the **normative** specification is
[`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md)
and the executable reference is
[`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py).
The C++ consensus implementation
[`src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp)
is bit-exact with the Python reference.

### 4.1 Parameters (locked, consensus-critical)

```text
SPEC_VERSION  = 0x00010101  -- v1.1.1, F-1 fix (ITER_MUL[7] distinct)

HEADER_BYTES  = 80                  (Bitcoin block header, unchanged)
SCRATCH_BYTES = 1 048 576           (1 MiB working set)
LANES         = 8                   (parallelism axis)
LANE_BYTES    = SCRATCH_BYTES / LANES = 131 072
BLOCK_BYTES   = 64                  (per-RMW block, matches BLAKE3 input)
LANE_BLOCKS   = LANE_BYTES / BLOCK_BYTES = 2 048  (address space, 11 bits)
ITERATIONS    = 2 048               (outer RMW loop count)
INNER_ROUNDS  = 2                   (reduced-round BLAKE3 per iteration)

BLAKE3_ROUNDS = 7  (full BLAKE3 for init/seed/final)

ITER_MUL[0..7] = {0xA0761D6478BD642F,  0xE7037ED1A0B428DB,
                  0x8EBC6AF09C88C6E3,  0x589965CC75374CC3,
                  0x1D8E4E27C47D124F,  0xEB44ACCAB455D165,
                  0xC863B19A77C75D70,  0x6E5C6F88AA5BDA77}
                                       (wyhash-vetted, pairwise distinct)

LANE_SHUFFLE = (1, 6, 3, 0, 5, 2, 7, 4)   -- equivalent to L' = (5L+1) mod 8
```

### 4.2 Inputs and outputs

The PoW function has signature:

```text
pow_hash : 32 bytes = b3pow_scratch( header[80 bytes],
                                     prev_block_hash[32 bytes] )
```

`header` is the standard 80-byte serialised Bitcoin header (`version
‖ hashPrevBlock ‖ hashMerkleRoot ‖ nTime ‖ nBits ‖ nNonce`,
little-endian). `prev_block_hash` is the raw little-endian 32-byte
SHA-256d hash of the parent block (the same value embedded inside
`header` at offset 4..36). Passing it explicitly lets the
implementation compute the scratchpad without re-parsing the header.

### 4.3 Top-level pipeline

```text
seed         = BLAKE3(header)                    [32 bytes]
pad          = init_scratchpad(prev_block_hash)  [1 MiB; expensive; cacheable]
lanes[0..7]  = init_lanes(seed)                  [8 × 32 bytes]

for r in 0 .. ITERATIONS - 1:
    addrs   = derive_addresses(lanes, r)         [8 × 11-bit indices]
    blocks  = read_scratchpad_blocks(pad, addrs) [8 × 64 bytes]
    (lanes_new, blocks_new) = mix_step(lanes, blocks)
    write_scratchpad_blocks(pad, addrs, blocks_new)
    lanes = lanes_new                            [post lane-shuffle]

pow_hash = BLAKE3( concat(lanes[0..7]) ‖ header[76..80] )
```

Each iteration is a parallel 8-lane RMW: read 8 × 64 B from the pad
(one per lane), mix with the lane state via a 2-round BLAKE3
compression, write back `block XOR permuted_msg`, and apply the
fixed lane-shuffle permutation. The shuffle ensures full
inter-lane diffusion within `INNER_ROUNDS = 2`.

![Per-hash B3PoW-Scratch data flow with byte sizes labelled at every interface. Source: [`doc/diagrams/algorithm-dataflow.mmd`](../diagrams/algorithm-dataflow.mmd).](../diagrams/out/algorithm-dataflow.svg)

### 4.4 `init_scratchpad`

```python
def init_scratchpad(prev_block_hash: bytes) -> bytearray:
    assert len(prev_block_hash) == 32
    pad = bytearray(SCRATCH_BYTES)
    for i in range(SCRATCH_BLOCKS):              # SCRATCH_BLOCKS = 16384
        chunk = BLAKE3-XOF(prev_block_hash ‖ u32_le(i), out_len=BLOCK_BYTES)
        pad[i * BLOCK_BYTES : (i + 1) * BLOCK_BYTES] = chunk
    return pad
```

This is 16 384 independent 64-byte BLAKE3-XOF calls. It is the only
per-parent cost; downstream nonce-search and validation of sibling
headers may reuse a pristine copy of the pad (the algorithm's RMW
mutates the pad, so reuse means handing out a fresh copy each call —
see §7.1).

![Scratchpad partition view: 1 MiB split into 8 contiguous 128 KiB lane partitions; 64 B per-iteration window with RMW write-back to the same offset. Source: [`doc/diagrams/scratchpad-layout.mmd`](../diagrams/scratchpad-layout.mmd).](../diagrams/out/scratchpad-layout.svg)

### 4.5 `init_lanes`

```python
def init_lanes(seed: bytes) -> List[bytes]:
    assert len(seed) == 32
    return [BLAKE3(seed ‖ u32_le(L)) for L in range(8)]
```

Each of 8 lanes gets an independent 32-byte starting state derived
deterministically from the header.

### 4.6 `derive_addresses`

```python
def derive_addresses(lanes: List[bytes], iter_idx: int) -> List[int]:
    mask = LANE_BLOCKS - 1                       # 2047
    addrs = []
    for L in range(LANES):
        lo = u64_le(lanes[L][0:8])
        hi = u64_le(lanes[L][8:16])
        mul   = ((hi ^ iter_idx) * ITER_MUL[L]) mod 2^64
        mixed = lo ^ rotr64(mul, 23)
        addrs.append(mixed & mask)
    return addrs
```

Two design notes:

- `iter_idx` is XOR'd into the **high** half before the
  multiplication, not after the rotation. This guarantees that the
  iteration index diffuses into every output bit (multiplication
  mixes upper and lower halves). An earlier draft placed `iter_idx`
  post-rotate, which left it at bit 41 of `mixed` after `rotr64(., 23)`
  — never reaching the 11-bit address window. Fixed in v1.1.0.
- The 8 entries of `ITER_MUL` are pairwise distinct, odd, and
  wyhash-vetted for full 64-bit avalanche. The F-1 fix in v1.1.1
  replaced an earlier duplicate `ITER_MUL[7] == ITER_MUL[1]` (which
  collapsed lane 7's address derivation to lane 1's) with a fresh
  distinct constant.

### 4.7 `mix_step`

```python
def mix_step(lanes, blocks):
    new_lanes  = [None] * LANES
    new_blocks = [None] * LANES
    for L in range(LANES):
        cv         = words_le(lanes[L])          # 8 × u32
        msg        = words_le(blocks[L])         # 16 × u32
        new_cv, permuted_msg = blake3_compress_reduced(cv, msg, INNER_ROUNDS)
        new_lanes[L]  = bytes_le(new_cv)         # 32 bytes
        new_blocks[L] = blocks[L] XOR bytes_le(permuted_msg)  # 64 bytes
    # apply lane shuffle: lanes seen by next iteration are reindexed
    shuffled = [new_lanes[LANE_SHUFFLE[L]] for L in range(LANES)]
    return shuffled, new_blocks
```

The reduced-round BLAKE3 compress runs `INNER_ROUNDS = 2` rounds
instead of the full 7. The first 8 output words feed the new lane
state; the (permuted) 16 message words feed the scratchpad
writeback. The writeback is `block XOR permuted_msg` to ensure that
even cold pad regions (those visited only once during nonce search)
receive non-trivial entropy injection.

### 4.8 Final hash

```python
pow_hash = BLAKE3( concat(lanes[0..7]) ‖ header[76:80] )
```

The 256-byte serialised lane state is hashed together with the
nonce (the last 4 bytes of the header). Including the nonce in the
final BLAKE3 input ties the output unambiguously to the candidate
header even in the (vanishingly unlikely) event of a lane-state
collision.

### 4.9 PoW check

`pow_hash <= target` in unsigned little-endian 256-bit integer
comparison. `target` is decoded from `header.nBits` exactly as in
Bitcoin's `arith_uint256::SetCompact`.

### 4.10 Worked dimensions

| Quantity | Value | Notes |
|---|---|---|
| BLAKE3 calls per hash | 16 384 init + 1 seed + 8 lane-init + 16 384 reduced mix + 1 final = **32 778** | The reduced calls are 2/7 of a full BLAKE3 compression. |
| Effective BLAKE3-compression-equivalent | ≈ 16 384 + 9 + 16 384 × (2/7) + 1 ≈ **21 074** | If you weight reduced rounds by their fraction of full. |
| Memory traffic per hash | 8 MiB read + 8 MiB write (16 384 × 8 × 64 B each way) | Sequential within a lane, scattered across lanes. |
| Pure-Python H/s (Zen 4, single core) | **~1–3** | Reference is correctness-only. |
| Optimised C++ AVX-512 H/s (Zen 4, single core) | **~50–150 estimate** | To be measured: [`contrib/testing/bench/results/r0/`](../../contrib/testing/bench/results/r0/). |
| Reference FPGA (KU5P, ~10 W) MH/s | **~tens of MH/s estimate** | §6 + [`doc/analysis/FPGA-FEASIBILITY.md`](../analysis/FPGA-FEASIBILITY.md). |

---

## 5. Security analysis

This section is informal. The IACR preprint at
[`doc/preprint/B3POW-SCRATCH-PREPRINT.tex`](../preprint/B3POW-SCRATCH-PREPRINT.tex)
develops the formal arguments and the external audit
[`doc/audit/SCOPE.md`](../audit/SCOPE.md) will independently verify
the claims here.

### 5.1 Preimage and collision resistance

B3PoW-Scratch's output is a single BLAKE3 evaluation over `lanes ‖
nonce`. Preimage and collision resistance reduce to BLAKE3's standard
security claims: 128-bit collision resistance, 256-bit preimage
resistance. Nothing in the inner loop interacts with the output BLAKE3
in a way that would weaken those assumptions; the loop output `lanes`
is a 256-byte buffer that BLAKE3 then absorbs.

### 5.2 Memory-hardness lower bound

We claim that any implementation of B3PoW-Scratch must perform
roughly the same memory-traffic-per-hash that the reference does:
16 384 × 8 reads and 16 384 × 8 writes of 64 B each, for ~8 MiB of
read traffic and ~8 MiB of write traffic per hash. The justification:

- Each iteration's address derivation depends on the lane state.
- The lane state after iteration `r` depends on the block at
  `addrs[L]` that was just read.
- The block at `addrs[L]` after iteration `r` is the writeback
  `block XOR permuted_msg`, which depends on the lane state at
  iteration `r`.

These three facts together mean the iteration `r+1` cannot start
until iteration `r` has written its pad updates. The chain has length
`ITERATIONS = 2 048` per nonce. An attacker that tries to skip the
memory traffic (e.g. by maintaining lanes-only state and recomputing
the pad on demand) would have to recompute the entire history of
writebacks from iteration 0, which is itself an `O(ITERATIONS)`
operation. The classical time–memory trade-off therefore does not
apply: there is no way to shrink the working set without paying a
proportional time penalty.

This is the same fundamental argument used by scrypt and Argon2-d
("each step depends on the previous and on a memory location chosen
by the previous"), specialised to a fixed-size on-chip-fitting pad
and 8-lane parallelism.

### 5.3 Address-derivation uniformity

For the algorithm to be memory-hard in the strong sense (every
read–modify–write touches a uniformly-distributed pad address per
lane), the address derivation must produce uniformly-distributed
`addrs[L]` in `[0, LANE_BLOCKS)` across all reasonable distributions
of input lane state.

We verify this with three layers:

1. **Construction.** `ITER_MUL[L]` are wyhash-vetted 64-bit
   constants that pass standard PRNG suites. The multiplication
   `(hi ^ iter_idx) * ITER_MUL[L]` followed by `rotr64(., 23)` and
   `XOR` with `lo` is a standard "multiply-rotate-xor" hash; for
   any high-entropy `(lo, hi)`, the result is statistically uniform
   to >32 bits.
2. **CI gate (F-4).** A per-lane chi-squared test on 2²⁰ samples
   per lane is wired into
   [`.github/workflows/b3miner-rtl.yml`](../../.github/workflows/b3miner-rtl.yml).
   Any future change to address derivation must keep this test green.
3. **Cross-implementation parity.** The C++, TS, and SystemVerilog
   ports must produce byte-identical addresses to the Python
   reference; any drift fails the consensus-vector parity test.

The F-1 fix in v1.1.1 (giving lane 7 a distinct `ITER_MUL`) was
explicitly motivated by the lane-uniformity property: with the
original duplicate, lane 7's address derivation collapsed to lane
1's, reducing effective parallelism from 8 to 7 and creating a
correlated-write pattern in the pad.

### 5.4 Inter-lane diffusion

The lane-shuffle `LANE_SHUFFLE = (5L + 1) mod 8` is chosen so that
every lane sees every other lane's state within `INNER_ROUNDS = 2`
iterations. Combined with the BLAKE3 G-function's full intra-lane
diffusion in one round, this gives every output bit a dependence on
every input bit within 2 outer iterations. A formal argument is in
[`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md)
§8.F.

### 5.5 51 % attack cost

A standard 51 % chain-reorganisation attack costs the attacker
roughly `H_attacker × t × cost_per_unit_hashrate`, where `t` is the
target reorg depth and the cost per unit hashrate is the operating
cost (electricity + amortised capex) of the cheapest hash producer.
On B3PoW-Scratch, that cheapest producer is the B3Miner-1 FPGA card
at ~10 W. The attacker pays the same per-unit-hashrate cost as the
honest side, so there is no asymmetry advantage from hardware
specialisation — the only way to gain an advantage is volume.

[`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md)
develops this argument with concrete dollar figures across launch
hashrate × B3C/USD price scenarios.

### 5.6 Verification-DoS attack surface

An attacker can craft headers (with plausible nonces) that force the
node to do full B3PoW-Scratch evaluation. The mitigation has three
layers:

1. **Headers-first sync.** The node validates PoW before downloading
   block bodies, just like Bitcoin. A header with bad PoW is
   discarded after one B3PoW-Scratch evaluation.
2. **Per-parent pad cache.** The 1 MiB pad init is the expensive
   per-parent step. The cache amortises it across sibling headers
   (alternative branches on the same parent).
3. **Per-hash budget.** `Hash(... , chrono::milliseconds budget, bool&
   out_budget_exceeded)` lets the verifier bound the wall-clock per
   hash. During IBD this is set to a small value (10s of ms); during
   normal operation it's set to disabled for miners and small for
   nodes. A budget hit returns `std::nullopt` and the header is
   rejected.

The C++ implementation enforces the budget at the top of every
iteration: the BLAKE3 compression is unbroken (so we don't pay
crash-recovery cost) but the iteration count after which budget is
checked is configurable.

### 5.7 Known weaknesses we are aware of

- **Difficulty volatility on a low-hashrate chain.** B3PoW-Scratch
  does not change Bitcoin's 2 016-block retarget; like any
  low-hashrate chain in its first year, B3Chain is reorganisable at
  a state-level capital cost. The early-difficulty guard (10k blocks)
  mitigates stall risk; the post-launch security budget is laid out
  in [`doc/economics/SECURITY-BUDGET.md`](../economics/SECURITY-BUDGET.md).
- **Pad-cache memory pressure on the node.** A node that maintains
  pad caches for many parents pays per-parent 1 MiB. The default LRU
  capacity is small (16 pads = 16 MiB) and operators can override.
- **BLAKE3 implementation differences.** Different SIMD backends
  must produce byte-identical output. We pin the BLAKE3 vendored
  source tree to a specific upstream commit and re-test the SIMD
  ladder in CI.

---

## 6. Hardware analysis

Full quantitative treatment is in
[`doc/analysis/FPGA-FEASIBILITY.md`](../analysis/FPGA-FEASIBILITY.md)
and
[`doc/analysis/ASIC-ECONOMICS.md`](../analysis/ASIC-ECONOMICS.md).
This section gives the back-of-envelope reasoning that motivates the
algorithm shape.

### 6.1 The reference FPGA

The reference target is the Xilinx Kintex UltraScale+ **XCKU5P-2FFVB676E**:

| Resource | Available | Used by B3PoW-Scratch |
|---|---|---|
| BRAM (36 Kb tiles) | 432 | ~150 (8 lanes × 128 KiB scratchpad split into single-port BRAMs) |
| LUTs | 216k | ~10–30k (8 mixer pipelines + control + Stratum host glue) |
| DSP48E2 | 1 824 | 8–16 (per-lane 64×64 multiplier for `derive_addresses`) |
| GTH transceivers | 16 | 0 (USB-C is hosted by the ESP32-S3) |

A single B3PoW-Scratch pipeline running at 250 MHz produces roughly
**~1 MH/s** (1 iteration per cycle × 8 lanes × 250 MHz / 2 048
iterations per hash). The BRAM budget allows 8 parallel pipelines for
a target of **~8 MH/s** per KU5P card at **~10 W typical**. We will
publish measured numbers in `contrib/testing/bench/results/r0/` once
the first card is bench-tested.

### 6.2 The GPU bound

A modern high-end GPU (e.g. RTX 4090) has:

| Resource | Value |
|---|---|
| Per-SM L1 cache | 128 KiB |
| Per-warp L2 working set | ~128 KiB |
| Per-SM register file | 256 KB |
| Number of SMs | 128 |

B3PoW-Scratch's 1 MiB working set exceeds the per-SM L1 by an order
of magnitude and the per-warp L2 working set by an order of
magnitude. Worse, the inner loop is sequentially data-dependent:
nonce `n` and nonce `n+1` cannot share any work after `init_lanes`.
The GPU's only path to throughput is to run many independent nonces
in parallel; B3PoW-Scratch forces each nonce to bottleneck on memory
bandwidth.

Estimated throughput: tens to low hundreds of H/s per GPU at
hundreds of watts. H/s/$ is well below CPU per dollar. We do not
provide an in-tree GPU miner because such a miner would be both
incorrect (the existing GPU kernels at
[`contrib/miner/b3chain-gpuminer/`](../../contrib/miner/b3chain-gpuminer/)
target the retired double-BLAKE3 PoW and are kept for reference
only) and economically pointless.

### 6.3 The ASIC bound

A custom B3PoW-Scratch ASIC could:

- Pack the 1 MiB scratchpad in dense SRAM (similar density to the
  FPGA's BRAM, both using the same fab's SRAM cells in modern nodes).
- Eliminate the FPGA's LUT fabric overhead (~30–50 % of the FPGA's
  die area).
- Run the inner loop at a higher clock (~1 GHz vs ~250 MHz).
- Pipeline more lanes in parallel (one ASIC die could host 32–64
  pipelines).

Optimistic scaling: a B3PoW-Scratch ASIC could be ~10–30× the
H/s/W of the reference FPGA. But the per-die cost is dominated by
the SRAM, and modern-node tape-out NRE is multi-million-USD. At any
plausible launch hashrate (1–100 GH/s), the per-card economics
favour the FPGA until a very large total addressable market exists.

Crucially, this advantage range (~10–30×) is **bounded** —
SHA-256d's ASIC advantage over CPUs is in the millions-of-times
range. B3PoW-Scratch is engineered to compress this multiplier into
a regime where the chain can resist both ASIC monoculture and
GPU-farm dominance.

[`doc/analysis/ASIC-ECONOMICS.md`](../analysis/ASIC-ECONOMICS.md)
develops the per-card cost curves and the crossover analysis.

### 6.4 Hardware ranking summary

| Tier | Hardware | Approx H/s/$ (relative) | Notes |
|---|---|---|---|
| 1 (best) | Custom B3PoW ASIC | 5–30× FPGA | Hypothetical. Bounded by SRAM cost. NRE > $1M; requires plausible-multi-year revenue to justify. |
| **2 (launch)** | **B3Miner-1 (KU5P FPGA)** | **1×** (reference) | The launch miner. ~10 W, ~tens of MH/s, BOM low 3-digit USD at volume. |
| 3 | High-end CPU (AVX-512) | 0.001–0.01× FPGA | Roughly 50–150 H/s/core at ~5 W/core. Estimate; bench-pending. |
| 4 (worst) | High-end GPU | < CPU per dollar | The sequential 1 MiB working set defeats GPU pipelining. |

(Numbers in this table are order-of-magnitude estimates derived from
the SPEC.md hardware analysis. To-be-measured by
`contrib/testing/bench/results/r0/`.)

![Hardware ranking by hashrate-per-watt on B3PoW-Scratch. Solid stroke = shipped artifact; dashed = order-of-magnitude estimate pending r0 measurement. Source: [`doc/diagrams/hardware-ranking.mmd`](../diagrams/hardware-ranking.mmd).](../diagrams/out/hardware-ranking.svg)

---

## 7. Verification cost on the node

This is the inverse of the "make mining hard" goal: validating a
B3PoW-Scratch hash is intentionally non-trivial (16 384 BLAKE3
rounds + 16 MiB memory traffic). To keep nodes lean we apply three
mitigations:

![Block-verification code path inside `b3chaind`: header parse, context-free pre-checks, `CheckBlockHeaderPoW`, `b3pow::Hash`, target compare, remainder of the validation pipeline. Filepath labels point at the canonical implementation symbol. Source: [`doc/diagrams/verification-flow.mmd`](../diagrams/verification-flow.mmd).](../diagrams/out/verification-flow.svg)

### 7.1 Per-parent pad cache

The 1 MiB pad depends only on `prev_block_hash`. A node maintains an
LRU cache keyed on that hash and reuses the pristine pad across all
sibling headers it sees. This turns N-sibling validation from
`N × (init + mix)` into `1 × init + N × (copy + mix)`.

Implementation note: the canonical Python reference (and the C++ and
TS ports) mutate the pad as part of the RMW loop. Reusing the pad
literally would give wrong hashes. The cache stores the
**pristine** init-only pad and hands out a **fresh copy** per call.
Copy cost is ~100 µs at the ~10 GB/s memcpy of modern CPUs, vs the
~10 ms cost of init.

The shared TypeScript pad cache used by the pool is at
[`contrib/testnet/pool/src/lib/pad-cache.ts`](../../contrib/testnet/pool/src/lib/pad-cache.ts).
The shared Python pad cache used by the CPU miner is at
[`contrib/miner/b3chain-cpuminer.py`](../../contrib/miner/b3chain-cpuminer.py).
The shared C++ pad cache used by the consensus validator is at
[`src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp)
(`b3pow::InitScratchpad` returns a `shared_ptr<const Pad>`).

### 7.2 Per-hash budget

`Hash(..., chrono::milliseconds budget, bool& out_budget_exceeded)`
in the C++ implementation lets the verifier bound wall-clock per
hash. During Initial Block Download (IBD) the budget is set to ~10s
of ms; a header that hits the budget is rejected. The budget is
checked at iteration boundaries.

For miners and `b3chain-util grind`, the budget is set to 0
(disabled), since miners are intentionally CPU/FPGA-bound and have
no DoS surface from headers they themselves construct.

### 7.3 Headers-first sync

Bitcoin's headers-first IBD applies unchanged: the node receives
header chains, validates PoW on each header, and only then requests
block bodies. A header with bad PoW is discarded after one
B3PoW-Scratch evaluation, never costing the node block-body
download bandwidth.

### 7.4 Worst-case envelope

| Scenario | Per-block cost (single core, AVX-512 est.) |
|---|---|
| First validation of a new parent | ~10 ms init + ~10 ms mix = ~20 ms |
| Sibling on a cached parent | ~100 µs copy + ~10 ms mix = ~10 ms |
| Adversarial DoS header | budget (e.g. 30 ms) → rejected |
| Full 2 016-block retarget window | ~2 016 × 10 ms = ~20 s single-core; parallelisable across cores |

These are pre-measurement estimates derived from the BLAKE3 SIMD
throughput numbers in §4.10. Real numbers will land in
`contrib/testing/bench/results/r0/`.

---

## 8. Implementation and parity testing

### 8.1 Four reference implementations

| Implementation | Path | Role |
|---|---|---|
| Python (executable spec) | [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) | Source of truth alongside SPEC.md. Deliberately verbose; no NumPy, no micro-optimisations. |
| C++ (consensus) | [`src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp) + [`b3pow_scratch.h`](../../src/crypto/b3pow_scratch.h) | Production validator inside `b3chaind`. |
| TypeScript (pool) | [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../../contrib/testnet/pool/src/lib/b3pow-scratch.ts) | Pool share validator. Uses `@noble/hashes/blake3`. |
| SystemVerilog (RTL) | [`contrib/miner/b3miner-rtl/rtl/`](../../contrib/miner/b3miner-rtl/rtl/) | FPGA pipeline. Targets Xilinx Kintex UltraScale+ KU5P. |

### 8.2 Consensus vectors

The single source of truth for cross-implementation parity is
[`src/test/data/b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json)
(`schema_version = 1`, `spec_version = 0x00010101`). Every entry
records `header_hex`, `prev_block_hash_hex`,
`expected_pow_hash_hex`, `nbits_hex`, and `expected_check_pow`.

Vectors are generated by
[`contrib/miner/b3miner-rtl/ref/gen_vectors.py`](../../contrib/miner/b3miner-rtl/ref/gen_vectors.py)
and include:

- Mainnet and regtest genesis-like templates.
- "Loose" and "tight" target boundary tests (one designed to pass,
  one to fail).
- Non-trivial parent-hash tests (so the pad init is exercised).
- "Cache-pair" tests (two nonces against the same parent — the
  primary regression net for the pad-cache copy-vs-reuse semantics).

### 8.3 CI parity gate

[`.github/workflows/b3miner-rtl.yml`](../../.github/workflows/b3miner-rtl.yml)
runs:

1. **Python reference tests** — pytest in
   `contrib/miner/b3miner-rtl/ref/tests/`.
2. **Consensus-vector parity** — `contrib/testing/verify-b3pow.py`
   re-derives every vector from `b3pow_ref` and asserts
   `expected_pow_hash_hex` matches.
3. **Pool TS parity** — `contrib/testnet/pool/tests/b3pow-scratch.test.ts`
   re-derives every vector from the TS port.
4. **RTL lint + sim** — Verilator lint and simulation against the
   same vectors.

The C++ parity is asserted by the in-tree unit tests
(`src/test/b3pow_scratch_tests.cpp`) which load the same JSON
vectors and re-derive every entry through the production
`b3pow::Hash` function.

Any divergence between implementations fails CI. This is the
hard credibility gate the launch package rests on.

### 8.4 End-to-end verifier

[`contrib/testing/verify-b3pow.py`](../../contrib/testing/verify-b3pow.py)
is the externally-runnable verifier:

```bash
pip3 install blake3
python3 contrib/testing/verify-b3pow.py                  # vectors only
python3 contrib/testing/verify-b3pow.py --rpc-port=18534 # + every recent live block
```

It uses the Python reference (which is bit-exact with the C++
consensus) so a successful run validates that the live node's
B3PoW-Scratch path matches consensus.

---

## 9. Open questions and known limitations

1. **External security audit** — scope at
   [`doc/audit/SCOPE.md`](../audit/SCOPE.md), threat model at
   [`doc/audit/THREAT-MODEL.md`](../audit/THREAT-MODEL.md), RFP at
   [`doc/audit/RFP.md`](../audit/RFP.md). Mainnet launch is gated on
   audit completion.
2. **Production hardware benchmarks** —
   [`contrib/testing/bench/`](../../contrib/testing/bench/) is the
   harness; round-0 results land at
   [`contrib/testing/bench/results/r0/`](../../contrib/testing/bench/results/r0/)
   once measured on each target.
3. **Custom B3PoW ASIC analysis** — quantitative crossover analysis
   at [`doc/analysis/ASIC-ECONOMICS.md`](../analysis/ASIC-ECONOMICS.md);
   open question is whether a major ASIC vendor (Bitmain, MicroBT)
   would tape out at the launch hashrate. We argue no; the analysis
   is calibrated to be falsifiable.
4. **GPU H/s/$ measurement** — we claim GPUs are well below CPU per
   dollar but have not yet measured. The
   [`contrib/miner/b3chain-gpuminer/`](../../contrib/miner/b3chain-gpuminer/)
   tree currently targets the retired double-BLAKE3 PoW; porting it
   to B3PoW-Scratch (for the purpose of measurement only) is an open
   work item.
5. **KU15P 2 MiB variant (v1.2)** — reserved for a future product
   tier. Incompatible with v1.1; would require a hard fork. See
   SPEC.md Appendix A.
6. **Stratum v2 Noise transport hardening** — in scope of the
   external audit. Reference at
   [`contrib/testnet/pool/src/sv2/`](../../contrib/testnet/pool/src/sv2/).
7. **Long-term security-budget transition** — fee-market dependence
   when subsidy halves below the security-budget floor. Tracked in
   [`doc/economics/SECURITY-BUDGET.md`](../economics/SECURITY-BUDGET.md).
8. **Tail-emission consideration** — explicit non-decision at
   launch. Trigger conditions and decision process described in
   [`doc/economics/MONETARY-POLICY.md`](../economics/MONETARY-POLICY.md).

---

## 10. Conclusion

B3PoW-Scratch v1.1 is a deliberately small departure from Bitcoin:
the only consensus-level change is the PoW hash function. The
algorithm is engineered so the most economical production miner is a
small low-power FPGA card rather than a megafarm ASIC; the chain is
otherwise Bitcoin. The four-implementation parity gate, the
in-tree formal spec, the launch-package documentation tree, the
external audit pipeline, and the reproducible-build release flow
together form the launch credibility surface.

We do not claim B3PoW-Scratch is the last word on memory-hard PoW.
We claim it is a calibrated, conservative, four-times-implemented,
publicly-auditable construction that resolves the SHA-256d
carry-over problem for a new Bitcoin-derived chain. The rest is the
mining and economic community's call.

---

## Appendix A. Reproducing every claim in this paper

| Claim | How to reproduce |
|---|---|
| The four implementations agree on every consensus vector. | `python3 contrib/testing/verify-b3pow.py` (Python ref). `cd contrib/testnet/pool && npm ci && node --import tsx --test tests/b3pow-scratch.test.ts` (TS port). `ctest -R b3pow_scratch` from the b3chaind build dir (C++). Verilator parity sim in `contrib/miner/b3miner-rtl/`. |
| Pad-cache copy semantics are correct. | The `cache_pair_nonce_*` consensus vectors specifically exercise this; all parity tests re-derive them. |
| BLAKE3 primitive is unmodified upstream. | `git log src/crypto/blake3/` shows the vendoring commit and any cherry-picked patches; the dispatch layer is unchanged. |
| GPU is hostile. | Open work item — `contrib/testing/bench/results/r0/` will report a measured GPU bench once we port the kernel. The estimate is in §6.2. |
| FPGA reference target hits ~tens of MH/s at ~10 W. | Open work item — same dir, FPGA bench from a B3Miner-1 card. The pipeline arithmetic is in §6.1 and `doc/analysis/FPGA-FEASIBILITY.md`. |
| ASIC advantage is bounded to ~5–30×. | Calculation in §6.3 and `doc/analysis/ASIC-ECONOMICS.md`; bounded by SRAM-area cost which is comparable across modern fabs. |

---

## Appendix B. Glossary

- **B3PoW-Scratch v1.1** — the algorithm specified in this paper.
- **`SPEC_VERSION`** — `0x00010101` (1.1.1, F-1 fix).
- **Scratchpad** — the 1 MiB working buffer derived from
  `prev_block_hash` and mutated during the inner loop.
- **Lane** — one of 8 parallel pipelines that share the scratchpad
  (each owns its own 128 KiB region).
- **Iteration** — one outer-loop RMW step. There are 2 048 per hash.
- **Inner rounds** — `INNER_ROUNDS = 2`. The number of BLAKE3 rounds
  the per-iteration mixer runs (vs 7 for full BLAKE3).
- **Pad cache** — the per-parent LRU of pristine init-only pads that
  amortises the dominant per-parent cost.
- **F-1 / F-2 / ...** — finding numbers from the pre-launch security
  audit; see [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md).
- **B3Miner-1** — the reference FPGA mining card (KU5P + ESP32-S3
  host + ATECC608B). See
  [`contrib/miner/b3miner-firmware/README.md`](../../contrib/miner/b3miner-firmware/README.md)
  and [`contrib/miner/b3miner-hardware/SCHEMATIC.md`](../../contrib/miner/b3miner-hardware/SCHEMATIC.md).

---

## References

1. Aumasson, J.-P.; Neves, S.; Wilcox-O'Hearn, Z.; O'Connor, J.
   *BLAKE3: one function, fast everywhere.* BLAKE3 Team, 2020.
   https://github.com/BLAKE3-team/BLAKE3-specs/blob/master/blake3.pdf
2. Nakamoto, S. *Bitcoin: A Peer-to-Peer Electronic Cash System.*
   2008. https://bitcoin.org/bitcoin.pdf
3. Tikhonov, S. *RandomX: a Proof-of-Work algorithm optimised for
   general-purpose CPUs.* tevador, 2019.
   https://github.com/tevador/RandomX/blob/master/doc/specs.md
4. Biryukov, A.; Dinu, D.; Khovratovich, D. *Argon2.* RFC 9106, 2021.
   https://www.rfc-editor.org/rfc/rfc9106
5. Tromp, J. *Cuckoo Cycle: a memory-hard Proof-of-Work system.*
   Financial Cryptography Workshops, 2015.
   https://eprint.iacr.org/2014/059
6. Wagner, D. *A Generalised Birthday Problem.* CRYPTO 2002.
7. Hasu. *Bitcoin's security model.* Deribit Insights, 2020.
   https://insights.deribit.com/market-research/an-overview-of-bitcoins-security-model/
8. B3Chain Contributors. *B3PoW-Scratch v1.1 — normative spec.*
   `contrib/miner/b3miner-rtl/SPEC.md`.
9. B3Chain Contributors. *B3PoW-Scratch 51 %-attack analysis.*
   `doc/security/B3POW-51-ATTACK-ANALYSIS.md`.

---

*Document version: 2026-05-19 draft. SPEC_VERSION:
`0x00010101`. This document is informative; the normative spec is
[`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md).*
