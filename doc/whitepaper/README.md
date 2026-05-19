# B3PoW-Scratch whitepaper

Source: [`B3POW-SCRATCH-WHITEPAPER.md`](B3POW-SCRATCH-WHITEPAPER.md).

This is the public-facing, informative description of B3PoW-Scratch
v1.1. The **normative** specification is
[`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md);
the **executable** reference is
[`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py).

## Render

```
make pdf        # B3POW-SCRATCH-WHITEPAPER.pdf via pandoc + xelatex
make html       # B3POW-SCRATCH-WHITEPAPER.html (self-contained)
make repro      # SOURCE_DATE_EPOCH-pinned build + SHA256 manifest
make clean
```

Build prerequisites:

- Debian/Ubuntu: `sudo apt install pandoc texlive-xetex texlive-fonts-recommended texlive-latex-extra librsvg2-bin`
- macOS: `brew install pandoc tectonic librsvg`

`make pdf` uses XeLaTeX with the Latin Modern font family that ships
with every TeX Live distribution; no external font downloads required.

## How this fits with other docs

- [`README.md`](../../README.md) — project entry-point.
- [`SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) — normative
  algorithm specification.
- [`b3pow_ref.py`](../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) —
  bit-exact executable reference (Python).
- [`b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp) —
  consensus C++ implementation.
- [`b3pow-scratch.ts`](../../contrib/testnet/pool/src/lib/b3pow-scratch.ts) —
  pool TypeScript port (CI-gated parity).
- [`b3chain-pow-design.md`](../b3chain-pow-design.md) — rationale
  document (shorter than the whitepaper; user-facing).
- [`mining.md`](../mining.md), [`stratum.md`](../stratum.md) —
  miner / pool integration docs.
- [`articles/why-b3pow-scratch.md`](../articles/why-b3pow-scratch.md) —
  Hacker-News-style technical article.
- [`preprint/B3POW-SCRATCH-PREPRINT.tex`](../preprint/B3POW-SCRATCH-PREPRINT.tex) —
  IACR ePrint LaTeX source (full proofs, academic format).

## Versioning

The whitepaper version is the `SPEC_VERSION` it describes. Current:
`0x00010101` (v1.1.1). Any change to `SPEC_VERSION` requires a
companion update to this whitepaper and the appendix `References`
table.
