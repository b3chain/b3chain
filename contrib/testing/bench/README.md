# `contrib/testing/bench/` — B3PoW-Scratch v1.1 benchmarks

Benchmarks for the **full** B3PoW-Scratch v1.1 PoW (memory-hard, 1 MB
scratchpad, 16 384 RMW rounds per hash). For inner-primitive numbers
(BLAKE3 vs SHA-256 round-function throughput), see
[`../compare/`](../compare/).

| Script | What it measures |
|---|---|
| [`bench-b3pow-cpu.py`](bench-b3pow-cpu.py) | Python-reference impl throughput (cold + warm pad cache, single + multi-thread) |
| [`bench-b3pow-cpp.cpp`](bench-b3pow-cpp.cpp) | C++ consensus impl throughput (cold + warm; optional Google Benchmark mode) |
| [`bench-b3pow-fpga.py`](bench-b3pow-fpga.py) | B3Miner-1 FPGA throughput via telemetry endpoint (or `--dry-run` synthetic row) |
| [`bench-b3pow-verify.py`](bench-b3pow-verify.py) | Single-block verifier latency at p50 / p95 / p99 across a deterministic header corpus |

All four scripts emit the same canonical CSV schema (defined in
[`lib/bench_common.py`](lib/bench_common.py)) so the chart generator at
[`charts/render-charts.py`](charts/render-charts.py) can plot every
backend on the same axes.

## Quick start

```bash
# Dependencies: blake3 (always); matplotlib (charts only).
pip3 install blake3
pip3 install matplotlib

cd contrib/testing/bench

# Python reference — slow on purpose (single-digit H/s/core)
python3 bench-b3pow-cpu.py --iterations 5

# C++ consensus — fast; requires a build
cmake --build build --target bench-b3pow-cpp
./build/bench-b3pow-cpp --both --iters 64 --csv results/r0/bench-b3pow-cpp.csv

# Verifier latency — the bench that gates SPEC §8.E (target p95 < 50 ms)
python3 bench-b3pow-verify.py --quick                # corpus=200, < 1 min
python3 bench-b3pow-verify.py --corpus-size 10000    # full

# FPGA throughput — needs a B3Miner-1 reachable on the LAN
python3 bench-b3pow-fpga.py --endpoint http://b3miner-01.lan:80 --window 60
# … or synthetic placeholder
python3 bench-b3pow-fpga.py --dry-run --expected-hps 8e6

# Charts (after running the four benches above)
python3 charts/render-charts.py --run-id r0
```

## Layout

```
contrib/testing/bench/
├── README.md                       this file
├── methodology.md                  what we measure, what we hold constant
├── bench-b3pow-cpu.py              python-ref throughput bench
├── bench-b3pow-cpp.cpp             c++ consensus impl bench (compile via CMake)
├── bench-b3pow-fpga.py             FPGA telemetry-driven bench
├── bench-b3pow-verify.py           verifier latency bench
├── lib/
│   └── bench_common.py             shared host detect, CSV/JSON writers, percentiles
├── charts/
│   └── render-charts.py            matplotlib chart generator
└── results/
    └── r0/                         first authoritative run (CSVs + JSONs committed)
        ├── HARDWARE.md             bench machine config
        ├── README.md               narrative of the r0 run
        ├── bench-b3pow-cpu.csv     (committed)
        ├── bench-b3pow-cpp.csv     (committed)
        ├── bench-b3pow-fpga.csv    (committed; rows marked fpga-dry until bring-up)
        └── bench-b3pow-verify.csv  (committed)
```

## Results buckets

Bench output goes to `results/<run-id>/`. By default `run-id=r0`; set
`B3POW_BENCH_RUN_ID=rN` or pass `--run-id rN` to capture a new bucket
without overwriting the canonical one.

## CSV schema

All four benches share this 14-column schema (see
[`lib/bench_common.py::CSV_HEADERS`](lib/bench_common.py)):

```
timestamp, bench, label, backend, threads,
iterations, wall_s,
hashes_per_s, ns_per_hash,
p50_ms, p95_ms, p99_ms,
j_per_hash, note
```

`backend` is the cross-script join key. Known values:

| Backend | Source |
|---|---|
| `python-ref` | `bench-b3pow-cpu.py` |
| `cpp-consensus` | `bench-b3pow-cpp.cpp` |
| `fpga-live` | `bench-b3pow-fpga.py` against a real card |
| `fpga-dry` | `bench-b3pow-fpga.py --dry-run` (algebraic placeholder) |
| `verify` | `bench-b3pow-verify.py` |

## Plan reference

Phase 1.3 of the launch package
([`../../../doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../../../doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md)
§ Verification cost), plus the
[`charts/render-charts.py`](charts/render-charts.py) outputs that feed
Phase 2.2 (chart publication).

## See also

* Spec: [`contrib/miner/b3miner-rtl/SPEC.md`](../../miner/b3miner-rtl/SPEC.md)
* Reference impl: [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../../miner/b3miner-rtl/ref/b3pow_ref.py)
* C++ impl header: [`src/crypto/b3pow_scratch.h`](../../../src/crypto/b3pow_scratch.h)
* FPGA registers: [`contrib/miner/b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h`](../../miner/b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h)
* Pool implementer guide: [`doc/stratum.md`](../../../doc/stratum.md)
* Inner-primitive comparisons: [`contrib/testing/compare/`](../compare/)
