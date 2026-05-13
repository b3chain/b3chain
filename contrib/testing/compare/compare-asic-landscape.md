# ASIC Landscape — SHA-256 vs BLAKE3

## Why this matters for B3Chain

When B3Chain is brand new, the question that matters most is **"who can mine
it from day one?"**. Bitcoin's SHA-256 has a 15-year head start on
specialised hardware; BLAKE3 has effectively none. That asymmetry is the
single biggest reason B3Chain is launching on a different PoW: a chain that
is dominated by a small number of ASIC operators on day one is much easier
to 51% attack than one whose initial security comes from a large pool of
commodity CPUs and GPUs.

This is a data-only document. None of these numbers come from us; they are
collected from public sources cited at the bottom.

## SHA-256 ASIC ecosystem (as of writing)

| Manufacturer  | Flagship product           | Hash rate (single unit) | Approx J/TH |
|---------------|----------------------------|------------------------|-------------|
| Bitmain       | Antminer S21 XP Hyd        | ~473 TH/s              | ~13.5       |
| MicroBT       | WhatsMiner M66S            | ~298 TH/s              | ~18.5       |
| Canaan        | Avalon A14 Pro             | ~250 TH/s              | ~22.5       |
| Bitdeer Tech  | SealMiner A2               | ~226 TH/s              | ~16.0       |
| Auradine      | AT2880                     | ~600 TH/s (water)      | ~14.5       |

**Total network**: ~700+ EH/s (700 000 000 TH/s) as of mid-2026; held
across ~30 publicly traded miners plus an unknown long tail. Top 5 pools
control >75% of hashpower.

## BLAKE3 ASIC ecosystem

There is no public BLAKE3 ASIC product. The reasons:

- BLAKE3 was published Jan 2020; the first chain to use it for PoW (Alephium)
  launched late 2021. The economic incentive to design a BLAKE3 ASIC has
  existed for ~4 years, vs ~16 for SHA-256.
- BLAKE3's tree structure makes a naive ASIC less efficient than for SHA-2:
  the parallelism that BLAKE3 exposes is already extracted by GPU/CPU SIMD,
  so the ASIC speed-up over a top GPU is smaller in absolute terms.
- A handful of GPU miners (Bzminer, GMiner, lolMiner) support BLAKE3 family
  algorithms (`alephium`, `kaspa-blake3`); estimated at ~$100K total capex
  to reach 100 GH/s on commodity GPUs.

**Implication for B3Chain**: in year one the cost-of-attack is bounded by
the CPU/GPU rental market on EC2/Vast.ai/Akash, which is much more diffuse
than the SHA-256 ASIC market. We make no claim this lasts forever — once
B3Chain has economic value, ASICs will follow. The roadmap addresses this
in the BLAKE3 ASIC tracking item.

## What this comparison is NOT

- **Not a claim that BLAKE3 is "ASIC-resistant"**. No PoW algorithm is
  truly ASIC-resistant; the question is the cost gap between the best ASIC
  and the best commodity hardware. For SHA-256 today that gap is ~10x in
  J/hash; for BLAKE3 it is much smaller because the ASIC barely exists.
- **Not a claim that BLAKE3 PoW is more secure**. SHA-256 PoW is enormously
  secure precisely *because* the ASIC market is so large and competitive.
  BLAKE3 PoW is more *decentralised in its initial distribution*, which is
  a different security property.

## Sources

- Bitmain product page (Antminer S21 XP Hyd): bitmain.com/products
- MicroBT product page (M66S): whatsminer.com
- Canaan A14 Pro: canaan.io/product/avalon-a14
- Bitdeer Tech press release Q3 2025: bitdeer.com/news
- Auradine spec sheet: auradine.com
- Bitcoin total hashrate: blockchain.info/charts/hash-rate
- Alephium hashrate / GPU miner support: alephium.org
- BLAKE3 paper (Jack O'Connor et al., 2020): github.com/BLAKE3-team/BLAKE3-specs

## Update protocol

This document should be re-checked every 6 months. The key signals to
watch for are:

1. A public BLAKE3 ASIC product announcement.
2. A specific miner's BLAKE3 hashrate exceeding 1 PH/s.
3. The first BLAKE3 mining pool to control >25% of any major BLAKE3 chain.

Any of these triggers a reassessment of B3Chain's launch-time security
margin and may motivate the checkpoint ceremony described in
[`SECURITY-ROADMAP.md`](../../doc/SECURITY-ROADMAP.md).
