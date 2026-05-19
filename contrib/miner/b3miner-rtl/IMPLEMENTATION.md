# IMPLEMENTATION.md — week-by-week phasing

This is the engineering rollout plan. The tree was bootstrapped in one
sitting, so the deliverable for each phase is **stable, byte-parity-tested
RTL** rather than line counts.

> **v1.1.1 rebuild required (F-1 fix).** The constant table at
> `params_pkg.sv::ITER_MUL[7]` changed from `0xE7037ED1A0B428DB`
> (duplicate of `ITER_MUL[1]`) to `0x6E5C6F88AA5BDA77` (pairwise
> distinct).  `SPEC_VERSION` bumped to `0x00010101` and the firmware
> magic `REG_ID_MAGIC` bumped to `0xB3110002`.  Any synthesised
> bitstream older than this commit **will not match** the consensus
> vectors and must be rebuilt.  Quick path:
>
> ```bash
> cd b3chain/contrib/miner/b3miner-rtl
> make clean
> python ref/tests/test_b3pow_ref.py          # confirms vectors are at v1.1.1
> make synth impl bin                           # produces v1.1.1 bitstream
> python build/verify_bin.py                    # confirms MD5
> ```
>
> Firmware boot expects `FPGA ID = 0xB3110002` after this rebuild.
> See [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../../../doc/security/B3POW-51-ATTACK-ANALYSIS.md)
> F-1 for the rationale.

Each phase's gate is a passing test in `ci/sim.sh` (Verilator or XSIM).
The Python reference in `ref/b3pow_ref.py` is **the** spec — RTL is
derived from it, not the other way around.

## Phase 0 — Infra (weeks 1–2)

- [x] Tree skeleton, Vivado TCL, Verilator harness, GitHub Actions CI
- [x] `SPEC.md` frozen at v1.1
- [x] `ref/b3pow_ref.py` + pytest suite, produces every `sim/vectors/*.hex`
- [x] `make lint` green on empty modules

**Gate:** `make ref-test` green; `make lint` green.

## Phase 1 — Primitives (weeks 3–5)

- [x] `rtl/blake3_compress.sv` — 7-round compressor, 1 chunk/cycle pipeline
- [x] `rtl/blake3_xof.sv` — XOF wrapper for `scratch_init`

**Gate:** `tb_blake3_compress` / `tb_blake3_xof` byte-match
`sim/vectors/blake3_compress.hex` and `blake3_xof.hex`.

## Phase 2 — SPI + regfile (weeks 6–7)

- [x] `rtl/spi_slave.sv` — 40-bit mode-0 slave at 25 MHz
- [x] `rtl/regfile.sv` — every offset in
  [`b3_fpga_regs.h`](../b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h)

**Gate:** `tb_regfile` exercises the firmware's bring-up SPI trace
verbatim (`sim/vectors/regfile_trace.hex`).

## Phase 3 — Scratchpad (weeks 8–10)

- [x] `rtl/scratchpad_mem.sv` — 8 × 128 KB true-dual-port BRAM bank
- [x] `rtl/scratch_init.sv` — BLAKE3-XOF chain to fill the pad

**Gate:** `tb_scratch_init` reproduces `sim/vectors/scratch_init.hex`
for `prev_block_hash = 0x00..00` and one random non-zero vector.

## Phase 4 — Mixing core (weeks 11–13)

- [x] `rtl/mixing_core.sv` — 8-lane B3PoW-Scratch inner loop
- [x] `rtl/target_compare.sv` — int-LE comparator

**Gate:** `tb_mixing_core` byte-matches `sim/vectors/mixing_one_iter.hex`
and the full-hash vector for `header = 0x00..00`.

## Phase 5 — Top integration (weeks 14–15)

- [x] `rtl/b3miner_top.sv` — chip wrapper, MMCM, reset, SelectMAP gating
- [x] `rtl/pow_top.sv` — IDLE → SCRATCH_INIT → MINING → SHARE FSM
- [x] `rtl/xadc_monitor.sv` — die temp → `REG_TEMP_RAW`

**Gate:** `tb_b3miner_top` drives the SPI port using
`sim/vectors/regfile_trace.hex` and sees `STATUS.share_valid` rise with
the expected `nonce`/`pow_hash` from `full_hash.hex`.

## Phase 6 — Timing + HW-in-loop (week 16)

Full procedure: [`docs/TIMING_CLOSURE.md`](docs/TIMING_CLOSURE.md) and
[`docs/HWLOOP.md`](docs/HWLOOP.md).

- [ ] Run `make impl` on a Vivado-equipped workstation; iterate
  `xdc/b3miner_timing.xdc` + `build/synth.tcl` retiming pragmas until
  WNS ≥ 0 at 250 MHz mining clock.  Auto-explore via
  `make timing-explore`.
- [ ] Generate `b3miner.bin` with SelectMAP byte order (`make bin`).
- [ ] Run `python build/verify_bin.py` to check size + sync + record MD5.
- [ ] Bring up on an Avnet AES-XCKU5P-EVAL or equivalent dev kit:
   1. Wire ESP32-S3 GPIO 10–13 + GPIO 26/27 to the FMC SPI/SelectMAP pads
      per [`../b3miner-hardware/SCHEMATIC.md`](../b3miner-hardware/SCHEMATIC.md)
      §5.3.
   2. Flash `b3miner.bin` into firmware partition `bitstream` (16 MB).
   3. Build firmware with `CONFIG_B3_FPGA_SIM=n` and run.
   4. Point Stratum URL at a local regtest pool
      (see [`../testnet/pool/README.md`](../testnet/pool/README.md)).
   5. Verify ≥ 1 share/min and `read die °C` stable < 70 °C with passive
      heatsink.

**Gate:** firmware (sim disabled) submits real B3PoW-Scratch shares to
the regtest pool for ≥ 30 minutes with no hash-mismatch rejection.

## Out of scope for v0

See [`SPEC.md`](SPEC.md) §"Out of scope" — DDR4, GTH transceivers,
legacy double-BLAKE3, multi-pipeline, multi-chip, KiCad layout, test
fixture.

## Quick bring-up recipe (Phase 6, copy-paste)

```bash
# 1) Build bitstream (on Vivado host)
cd b3chain/contrib/miner/b3miner-rtl
make synth impl bin
# Output: build/artifacts/b3miner.bin

# 2) Flash bitstream + firmware (on ESP32-S3 dev host)
cd ../b3miner-firmware
idf.py -DCONFIG_B3_FPGA_SIM=n build
esptool.py --chip esp32s3 write_flash 0x800000 ../b3miner-rtl/build/artifacts/b3miner.bin
idf.py flash monitor

# 3) Verify
# Expect within ~10 s of boot:
#   I (xxxx) b3_fpga: FPGA ID = 0xB3110002 (OK, v1.1.1)
#   I (xxxx) b3_fpga: SCRATCH ready
#   I (xxxx) b3_stratum_v1: subscribed, job=...
#   I (xxxx) b3_fpga_worker: share submitted nonce=0x... ntime=0x...
```
