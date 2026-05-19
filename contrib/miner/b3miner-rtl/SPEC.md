# B3PoW-Scratch v1.1 — Formal Specification (KU5P Profile)

**Status:** draft (matches RTL in `b3chain/contrib/miner/b3miner-rtl/rtl/`)
**Author:** b3chain
**Last updated:** 2026-05-18
**Supersedes:** B3PoW-Scratch v1.0 (KU15P profile, 2 MB scratchpad — never deployed)

---

## 1. Purpose and scope

This document is the **single normative reference** for the proof-of-work
function used by `b3chain` from the genesis block, on **mainnet,
testnet, testnet4, and regtest** — every chain b3chain ships
runs B3PoW-Scratch v1.1 from height 0. Any implementation —
node validator, miner, pool, FPGA RTL — that matches every test vector
in §10 is correct. Any implementation that does not, isn't.

The C++ port lives in
[`src/crypto/b3pow_scratch.{h,cpp}`](../../../src/crypto/) and is gated
against the Python reference in this directory via
[`src/test/data/b3pow_consensus_vectors.json`](../../../src/test/data/b3pow_consensus_vectors.json)
(consumed by
[`src/test/b3pow_scratch_tests.cpp`](../../../src/test/b3pow_scratch_tests.cpp)).
Verifiers enforce a 50 ms wall-clock budget per header
(`Consensus::Params::b3pow_verify_budget_ms`); headers that exhaust
the budget are routed to peer-scoring as `BLOCK_POW_BUDGET` (see
[`src/pow.{h,cpp}`](../../../src/pow.h) and
[`src/net_processing.cpp`](../../../src/net_processing.cpp)).

This document does **not** cover:

- Block header layout (unchanged from Bitcoin / current b3chain — see
  [`doc/stratum.md`](../../../doc/stratum.md) §1)
- Block-identity hash (still SHA-256d — see
  [`doc/SECURITY-INHERITANCE.md`](../../../doc/SECURITY-INHERITANCE.md))
- Difficulty adjustment (unchanged — see [`src/pow.cpp`](../../../src/pow.cpp))
- Network protocol changes

---

## 2. Design intent

B3PoW-Scratch is designed to:

1. **Inherit BLAKE3's cryptographic strength** by using full BLAKE3 round
   functions as the only non-linear primitive.
2. **Be GPU-hostile** by forcing 8-way parallel dependent reads from a
   1 MB scratchpad with read-modify-write semantics — a pattern GPUs
   serialise badly and FPGAs/ASICs do in one cycle.
