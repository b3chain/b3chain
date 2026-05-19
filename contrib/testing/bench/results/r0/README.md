# `r0/` — first authoritative B3PoW-Scratch bench run

This directory is the **canonical first run** of the B3PoW-Scratch
benchmark suite, captured for the launch whitepaper, the website
B3PoW landing page, and the chart generator.

It contains the published CSV / JSON rows that downstream consumers
(whitepaper PDF render, website charts, regression-trend audit) read
from.

## What is here

* [`HARDWARE.md`](HARDWARE.md) — bench-machine configuration; what to
  hold constant when reproducing.
* `bench-b3pow-cpu.csv` — Python-reference impl rows (cold / warm /
  multi-thread).
* `bench-b3pow-cpp.csv` — C++ consensus impl rows (cold / warm).
* `bench-b3pow-fpga.csv` — B3Miner-1 FPGA rows (live where the card is
  on the wire, `fpga-dry` synthetic rows otherwise).
* `bench-b3pow-verify.csv` — verifier latency rows (p50 / p95 / p99
  across a deterministic 10 000-header corpus).
* `*.latest.json` and `*-<ts>.json` — full result blobs per run with
  host metadata.

## Status

This bucket is a **stable placeholder** at launch. The CSVs are
committed empty (header-only) or with a small set of "fpga-dry"
synthetic rows that match the algebraic estimate in
[`doc/analysis/FPGA-FEASIBILITY.md`](../../../../doc/analysis/FPGA-FEASIBILITY.md).
Real CPU-bench numbers populate on the first contributor's run of:

```bash
cd contrib/testing/bench
python3 bench-b3pow-cpu.py --iterations 5 --threads 1,n --run-id r0
python3 bench-b3pow-verify.py --corpus-size 10000  --run-id r0
./build/bench-b3pow-cpp --both --iters 64 \
    --csv results/r0/bench-b3pow-cpp.csv
```

Real FPGA numbers populate when the B3Miner-1 reaches bench bring-up;
the bench is wired up to drop rows in without any other code change.

## Honesty notes

* Python-ref rows are **single-digit H/s/core by design**. They serve
  as the correctness floor and the verification-cost ceiling, not as a
  competitive mining rate.
* `fpga-dry` rows are algebraic placeholders. Charts colour them
  distinctly from live numbers; the `note` column always says
  `"dry-run synthetic"`.
* `j_per_hash` is `NaN` unless the operator wired an out-of-band wall
  power reading. See [`../../methodology.md`](../../methodology.md) §
  *Power and J/hash*.

## Reproducing

Full instructions in [`../../methodology.md`](../../methodology.md) §
*Reproducing the published `r0` run*.

## Plan reference

Phase 1.3 (this bench suite) of
[`b3pow-scratch_launch_package`](../../../../../.cursor/plans/b3pow-scratch_launch_package_c6f10175.plan.md);
Phase 2.2 (chart publication) consumes the CSVs in this directory and
emits the SVGs into the whitepaper and website.
