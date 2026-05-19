# B3Chain Proof-of-Work Design

## Status

The **normative** specification for B3Chain's Proof-of-Work algorithm
is [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md).
The Python reference implementation at
[`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py)
is bit-exact with the consensus C++ code at
[`src/crypto/b3pow_scratch.cpp`](../src/crypto/b3pow_scratch.cpp);
consensus vectors live at
[`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json).
Anything that disagrees with those three files is wrong.

This document is the **rationale** — why the algorithm looks the way it
does and how it slots into the dual-hash architecture. For test
vectors, byte layouts, and constants, follow the pointers above.

## Overview

B3Chain uses a **dual-hash architecture** where two different hash
functions serve distinct roles:

| Purpose | Algorithm | Function |
|---------|-----------|----------|
| **Proof-of-Work (PoW)** | **B3PoW-Scratch v1.1** (BLAKE3 + 1 MB scratchpad) | `CBlockHeader::GetPoWHash(prev, pad, …)` |
| **Block identity / merkle trees** | Double SHA-256 | `CBlockHeader::GetHash()` |

Departing from Bitcoin's SHA-256d-for-everything approach provides:

- **No carry-over from existing SHA-256d ASICs** — those farms cannot
  mine B3Chain at any difficulty. Mining starts from a clean hardware
  field.
- **Memory-hard PoW** — the 1 MB working set with 16 384 sequential,
  data-dependent read–modify–write rounds is intentionally
  GPU-hostile and ASIC-expensive-to-shrink (BRAM area dominates).
- **Bitcoin-compatible identity layer** — every other hash on the wire
  (txids, merkle root, block ID) is still SHA-256d, so the P2P
  framing, headers, and explorer UX match Bitcoin.

## B3PoW-Scratch v1.1 at a glance

```
PoW_hash = b3pow_scratch( header, prev_block_hash )
```

| Parameter | Value |
|---|---|
| Scratchpad | 1 MiB (1 048 576 B), split into 8 lanes of 128 KiB |
| Block size | 64 B |
| Blocks per lane | 2 048 (address space 11 bits per lane) |
| Iterations | 2 048 read-modify-write rounds |
| Inner BLAKE3 rounds per iteration | 2 (reduced) |
| Final hash | BLAKE3(concat(lane[0..7]) ‖ nonce) |
| Per-hash BLAKE3 work | ≈16 384 sequential block compressions |
| Per-hash memory traffic | ≈8 MiB read + 8 MiB write |

Every iteration: each of 8 lanes independently derives a scratchpad
address from `(lane_state ⊕ iter_idx) × ITER_MUL[L]`, reads 64 B, runs
a reduced-round BLAKE3 compression, writes back `block XOR
permuted_msg`, and shuffles state across lanes. Full step-by-step
semantics are in SPEC §5–§7.

### Why 1 MB / why this shape

| Choice | Why |
|---|---|
| 1 MB working set | Fits entirely in BRAM on a Xilinx Kintex UltraScale+ KU5P (≈35 % of available BRAM). No external DDR required → low BOM. Exceeds every consumer-GPU per-SM L1 / per-warp L2 working set, killing GPU throughput. |
| 16 384 sequential rounds | Pure data dependency chain. GPUs cannot pipeline across nonces inside the inner loop, so 10 000+ warps can't help. |
| 8 lanes × 1 RMW each | Matches an 8-port URAM/BRAM partition layout natively; FPGA reads all 8 addresses in one cycle. |
| Reduced (2-round) BLAKE3 | Mixing function is fast enough that memory bandwidth dominates, which is exactly the hardware constraint we want to bind on. |
| BLAKE3 primitive | Modern, parallelism-friendly, NIST-recognized lineage (BLAKE finalist of SHA-3), well-analyzed. |

### Implementation pointers

- **Consensus C++ (the law):**
  [`src/crypto/b3pow_scratch.cpp`](../src/crypto/b3pow_scratch.cpp)
  and [`src/crypto/b3pow_scratch.h`](../src/crypto/b3pow_scratch.h).