3. **Be FPGA-economical on Kintex UltraScale+ KU5P** — the entire
   scratchpad fits in on-chip BRAM (uses ~35 % of KU5P's 432 BRAMs).
4. **Cheap to verify** — one full PoW evaluation completes in ≤ 50 ms
   on a 2026-era CPU core, ≪ 1 % of the 600 s target block interval.
5. **Be ASIC-economical** — the same data-flow scales linearly to ASIC
   embedded SRAM with no algorithmic changes.

---

## 3. Parameters (v1.1, KU5P profile)

| Symbol | Value | Bits | Source of value |
|---|---|---|---|
| `SCRATCH_BYTES` | 1,048,576 | 20 | KU5P BRAM budget (16.3 Mb total) |
| `LANES` | 8 | 3 | One BRAM partition per lane |
| `LANE_BYTES` | 131,072 | 17 | `SCRATCH_BYTES / LANES` |
| `BLOCK_BYTES` | 64 | 6 | BLAKE3 block size |
| `LANE_BLOCKS` | 2,048 | 11 | `LANE_BYTES / BLOCK_BYTES` |
| `ADDR_BITS` | 11 | — | `log2(LANE_BLOCKS)` |
| `ITERATIONS` | 2,048 | 11 | Long enough that latency dominates init |
| `INNER_ROUNDS` | 2 | — | BLAKE3 rounds per mix call |
| `STATE_BITS` | 2,048 | — | 8 lanes × 256-bit lane state |
| `VERSION` | `0x00010101` | 32 | Major.Minor.Patch packed (v1.1.1, F-1 fix) |

The 8 `ITER_MUL[L]` 64-bit multiplicative-mixer constants (wyhash
secret table) are:

```
ITER_MUL[0] = 0xA0761D6478BD642F
ITER_MUL[1] = 0xE7037ED1A0B428DB
ITER_MUL[2] = 0x8EBC6AF09C88C6E3
ITER_MUL[3] = 0x589965CC75374CC3
ITER_MUL[4] = 0x1D8E4E27C47D124F
ITER_MUL[5] = 0xEB44ACCAB455D165
ITER_MUL[6] = 0xC863B19A77C75D70
ITER_MUL[7] = 0x6E5C6F88AA5BDA77
```

All values are pairwise distinct (post-v1.1.1) and have popcount ≥ 28
(well above the 16-bit threshold below which multiplicative mixers fail
chi-squared tests on low-entropy inputs).  ITER_MUL[0..3] are taken
verbatim from the wyhash secret table (`wyhash._wyp[]`); ITER_MUL[4..6]
are project-chosen with the same popcount and distribution properties;
ITER_MUL[7] (`0x6E5C6F88AA5BDA77`) was added in v1.1.1 to replace a
duplicate of ITER_MUL[1] that appeared in v1.1.0 (see
[doc/security/B3POW-51-ATTACK-ANALYSIS.md](../../doc/security/B3POW-51-ATTACK-ANALYSIS.md) F-1).
ITER_MUL[6] (`0xC863B19A77C75D70`) is the only even entry; this is
not a defect because the address-derivation rotr64(...,23) and `& ADDR_MASK`
post-processing recovers full output entropy in the 11-bit address window.

---

## 4. BLAKE3 primitive

B3PoW-Scratch uses **unmodified BLAKE3** as its only mixing primitive.
The relevant subset (the same one used by
[`contrib/miner/b3chain-gpuminer/kernels/blake3.cuh`](../b3chain-gpuminer/kernels/blake3.cuh)):

- `IV[8]` — SHA-256 IV (BLAKE3 spec §2.1)
- `MSG_PERMUTATION[16]` = `{2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8}`
- `g(s, a, b, c, d, mx, my)` — quarter-round mixer (BLAKE3 spec §2.5)
- `round_fn(state[16], m[16])` — one round = 4 column G + 4 diagonal G
- 7 rounds per compression, message permuted after each round

The RTL `rtl/blake3_compress.sv` is a port of this exact data flow.

---

## 5. Top-level function

```
b3pow_scratch(header[80], prev_block_hash[32]) -> hash[32]
```

The block header is the standard 80-byte Bitcoin layout (see
[`doc/stratum.md`](../../../doc/stratum.md) §1). `prev_block_hash` is
the SHA-256d block-identity hash of the parent (already available in
the chain state — no additional storage).

```python
def b3pow_scratch(header: bytes, prev_block_hash: bytes) -> bytes:
    assert len(header) == 80 and len(prev_block_hash) == 32

    nonce = header[76:80]                           # informational only
    seed  = blake3(header).digest()                 # 32 bytes
    pad   = init_scratchpad(prev_block_hash)        # 1 MB
    lanes = init_lanes(seed)                        # 8 × 32 bytes

    for r in range(ITERATIONS):                     # 2048
        addr     = derive_addresses(lanes, r)       # 8 × 11-bit
        block    = parallel_read(pad, addr)         # 8 × 64-byte reads
        lanes, blk_new = mix(lanes, block)          # 2 BLAKE3 rounds
        parallel_write(pad, addr, xor(block, blk_new))   # RMW

    return blake3(serialize_lanes(lanes) || nonce).digest()
```

The same pad is reused for **every** nonce within the same block (it
depends only on `prev_block_hash`, not the header). Miners regenerate
the pad once per `prev_block_hash` change, amortised over ~10⁹ nonce
attempts.

---

## 6. Step-by-step semantics

### 6.1 `init_scratchpad(prev_block_hash) -> bytes[SCRATCH_BYTES]`

```
SCRATCH_BLOCKS = SCRATCH_BYTES // BLOCK_BYTES        # 16384
for i in 0 .. SCRATCH_BLOCKS - 1:
    pad[i*64 : (i+1)*64] = blake3_xof(prev_block_hash || u32_le(i), 64)
```

`blake3_xof(input, out_len)` is BLAKE3 in extendable-output mode with
the standard 32-byte CV, 7 rounds, no keyed mode.

Reference cost (one CPU core): ~5 ms.

### 6.2 `init_lanes(seed) -> bytes[LANES][32]`

```
for L in 0 .. LANES - 1:
    lanes[L] = blake3(seed || u32_le(L)).digest()    # 32 bytes
```

### 6.3 `derive_addresses(lanes, r) -> uint11[LANES]`

For each lane `L`:

```
lo     = u64_le(lanes[L][0:8])
hi     = u64_le(lanes[L][8:16])
mul64  = ((hi ^ r) * ITER_MUL[L]) & 0xFFFFFFFFFFFFFFFF   # truncating
mixed  = lo ^ rotr64(mul64, 23)
addr[L] = mixed & (LANE_BLOCKS - 1)                      # low ADDR_BITS bits
```

`r` is XORed into `hi` **before** multiplication so its bits diffuse
through every output bit of `mul64` (multiplication mixes high and low
halves of its operands). All multiplies are 64×64 → 64 (low half).
`rotr64(x, n)` rotates right by n bit positions.

### 6.4 `parallel_read(pad, addr) -> bytes[LANES][64]`

Each lane `L` reads from its own partition:

```
partition_L = pad[L*LANE_BYTES : (L+1)*LANE_BYTES]
block[L]    = partition_L[addr[L]*64 : (addr[L]+1)*64]
```

Lanes never read from each other's partitions.

### 6.5 `mix(lanes, block) -> (lanes_new, block_new)`

This is the core diffusion step. Treat the 8 lane states (8 × 256 bits
= 2,048 bits) and 8 message blocks (8 × 512 bits = 4,096 bits) as 4
parallel BLAKE3 internal states, each `16 × 32-bit = 512 bits`:

```
state[s][0..15] = repack(lanes, block) for s in 0..3   # 4 × 16 words
for inner in 0 .. INNER_ROUNDS - 1:                   # 2 rounds
    for s in 0..3:
        round_fn(state[s], message_perm(state[s]))
    lane_shuffle(state)                                # σ permutation
(lanes_new, block_new) = unpack(state)
```

`round_fn` is the unmodified BLAKE3 round (§4). `lane_shuffle` applies
the BLAKE3 message permutation σ at lane granularity (swaps state
slices between the 4 parallel states using the same σ indices).

The exact `repack` / `unpack` mapping is described in
`ref/b3pow_ref.py::repack_state` and is **the** authoritative reference;
the RTL `rtl/mixing_core.sv` follows that mapping bit-for-bit.

### 6.6 `parallel_write(pad, addr, value)`

Each lane writes its own 64-byte block back to the same address it
read from:

```
for L in 0 .. LANES - 1:
    partition_L = pad[L*LANE_BYTES : (L+1)*LANE_BYTES]
    partition_L[addr[L]*64 : (addr[L]+1)*64] = value[L]
```

The XOR with the original block (in the top-level function) before
write is what makes future reads at the same address see modified
data — this is the read-modify-write dependency that prevents
parallelisation across nonces.

### 6.7 Final hash

```
serialised_lanes = concat(lanes[L] for L in 0..LANES-1)   # 256 bytes
pow_hash         = blake3(serialised_lanes || nonce).digest()
```

The 4-byte `nonce` is the same `header[76:80]` extracted at function entry.

---

## 7. Comparison vs network target

Identical to Bitcoin / current b3chain:

```
int_le(pow_hash) <= target_from_nbits(header.nbits)
```

`int_le` interprets the 32-byte hash as a 256-bit little-endian unsigned
integer (matches [`src/pow.cpp::CheckProofOfWorkImpl`](../../../src/pow.cpp)).

---

## 8. Security argument (informal)

**A. Cryptographic strength.** The output is `BLAKE3(serialised_lanes ||
nonce)`. Any preimage/collision attack on `b3pow_scratch` immediately
gives a preimage/collision on plain BLAKE3 applied to the lane state.
B3PoW-Scratch inherits BLAKE3's 128-bit collision and 256-bit preimage
resistance.

**B. Progress-freeness.** Each iteration depends on the previous
iteration's `lanes` state (sequential dependency) and on
read-modify-written scratchpad blocks (data dependency). The address
sequence is data-dependent, so no part of the work can be precomputed
across nonces beyond the initial 32-byte seed. There is no Bitcoin-style
midstate optimisation.

**C. Memory-hardness.** Adversaries using `M < SCRATCH_BYTES` memory pay
a recompute cost on each miss. For `M = 512 KB` the expected miss
penalty is ~2× honest path; for `M = 128 KB` it is ~8× honest path. Not
Argon2-strength, but sufficient to make full-scratchpad mining strictly
more profitable than reduced-memory variants.

**D. Hardware ranking.** The 8-way parallel RMW per iteration is the
key wedge:

| Hardware | Per-iter latency | Hash time | Rel. throughput |
|---|---|---|---|
| FPGA (KU5P, on-chip BRAM) | ~24 ns (6 cycles @ 250 MHz) | ~49 µs | 1.0× |
| GPU (RTX 4090, L2-spilled) | ~150 ns × 8 = ~1.2 µs | ~2.5 ms | ~0.02× |
| CPU (Ryzen 9 7950X) | ~80 ns × 8 = ~640 ns | ~1.3 ms | ~0.04× |
| ASIC (7 nm, on-die SRAM) | ~6 ns | ~12 µs | ~4× |

**E. Open audit items.** The address-derivation function's uniformity
is gated in CI at 2²⁰ samples per lane per PR and 2²⁸ samples per lane
per release tag (see [`ref/tests/test_address_uniformity.py`](ref/tests/test_address_uniformity.py)).
The 2³⁶-sample full audit remains an open item for a contracted auditor.
The `mix` function's 2-round diffusion bound is sketched informally in
§8.F; a formal bound is an open item for a tier-1 cryptographic
auditor (see [`doc/SECURITY-ROADMAP.md`](../../doc/SECURITY-ROADMAP.md) item 4).

**F. 2-round full-diffusion sketch.** Each lane's input state (`new_cv`)
after `mix_step` depends on:

  1. Its own previous state, via the reduced-round BLAKE3 `g()` mixer.
  2. The scratchpad block it read (which itself depends on `pad_init` =
     BLAKE3-XOF(prev_block_hash || i) for i ∈ [0, SCRATCH_BLOCKS)).

The cross-lane diffusion happens via `LANE_SHUFFLE = {1, 6, 3, 0, 5, 2,
7, 4}`, which is the permutation `L' = (5L + 1) mod 8` for L ∈ [0, 8).

*Claim (informal):* after `INNER_ROUNDS = 2` applications of
`mix_step`, every lane's state depends on every other lane's previous
state.

*Argument:*
- `LANE_SHUFFLE` is a single permutation, not a cascade.  Define
  σ(L) = (5L + 1) mod 8.
- σ has order 4 in S₈: its cycle decomposition is (0 1 6 7 4 5 2 3),
  one 8-cycle.  After one σ-application, each lane has been moved by
  one position along the cycle; after two applications, by two.
- A single BLAKE3 g() round inside mixing_core mixes 4 of the 16
  message words.  After 7 rounds (full BLAKE3) every input word
  influences every output word.  Our `INNER_ROUNDS = 2` mixes a
  cv-pair plus a 16-word message lane-locally; lane-locality is broken
  only by σ.
- After iteration *r*, lane L's state is a function of lanes
  σ⁻¹(L), σ⁻²(L), ..., σ⁻ʳ(L) -- one new lane per iteration.
- Since σ⁻ʳ traverses the full 8-cycle in r = 8 iterations, lane L
  has been influenced by all 8 lanes after 8 mixing iterations.
- With `ITERATIONS = 2048` (per SPEC §3), the mixing loop runs σ-cycle
  256 times.  Full diffusion is overwhelmingly satisfied.

*Caveat.* This is a *cycle-counting* argument, not a formal
indifferentiability proof.  A tier-1 auditor should establish a
formal bound on the algebraic degree of `mix_step ∘ σ` and confirm
that 2048 iterations are sufficient under the SPEC's adversarial model
(SPEC §8.A).  Tracked as open audit item in
[SECURITY-ROADMAP §4](../../doc/SECURITY-ROADMAP.md).

---

## 9. Versioning

| Version | Date | Profile | `SCRATCH_BYTES` | RTL tag |
|---|---|---|---|---|
| v1.0 | 2026-05-18 | KU15P (URAM) | 2,097,152 | never deployed |
| v1.1 | 2026-05-18 | KU5P (BRAM) | 1,048,576 | (superseded by v1.1.1) |
| **v1.1.1** | **2026-05-19** | **KU5P (BRAM)** | **1,048,576** | **b3miner-rtl @ HEAD (F-1 fix: ITER_MUL[7])** |

Future versions:

- v1.2 candidate: KU15P URAM with `SCRATCH_BYTES = 2 MB` once a higher-tier
  product ships. Cross-implementation parity requires a hard fork.
- v2.x candidate: post-genesis adjustments after empirical mining data;
  requires consensus change.

The version constant lives in:

- `ref/b3pow_ref.py::SPEC_VERSION`
- `rtl/params_pkg.sv::SPEC_VERSION`
- `b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h::B3_FPGA_MAGIC`
  (currently `0xB3110002` = v1.1.1 build 0002 -- bumped by F-1 fix)

Implementations MUST refuse to mine if the configured version does
not match the chain's expected version.

---

## 10. Test vectors

Authoritative test vectors live in [`ref/b3pow_ref.py`](ref/b3pow_ref.py) and
are regenerated into `sim/vectors/*.hex` by
[`ref/gen_vectors.py`](ref/gen_vectors.py).

The minimum set for any implementation claiming v1.1 compliance:

| Vector | File | Inputs | Expected output |
|---|---|---|---|
| Empty header | `vectors/full_hash.hex` line 1 | `header = 0x00..00`, `prev = 0x00..00` | (see file) |
| All-ones header | `vectors/full_hash.hex` line 2 | `header = 0xFF..FF`, `prev = 0x00..00` | (see file) |
| Genesis-like | `vectors/full_hash.hex` line 3 | (see file) | (see file) |
| BLAKE3 compress single block | `vectors/blake3_compress.hex` | (see file) | (see file) |
| Scratchpad init dump (first 64 B) | `vectors/scratch_init.hex` | `prev = 0x00..00` | (see file) |
| Single mixing iteration | `vectors/mixing_one_iter.hex` | (see file) | (see file) |
| Register-trace bringup | `vectors/regfile_trace.hex` | SPI command list | (see file) |

Implementations validate by running each vector through their code and
byte-comparing the output. The `ref/tests/` pytest suite is the
canonical validator.

---

## 11. Implementation pointers

| Layer | Path | Notes |
|---|---|---|
| Python reference (executable spec) | [`ref/b3pow_ref.py`](ref/b3pow_ref.py) | Pure-Python, no SIMD, deliberately verbose. Source of truth alongside this document. |
| RTL | [`rtl/`](rtl/) | SystemVerilog, params in `params_pkg.sv`. Parity-tested against `ref/` vectors by [`.github/workflows/b3miner-rtl.yml`](../../../.github/workflows/b3miner-rtl.yml). |
| FPGA host firmware | [`../b3miner-firmware/`](../b3miner-firmware/) | ESP32-S3 host: SPI to the FPGA, Stratum client, ATECC608B-backed identity. |
| Consensus C++ | [`../../../src/crypto/b3pow_scratch.cpp`](../../../src/crypto/b3pow_scratch.cpp) and [`.h`](../../../src/crypto/b3pow_scratch.h) | Production validator inside `b3chaind`. Exposes `b3pow::InitScratchpad` + `CBlockHeader::GetPoWHash(prev, pad, budget, &budget_exceeded)`. |
| Block header glue | [`../../../src/primitives/block.cpp`](../../../src/primitives/block.cpp) | Where `GetPoWHash()` lives; wraps `b3pow::Hash` with the per-IBD-hash time budget. |
| Consensus vectors | [`../../../src/test/data/b3pow_consensus_vectors.json`](../../../src/test/data/b3pow_consensus_vectors.json) | JSON, `schema_version=1`, `spec_version=0x00010101`. Re-derived by all parity tests above. |
| Pool TypeScript validator | [`../../testnet/pool/src/lib/b3pow-scratch.ts`](../../testnet/pool/src/lib/b3pow-scratch.ts) | Bit-exact port of `ref/b3pow_ref.py`. Used by the pool's `share-validator.ts` with an in-process per-parent pad cache (`pad-cache.ts`). |
| End-to-end verifier | [`../../testing/verify-b3pow.py`](../../testing/verify-b3pow.py) | Imports `ref/`, re-derives every vector, optionally re-derives every recent live block via RPC. |
| User-facing PoW docs | [`../../../doc/b3chain-pow-design.md`](../../../doc/b3chain-pow-design.md), [`../../../doc/mining.md`](../../../doc/mining.md), [`../../../doc/stratum.md`](../../../doc/stratum.md) | Rationale, mining workflow, pool implementer guide. |

---

## Appendix A — Why 1 MB and not 2 MB

The original v1.0 spec targeted KU15P (URAM-equipped, 36 Mb URAM = 4.5 MB)
with `SCRATCH_BYTES = 2 MB`. The KU5P retail-product target has only
1.1 Mb URAM and 16.3 Mb BRAM. To fit on-chip without external DDR4 and
to leave headroom for compressor pipelines, FIFOs, and configuration
overhead, v1.1 reduces to 1 MB (8 × 128 KB partitions, ~35 % of the
432 available BRAMs).

GPU-hostility is preserved: 1 MB still vastly exceeds any consumer GPU
SM's L1 (128 KB on RTX 4090) and per-warp L2 working set. The
data-dependency chain (16,384 reads per hash, each sequentially
dependent on prior state) is what makes the algorithm slow on GPUs,
not the absolute scratchpad size.

A v1.2 KU15P-targeted variant with 2 MB is reserved for a future
higher-tier product but **is incompatible** with v1.1 — they produce
different hashes and require a hard fork to switch between.
