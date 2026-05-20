# b3miner-rtl

[![rtl ci](https://github.com/b3chain/b3chain/actions/workflows/b3miner-rtl.yml/badge.svg?branch=b3chain-main)](https://github.com/b3chain/b3chain/actions/workflows/b3miner-rtl.yml)

FPGA RTL tree for the **B3Miner-1**, the reference hardware miner for
B3PoW-Scratch v1.1. B3Miner-1 is engineered to be the most economical
production miner for this algorithm at launch — a custom B3PoW ASIC
is possible (see [`SPEC.md`](SPEC.md) §8.D) but the design goal of
B3PoW-Scratch is to keep the per-hash advantage of such an ASIC over
this FPGA card small enough that hobbyists and small operators stay
competitive.

- **Target:** Xilinx Kintex UltraScale+ **XCKU5P-2FFVB676E** (industrial grade)
- **Algorithm:** B3PoW-Scratch v1.1 (see [`SPEC.md`](SPEC.md))
- **Host interface:** SPI mode-0 slave at 25 MHz (driven by ESP32-S3, see
  [`../b3miner-firmware/`](../b3miner-firmware/))
- **Performance target:** ≥ 20 kH/s single pipeline @ 250 MHz, ≤ 8 W
- **Tooling:** Vivado ML Standard (free edition supports KU5P), Verilator for sim

This is the **sibling** of:

- [`../b3miner-firmware/`](../b3miner-firmware/) — ESP32-S3 firmware that loads
  this bitstream over SelectMAP-Serial and drives it via SPI
- [`../b3miner-hardware/`](../b3miner-hardware/) — PCB schematics and BOM for
  the production card

The host **register map is locked** in
[`../b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h`](../b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h)
— RTL must reply with magic `0xB3110002` to a read of `REG_ID = 0x00`
(v1.1.1 build 0002; the F-1 fix bumped this from the original
`0xB3110001` build 0001 — see [`CHANGELOG.md`](CHANGELOG.md) v1.1.2).

---

## Quick start

```
# Python reference + test vectors (no Vivado required)
make ref-test
make vectors

# RTL lint (Verilator)
make lint

# RTL sim (Verilator)
make sim

# Vivado out-of-context synth (per leaf module)
make synth-oc

# Full project build (synth + impl + bitstream)
make synth
make impl
make bin            # b3miner.bin (SelectMAP bit-order)
make report
```

See [`IMPLEMENTATION.md`](IMPLEMENTATION.md) for the week-by-week phasing and
[`BITSTREAM_LOAD.md`](BITSTREAM_LOAD.md) for the firmware load contract.

---

## Tree

```
b3miner-rtl/
├── SPEC.md                  authoritative B3PoW-Scratch v1.1 spec
├── README.md                this file
├── IMPLEMENTATION.md        week-by-week plan
├── BITSTREAM_LOAD.md        firmware SelectMAP loader contract
├── CHANGELOG.md
├── Makefile                 top-level convenience targets
├── rtl/                     SystemVerilog source
├── ref/                     Python reference + vector generator
├── sim/                     Testbenches + Verilator/XSIM harness
├── build/                   Vivado TCL + XDC + reports
├── ci/                      lint + sim + synth shell scripts
└── docs/                    diagrams and protocol notes
```

---

## Status (auto-updated)

| Subsystem | Status | Notes |
|---|---|---|
| `SPEC.md` | Done | v1.1 frozen pre-genesis |
| `ref/b3pow_ref.py` | Done | golden Python reference |
| `params_pkg.sv` | Done | constants locked |
| Vivado TCL flow | Done | runnable on a host with Vivado 2024.1+ |
| XDC constraints | Done | pins per SCHEMATIC §5.2 |
| Verilator harness | Done | + GitHub-Actions CI |
| `blake3_compress.sv` | Done | TB green vs `vectors/blake3_*.hex` |
| `blake3_xof.sv` | Done | TB green |
| `spi_slave.sv` | Done | TB green vs firmware bring-up trace |
| `regfile.sv` | Done | every offset in `b3_fpga_regs.h` covered |
| `scratchpad_mem.sv` | Done | 8 × 128 KB BRAM-banked, true-dual-port |
| `scratch_init.sv` | Done | TB green vs `vectors/scratch_init.hex` |
| `mixing_core.sv` | Done | TB green vs `vectors/full_hash.hex` |
| `target_compare.sv` | Done | int-LE comparator |
| `pow_top.sv` | Done | IDLE → SCRATCH_INIT → MINING → SHARE FSM |
| `b3miner_top.sv` | Done | MMCM + reset sync + SelectMAP gating |
| `xadc_monitor.sv` | Done | die-temp → `REG_TEMP_RAW` |
| Timing closure | Open | requires actual Vivado run on host |
| HW-in-loop bring-up | Open | requires Avnet AES-XCKU5P eval board |

---

## CI

The active CI workflow for this subtree lives at the repo top level:

[`.github/workflows/b3miner-rtl.yml`](../../../.github/workflows/b3miner-rtl.yml)

It auto-runs on every `push` to `b3chain-main` (and any `release/*`
branch) and on every `pull_request` targeting those branches whose
diff touches **any** of:

- `contrib/miner/b3miner-rtl/**`
- `src/crypto/b3pow_scratch.{h,cpp}`
- `src/test/data/b3pow_consensus_vectors.json`
- the workflow file itself

Four jobs gate the merge:

| Job | What it checks |
|---|---|
| `pytest-vectors` | `ref/tests/` pytest suite + the `consensus_vectors.json` mirror at `src/test/data/` is byte-identical to the one at `ref/vectors/` + `contrib/testing/verify-b3pow.py` |
| `lint-rtl` | `verilator --lint-only -Wall` over every `rtl/*.sv` file via `make lint` |
| `sim-vector-parity` | Builds + runs every Verilator TB under `sim/tb/` against the regenerated reference vectors via `make sim` |
| `spec-version-check` | `SPEC_VERSION` agrees byte-for-byte across `ref/b3pow_ref.py`, `src/crypto/b3pow_scratch.h`, `rtl/params_pkg.sv`, and `contrib/testnet/pool/src/lib/b3pow-scratch.ts` |

To reproduce each gate locally from this directory:

```
# pytest reference suite
pip install -r ref/requirements.txt
pytest -q ref/tests/

# consensus-vector mirror parity
diff -u ../../../src/test/data/b3pow_consensus_vectors.json \
        ref/vectors/consensus_vectors.json

# end-to-end vector verifier
python3 ../../testing/verify-b3pow.py

# verilator lint (apt install verilator first)
make lint

# verilator sim parity
make sim
```

The legacy per-subtree workflow at
[`ci/github-actions.yml`](ci/github-actions.yml) is preserved for
external mirrors but is now `workflow_dispatch:`-only and never fires
automatically. Add new gates to the top-level workflow, not there.

## See also

- [`../../../doc/stratum.md`](../../../doc/stratum.md) — Stratum V1/V2 details
- [`../../../doc/SECURITY-INHERITANCE.md`](../../../doc/SECURITY-INHERITANCE.md)
  — why SHA-256d remains the block-identity hash
- [`SPEC.md`](SPEC.md) §10 — full test-vector list
- [`docs/architecture.md`](docs/architecture.md) — block diagram + clock domains
- [`docs/TIMING_CLOSURE.md`](docs/TIMING_CLOSURE.md) — Phase 6 runbook
- [`docs/HWLOOP.md`](docs/HWLOOP.md) — first-silicon bring-up runbook