- **Python reference (the spec, executable):**
  [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py).
- **SystemVerilog RTL:**
  [`contrib/miner/b3miner-rtl/rtl/`](../contrib/miner/b3miner-rtl/rtl/).
- **FPGA host firmware:**
  [`contrib/miner/b3miner-firmware/`](../contrib/miner/b3miner-firmware/).
- **Pool TypeScript port (share validator):**
  [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../contrib/testnet/pool/src/lib/b3pow-scratch.ts).
- **Consensus vectors:**
  [`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json).

## Where each hash is used

### `GetPoWHash()` — B3PoW-Scratch v1.1

Used **only** for Proof-of-Work validation:

- `CheckProofOfWork()` in [`src/pow.cpp`](../src/pow.cpp)
- `b3chain-util grind` nonce search in
  [`src/bitcoin-util.cpp`](../src/bitcoin-util.cpp) (uses the long-lived
  scratchpad cache form for nonce searches)
- Block validation during IBD
- Mining (block template solving, FPGA host firmware)

The C++ signature is

```cpp
std::optional<uint256> CBlockHeader::GetPoWHash(
    const uint256& prev,
    const b3pow::Scratchpad& pad,
    std::chrono::milliseconds budget,
    bool& budget_exceeded) const;
```

`pad` is the 1 MB scratchpad initialised once per `prev` and reused
across all candidate nonces for that parent. `budget` lets the IBD
verifier bound CPU time per hash; `budget == 0` disables the limit and
is what miners use.

### `GetHash()` — Double SHA-256

Used for **everything else** — unchanged from Bitcoin Core:

- Block identity (the hash referenced in `hashPrevBlock`)
- Transaction IDs (txid)
- Merkle tree construction
- P2P protocol (block inventory, headers)
- RPC responses (`getblock`, `getblockheader`, etc.)

## Verification cost

Validating a B3PoW-Scratch hash is intentionally expensive (≈16 384
BLAKE3 block compressions over 16 MiB of memory traffic) — that is
the whole point. To keep nodes lean:

| Mitigation | Effect |
|---|---|
| Per-parent scratchpad cache | Init the 1 MB pad once per `prev`; reuse for every header that builds on that parent. Validation of N siblings drops from N init + N mix to 1 init + N mix. |
| Per-hash CPU budget (`budget` arg, IBD only) | Cap wall-clock per hash so an adversarial header history can't pin a node validator for hours. Hit → header rejected. |
| Header-only PoW pre-check | Validate PoW before downloading the block body, same as Bitcoin's headers-first sync. |

Reference numbers (single thread, 5 GHz Zen 4, AVX-512 BLAKE3): roughly
20–30 ms per B3PoW-Scratch hash including init, ≈10 ms once the pad is
warm. Mass-validating a 2 016-block retarget window costs ≈20 s of
single-core time; in practice the verifier pipelines this in parallel.

Actual measured numbers (and a methodology to reproduce them) live in
[`contrib/testing/bench/`](../contrib/testing/bench/) once the bench
harness has run on the platforms in question.

## Security considerations

1. **No SHA-256d carry-over.** A header that satisfies SHA-256d
   difficulty almost certainly does not satisfy B3PoW-Scratch
   difficulty (the two hash families are uncorrelated). Verified by
   the `pow_tests` unit test family.
2. **Identity hash unchanged.** Block identity (`hashPrevBlock`, chain
   selection, P2P inventory) is still SHA-256d, so the existing
   Bitcoin wire format is preserved unchanged.
3. **BLAKE3 lineage.** BLAKE3 is the latest member of the BLAKE family
   (BLAKE/BLAKE2 finalist for SHA-3) and is published with a formal
   spec and reference implementation. We use it as a primitive, not as
   the entirety of the PoW.
4. **Not "ASIC-proof".** A B3PoW-Scratch ASIC is possible. Memory
   hardness raises the cost-of-entry for ASIC vendors but does not
   eliminate it. The design goal is to make the per-hash advantage of
   a hypothetical ASIC over a Kintex UltraScale+ FPGA small enough
   that small operators stay economic.
5. **Not "GPU-proof", but GPU-hostile.** Sequential 1 MB working set +
   data-dependent address generation defeats GPU throughput. A GPU can
   *run* the algorithm; it just produces an order or two of magnitude
   fewer H/s/$ than the same-class FPGA. See
   [`contrib/miner/b3chain-gpuminer/README.md`](../contrib/miner/b3chain-gpuminer/README.md).
6. **51 % analysis.** A formal 51 %-attack writeup is at
   [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](security/B3POW-51-ATTACK-ANALYSIS.md).
   B3PoW-Scratch is not magically reorg-resistant; a low-hashrate
   chain at any stage is.

## BLAKE3 SIMD acceleration

The underlying BLAKE3 primitive (used both for the scratchpad init and
for the per-iteration reduced-round compression) ships
hardware-optimized implementations selected automatically at runtime
via CPUID:

| Instruction set | SIMD degree | Speed-up vs portable |
|---|---|---|
| Portable (C) | 1 | 1× (baseline) |
| SSE2 | 4 | ≈3× |
| SSE4.1 | 4 | ≈4× |
| AVX2 | 8 | ≈8× |
| AVX-512 | 16 | ≈14× |

Assembly implementations are in
`src/crypto/blake3/blake3_*_x86-64_unix.S`. The dispatch layer
(`blake3_dispatch.c`) handles runtime detection. On Windows and
non-x86 platforms, the portable C implementation is used.

## Network parameters

| Parameter | Mainnet | Testnet | Regtest |
|---|---|---|---|
| Default P2P port | 8533 | 18533 | 18544 |
| Default RPC port | 8534 | 18534 | 18543 |
| Bech32 HRP | `b3` | `tb3` | `b3rt` |
| Address prefix | `B` (0x19) | `m/n` (0x6F) | `m/n` (0x6F) |
| Config file | `b3chain.conf` | — | — |
| Data directory | `.b3chain` | — | — |

## Test coverage

The following test surfaces guard the B3PoW-Scratch implementation:

- `crypto_tests/b3pow_scratch_*` — primitive and end-to-end
  consensus-vector tests (`src/test/crypto_tests.cpp`).
- `pow_tests` — difficulty-target checking with `GetPoWHash()`.
- `miner_tests` — full block mining with B3PoW-Scratch via the
  `b3chain-util grind` code path.
- Python parity:
  `contrib/miner/b3miner-rtl/ref/tests/` (pytest) cross-checks the
  reference against the JSON consensus vectors.
- TS parity:
  `contrib/testnet/pool/test/b3pow-scratch.spec.ts` cross-checks the
  TypeScript port used by the pool against the same JSON vectors.
- End-to-end:
  `contrib/testing/verify-b3pow.py` re-derives every vector and,
  optionally with `--rpc-port`, every recent block on a live node.

## Migration history

| Version | Date | Notes |
|---|---|---|
| v0 — Double BLAKE3 | retired 2026-Q1 | Initial PoW. Replaced because BLAKE3 alone offered no memory-hardness; trivially ASIC-able by anyone willing to copy the BLAKE3 reference RTL. |
| **v1.1 (current)** | active | B3PoW-Scratch v1.1.1 (`SPEC_VERSION=0x00010101`). Locked-in F-1 fix (distinct `ITER_MUL[7]`). |
| v1.2 | reserved | KU15P-targeted 2 MB variant; incompatible with v1.1, would require a hard fork. Not in scope for mainnet launch. |

Legacy double-BLAKE3 code (the GPU kernels in
`contrib/miner/b3chain-gpuminer/`) is retained for reference only and
**will not produce valid B3Chain shares**.
