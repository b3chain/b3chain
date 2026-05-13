# Energy comparison — SHA-256 vs BLAKE3

## What "energy per hash" means in PoW

Two completely different numbers travel under the same name and are
constantly confused:

1. **Algorithm energy** — joules to compute one hash on hardware optimised
   for that algorithm. This is what BLAKE3 vs SHA-256 papers measure.
2. **Network energy** — total grid energy a chain spends per second on PoW.
   This depends almost entirely on the price of the coin and the cost of
   electricity, **not** on the algorithm. Bitcoin and a hypothetical
   identical-difficulty BLAKE3 chain would consume roughly the same
   network energy if the rewards were the same.

This document is about (1), the algorithm. (2) is a property of the
*network*, not the hash function, and B3Chain's mainnet network energy is
unknowable until launch.

## Algorithm energy: published numbers

| Algorithm        | Hardware            | Throughput (single core) | J/hash (estimate) | Source |
|------------------|---------------------|--------------------------|-------------------|--------|
| SHA-256          | Antminer S21 XP Hyd | ~473 TH/s                | ~6.4e-15 J/hash   | Bitmain spec |
| SHA-256          | x86 single core (AVX2) | ~140 MH/s             | ~5.0e-9 J/hash    | OpenSSL bench, 65W |
| BLAKE3           | x86 single core (AVX-512) | ~1.0 GH/s          | ~6.5e-10 J/hash   | BLAKE3 paper figs |
| BLAKE3           | NVIDIA RTX 4090     | ~120 GH/s                | ~2.7e-12 J/hash   | published miner numbers |
| BLAKE3 (no SIMD) | x86 single core     | ~250 MH/s                | ~2.6e-9 J/hash    | BLAKE3 paper figs |

**Headline**: on the same general-purpose CPU, BLAKE3 is roughly an order
of magnitude lower J/hash than SHA-256, primarily because of SIMD
parallelism and the `compress_in_place` design avoiding extra memory
shuffling. On dedicated ASIC, the comparison flips because SHA-256 ASICs
exist and are highly tuned, and BLAKE3 ASICs effectively don't.

## What the numbers mean for B3Chain

- **Pre-ASIC era (year 1)**: B3Chain mined on commodity CPUs/GPUs is more
  energy-efficient per hash than Bitcoin mined on commodity CPUs/GPUs. The
  total network energy is still set by the difficulty curve and the value
  of B3C, not by the algorithm.
- **Post-ASIC era**: this efficiency gap closes as BLAKE3 ASICs appear.
  At steady state, both chains converge to roughly the same energy-per-USD
  spent on hashing, regardless of which algorithm is in use.

## What we explicitly do NOT claim

- "BLAKE3 is greener than SHA-256 PoW." False at the network level. PoW
  energy is set by token price and electricity cost.
- "B3Chain will use less energy than Bitcoin." Unknown — depends on
  B3C's market value, which is undetermined.
- "BLAKE3 is more efficient." True only when comparing equivalent hardware.

## Sources

- BLAKE3 paper (O'Connor, Aumasson, Neves, Wilcox-O'Hearn 2020):
  github.com/BLAKE3-team/BLAKE3-specs/blob/master/blake3.pdf
- OpenSSL `speed sha256` benchmarks on Intel 12th gen (AVX2):
  openssl-library.org/source/old/3.0/
- Bitmain Antminer S21 XP Hyd spec: shop.bitmain.com
- NVIDIA RTX 4090 BLAKE3 throughput: bzminer release notes
- Cambridge Bitcoin Electricity Consumption Index (network-level energy
  context): ccaf.io/cbnsi/cbeci

## Methodology notes

- "J/hash" for ASICs is taken directly from the manufacturer's J/TH spec
  divided by 1e12. ASIC numbers assume 100% duty cycle and ignore cooling
  overhead (typically +5–15%).
- "J/hash" for general-purpose CPUs assumes the chip's TDP is fully spent
  on the hashing thread. Actual energy is somewhat lower because adjacent
  cores are idle and the package power is shared.
- We have not run our own physical-power measurement. The
  [SECURITY-ROADMAP](../../doc/SECURITY-ROADMAP.md) item "continuous
  benchmark CI" includes a future task to wire up an actual power meter
  to a dedicated benchmark machine.
