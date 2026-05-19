# B3PoW-Scratch v1.1 vs SHA-256d (PoW-level comparison)

This is the *PoW-level* companion to the BLAKE3-primitive throughput
comparisons in this directory. It zooms out from "how fast is the
inner hash" to "what does an ASIC have to do to beat a commodity CPU
on this PoW?".

Cross-reference:
[`SPEC.md`](../../miner/b3miner-rtl/SPEC.md) is the normative
B3PoW-Scratch v1.1 algorithm spec.

## Side-by-side

| Property | SHA-256d (Bitcoin) | B3PoW-Scratch v1.1 (B3Chain) |
|---|---|---|
| Inner round function | SHA-256 (Merkle-Damgard) | BLAKE3 (Bao tree) |
| State per attempt | 32 bytes | **1 048 576 bytes** (1 MB scratchpad) |
| Lanes | 1 | 8 (4-way mixed) |
| Inner rounds per nonce | 2 | 2048 outer * 2 inner = **4096** |
| Memory bandwidth required | trivial (fits in L1) | 8 lanes * 64 B = **~512 B / attempt** of working set, dominated by ~1 MB pad re-reads |
| Time per attempt on CPU | ~1.5 µs | ~700 µs (median, single-thread) |
| ASIC speed-up upper bound | ~10^7 x (mature market, custom ALUs) | bounded by **on-die SRAM/HBM bandwidth**; commercially typical 1-3 GB/s per chip - **~1 000-3 000 x** over a 1-thread CPU, not 10^7 x |
| Verifier wall-clock budget | none | **50 ms** (consensus.b3pow_verify_budget_ms) |
| Verifier cache | not needed | per-`prev_block_hash` LRU (`b3pow::Cache`), 4 entries by default (~4 MB) |

## Why this matters

The headline number is the **ASIC speed-up upper bound**. A SHA-256d
ASIC ekes out enormous gains because the algorithm fits inside a
single 32-byte register file; the entire pipeline can be made
combinational and pipelined to 1-3 GHz with O(10^4) parallel pipelines
on one die. A B3PoW-Scratch ASIC cannot do that: every nonce needs to
read megabytes of memory in a data-dependent pattern, and the silicon
real estate that would otherwise go to "more pipelines" instead has
to be spent on more SRAM. The ASIC advantage caps near the
**memory-bandwidth-per-watt** frontier, which the GPU/CPU market is
already on.

## Honesty caveats

- "1 000-3 000 x" is an upper-bound estimate from analogous
  memory-bound PoW deployments (RandomX, Equihash 144/5). Real B3PoW
  ASICs are not deployed at scale at the time of writing, so this
  number will be refined as data appears.
- Memory-hardness is a **defense in depth** layer on top of the
  identity-hash isolation audited at [H-1] - it does not make a
  weak PoW algorithm strong, it makes a strong PoW algorithm harder
  to ASIC.
- Wall-clock budget enforcement (`b3pow_verify_budget_ms`) and the
  HEADERS verification cap (`MAX_B3POW_VERIFY_PER_BATCH`) are
  audited separately at [H-1.1] and [H-1.3]; this file only covers
  the algorithmic comparison.

## Source data

- Bitcoin SHA-256d ASIC market structure: see
  [`compare-asic-landscape.md`](compare-asic-landscape.md).
- BLAKE3 primitive throughput: see
  [`compare-pow-throughput.py`](compare-pow-throughput.py) and
  `results/`.
- Memory bandwidth-per-watt: GDDR6X cards observe ~1.5 GB/s/W
  on memory-bound workloads.
