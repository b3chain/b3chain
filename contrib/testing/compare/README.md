# BLAKE3 vs SHA-256 Comparative Suite

This directory holds the empirical and analytical comparisons between
B3Chain's hash function (double BLAKE3-256) and Bitcoin's (SHA-256d). The
goal is to back the claim *"BLAKE3 is a measurable improvement"* with
numbers and citations rather than rhetoric.

## Layout

| File | Type | Purpose |
|------|------|---------|
| `lib/compare_common.py`     | helper | shared timer, JSON schema, host detection |
| `compare-pow-throughput.py` | empirical | hashes/sec for SHA-256d vs BLAKE3d, raw + SIMD |
| `compare-block-validation.py` | empirical | end-to-end reindex wall time on bitcoind vs b3chaind |
| `compare-length-extension.py` | empirical | working SHA-256 LE attack demo; BLAKE3 immunity demo |
| `compare-asic-landscape.md`   | data-only | existing ASIC ecosystem (Bitcoin) vs nascent BLAKE3 ASIC market |
| `compare-energy.md`           | data-only | published BLAKE3 paper figures + estimated J/hash |
| `compare-attack-surface.md`   | data-only | CVE history per algorithm + structural comparison |
| `compare-collision-margin.md` | data-only | Merkle-Damgard vs Bao tree |
| `run-all-compare.sh`          | runner   | run every empirical comparison in sequence |
| `results/`                    | output   | JSON results for reproducibility |
| `baseline.json`               | data     | reference numbers used by `compare-bench.yml` to detect regressions |

## Quick start

```bash
# Run all empirical comparisons. Saves JSON to results/ and prints a markdown table.
bash contrib/testing/compare/run-all-compare.sh

# One comparison at a time
python3 contrib/testing/compare/compare-pow-throughput.py
python3 contrib/testing/compare/compare-block-validation.py    # needs both bitcoind and b3chaind
python3 contrib/testing/compare/compare-length-extension.py
```

## Result schema

Every empirical script writes
`results/<comparison>-<host>-<timestamp>.json` and updates
`results/latest.json` (a symlink or copy on Windows). The JSON is a single
object:

```json
{
  "comparison": "pow-throughput",
  "host":       "x86_64-linux gnu Intel(R) Core(TM) i7-...",
  "host_cores": 16,
  "timestamp":  "2026-05-13T22:18:43Z",
  "rows": [
    {"algo": "sha256d", "threads": 1, "hashes_per_sec": 4123456, ...}
  ],
  "summary": {"speedup_blake3d_vs_sha256d_single_thread": 5.2, ...}
}
```

The website hub (`b3chain.org/testing/compare.html`) reads
`results/latest.json` to populate headline numbers; if the file is absent
the hub displays "no run yet".

## Honesty caveats

- Raw hashing throughput is the **least** important number. SHA-256 has had
  20+ years of ASIC R&D; BLAKE3 has had ~5. Raw CPU comparison is a starting
  point, not a final verdict.
- The numbers vary substantially by CPU, cache size, and thermal throttling.
  Each result carries `host_cpu` and `host_cores` so you can re-interpret.
- The length-extension demo is about **construction** differences, not a
  claim that "Bitcoin is broken". Bitcoin's SHA-256**d** construction
  sidesteps length-extension intentionally.
