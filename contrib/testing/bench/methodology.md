# B3PoW-Scratch benchmark methodology

This document describes how the four bench scripts in this directory
produce their numbers, so that anyone reproducing the results gets the
same answers (within measurement noise) on their own hardware.

## Why bench?

The launch package and the whitepaper cite throughput, verification
latency, and (where possible) energy per hash for three implementations
of B3PoW-Scratch v1.1:

| Implementation | File | Bench script |
|---|---|---|
| Python reference | `contrib/miner/b3miner-rtl/ref/b3pow_ref.py` | `bench-b3pow-cpu.py` |
| C++ consensus | `src/crypto/b3pow_scratch.cpp` | `bench-b3pow-cpp.cpp` |
| FPGA core (B3Miner-1) | `contrib/miner/b3miner-rtl/src/` + firmware | `bench-b3pow-fpga.py` |
| Verifier latency | any of the above | `bench-b3pow-verify.py` |

All four scripts emit a **single canonical CSV schema** so a downstream
chart generator (`charts/render-charts.py`) can plot CPU, C++ and FPGA
on the same axes without per-script special-casing.

## Scope

B3PoW-Scratch is a **memory-hard, scratchpad-heavy** PoW. These benches
measure the **full** hash function, not just the BLAKE3 primitive.

For inner-primitive numbers (BLAKE3 / BLAKE3d / SHA-256 round-function
throughput), see `contrib/testing/compare/compare-pow-throughput.py`.
The two suites answer different questions; use the right tool.

## Honesty about the Python reference

`b3pow_ref.b3pow_scratch` is pure Python with no NumPy. By design it is
slow — single-digit hashes per second per core. The bench publishes
that number rather than hiding it; it serves three purposes:

1. **Correctness floor.** Every other impl is graded against the
   reference's output bytes. If the C++ or RTL impl produces different
   bytes for the same header, the reference is canonical and they are
   wrong.
2. **Pool-implementer baseline.** Pool operators porting B3PoW-Scratch
   to a new language can test their port against the same numbers our
   pool sees from the reference.
3. **Verification-cost ceiling.** If the *reference* verifies a header
   in `X` ms, the C++ impl will be roughly 100× faster and the SPEC
   §8.E target (p95 < 50 ms) gates the C++ impl, not the reference.

The bench prints a warning to this effect at the bottom of every
Python-ref run so readers don't accidentally publish reference numbers
as "B3PoW-Scratch hashrate".

## Pad cache pattern

`b3pow_ref.b3pow_scratch` (and every other impl) **mutates** the
scratchpad in place. A miner or verifier that hashes many headers
against the same parent must therefore either:

* re-run `init_scratchpad(prev_hash)` for every hash (the "cold" path,
  ~5–7 ms of overhead per hash on x86_64), **or**
* keep a *pristine* (unmutated) copy of the initialised pad and hand out
  a *fresh mutable copy* per hash (the "warm" path, ~0 ms init
  overhead, just a 1 MB memcpy).

The bench measures both paths so the cache impact is visible. The
production cpuminer, pool validator, and `b3chaind` all use the warm
pattern via a `PadCache` (Python) or a `b3pow::PadPtr` (C++).

## Deterministic corpus

Verifier latency benches use a deterministic 80-byte header corpus seeded
by `0xB3110002` (B3Miner-1 magic). Two runs on the same machine measure
the *same* corpus; deltas are timing noise, not corpus differences. The
seed can be overridden with `--seed=N` but the default is the canonical
one used for the published `results/r0/` numbers.

## Power and J/hash

`j_per_hash` is populated only when an out-of-band wall-power reading
is available. The bench framework exposes `measure_power_watts()` in
`lib/bench_common.py`; the default returns `None` and the bench writes
`NaN` for the column. Operators with a USB power analyser or
`B3POW_BENCH_POWER_CMD` shell hook can wire in real measurements without
changing the bench script.

For the published `results/r0/` numbers, J/hash is reported on the FPGA
card (measured at the 12 V input) and on the CPU bench machine
(measured at the wall via a Killawatt-style meter). CPU J/hash is
inherently noisy because the bench machine is doing other things;
treat it as ±20 % accurate.

## Reproducing the published `r0` run

The `r0/` bucket is the **first authoritative run** of the bench suite,
captured for the launch whitepaper and website. To reproduce:

```bash
# Hardware: see results/r0/HARDWARE.md for the exact bench machine.
# Software: blake3 (PyPI), Python 3.11+, optional matplotlib, optional
#           a built b3chaind with bench-b3pow-cpp target enabled.

cd contrib/testing/bench

# Python reference (≈ 30 s on a modern x86_64)
python3 bench-b3pow-cpu.py --iterations 5 --threads 1,n --run-id r0

# C++ consensus (≈ 10 s for warm + cold, after building)
./build/bench-b3pow-cpp --both --iters 64 --csv results/r0/bench-b3pow-cpp.csv

# Verifier latency (≈ 1–2 min at default corpus-size=10000 on Python ref;
# minutes faster on cpp)
python3 bench-b3pow-verify.py --corpus-size 10000 --run-id r0

# FPGA — requires B3Miner-1 reachable on the LAN
python3 bench-b3pow-fpga.py --endpoint http://b3miner-01.lan:80 --window 60 --run-id r0
# Without hardware, get a synthetic placeholder row:
python3 bench-b3pow-fpga.py --dry-run --expected-hps 8e6 --run-id r0

# Render charts
pip3 install matplotlib    # if not already
python3 charts/render-charts.py --run-id r0
```

The CSV schema is identical across all four scripts; charts join on
`backend` + `label`.

## What is held constant across runs

For the published numbers:

* Header corpus: deterministic (seed `0xB3110002`)
* `prev_block_hash`: deterministic (seed `0xB3C4A1F0`)
* Iteration count: 5 (CPU bench) / 64 (C++ bench) / 10 000 (verifier)
* Thread counts: `1, n` (where `n = os.cpu_count()`)
* CPU governor: `performance` (we do not measure on `powersave`; that
  is a separate energy-only run)
* Foreground load: bench machine is idle; no IDE, no browser, no
  background docker
* Network: bench machines wired (no wifi), FPGA on the same VLAN as
  the bench host

## What we will NOT do

* **No cherry-picking.** The whole CSV ships, not just the best row.
* **No turbo gaming.** Single-row "world record" numbers are not
  published; we publish the steady-state distribution.
* **No vendor-supplied numbers.** Where a vendor (e.g. Xilinx) ships a
  hashrate estimate for a BRAM macro, we cite it as such and never as
  a measured B3Miner-1 number.
* **No "estimated" numbers without that label.** Any row in the FPGA
  bench that was generated with `--dry-run` has `backend=fpga-dry` and
  a clearly-marked synthetic note. Charts colour them differently.

## Continuous trending

`contrib/testing/audit/audit-bench-trend.py` ingests the CSV bucket
across runs and computes regression deltas (a row in `r1` vs `r0` for
the same backend + label triggers a flag if hashrate dropped > 10 %
without an explanatory note). This guards against unwitting performance
regressions in the C++ impl during refactoring.

## Cross-references

* Spec: `contrib/miner/b3miner-rtl/SPEC.md` (esp. §5 algorithm, §8.E
  verification-cost target)
* Whitepaper: `doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md` §
  "Verification cost" cites verifier bench p95 numbers
* FPGA analysis: `doc/analysis/FPGA-FEASIBILITY.md` is the algebra
  behind the FPGA bench's dry-run defaults
* Pool implementer: `doc/stratum.md` § "Scratchpad caching" describes
  the same warm-cache pattern the bench uses
