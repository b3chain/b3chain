# `r0/` — hardware configuration

The `r0/` bucket is the **first authoritative bench run** of the B3PoW-Scratch
suite, captured for the launch whitepaper, the website B3PoW landing
page, and the published charts.

Per the methodology doc, we publish the full CSV (not a cherry-picked
"best" row) and we mark every estimate / synthetic / dry-run row
clearly so charts can colour them differently.

## Bench machine — CPU benches

| Field | Value | Notes |
|---|---|---|
| Hostname | _TBD: fill at bring-up_ | local naming |
| OS | _TBD_ | typically Ubuntu LTS or Debian stable |
| Kernel | _TBD_ | uname -a |
| CPU model | _TBD_ | populated automatically into the CSV `host.cpu_model` |
| Physical cores | _TBD_ | from `os.cpu_count()` |
| Logical cores | _TBD_ | with SMT |
| CPU governor | `performance` | `cpupower frequency-set -g performance` |
| RAM | _TBD_ | DDR4-3200 or better preferred |
| Python | 3.11+ | required for `bench-b3pow-cpu.py` and `bench-b3pow-verify.py` |
| `blake3` PyPI version | _TBD_ | populated automatically into the CSV `host.blake3_version` |
| `b3chaind` build | _TBD_ | required for `bench-b3pow-cpp` |
| Compiler | _TBD_ | clang ≥ 17 or gcc ≥ 13 recommended |
| C++ optimisation | `-O3 -march=native` | release-mode build |

## Bench machine — FPGA bench

| Field | Value | Notes |
|---|---|---|
| Card | B3Miner-1 (XCKU5P single-chip) | see `contrib/miner/b3miner-hardware/SCHEMATIC.md` |
| Bitstream version | _TBD_ | RTL revision hash |
| Firmware version | _TBD_ | ESP-IDF build, git rev |
| Host clock | 200 MHz LVDS input | from SCHEMATIC.md power tree |
| Telemetry endpoint | `http://b3miner-01.lan:80` | LAN-routable, no auth at testnet |
| Wall power meter | _TBD_ | Killawatt-style at 12 V input |

## What is held constant

* CPU governor: `performance`
* Foreground load: bench machine is otherwise idle
* Network: bench host and FPGA on the same VLAN, wired
* Deterministic header corpus seed: `0xB3110002` (default)
* `prev_block_hash` seed: `0xB3C4A1F0` (default)

## What is published in this bucket

After the bring-up run completes:

```
results/r0/
├── HARDWARE.md                this file (filled in)
├── README.md                  narrative summary, mean / p95 numbers, charts
├── bench-b3pow-cpu.csv        python-ref rows (cold + warm + multi-thread)
├── bench-b3pow-cpu-<ts>.json  full result blob (one per run)
├── bench-b3pow-cpu.latest.json
├── bench-b3pow-cpp.csv        c++ consensus rows (cold + warm)
├── bench-b3pow-cpp-<ts>.json
├── bench-b3pow-cpp.latest.json
├── bench-b3pow-fpga.csv       fpga rows (live preferred; dry-run synthetic if not on the wire yet)
├── bench-b3pow-fpga-<ts>.json
├── bench-b3pow-fpga.latest.json
├── bench-b3pow-verify.csv     verifier latency rows
├── bench-b3pow-verify-<ts>.json
└── bench-b3pow-verify.latest.json
```

Plus charts under `../../charts/out/r0/`:

* `hashrate-by-backend.svg` / `.png`
* `verify-latency.svg` / `.png`
* `jhash-by-backend.svg` / `.png`  (only when J/hash is populated)
* `summary.md` — auto-generated tabular dump
