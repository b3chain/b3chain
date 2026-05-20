# Changelog

All notable changes to `b3miner-rtl` are recorded here. Newest entries on top.

## v1.1.4 — miner doc cleanup + `LANE_SHUFFLE` relocation (no consensus change)

Cosmetic / source-organisation pass.  No bitstream needs rebuilding,
no consensus vector changes, no parity gate touched.

### Changed

- **`LANE_SHUFFLE` promoted to `rtl/params_pkg.sv`.**  The
  cross-lane diffusion permutation `{1, 6, 3, 0, 5, 2, 7, 4}` used to
  live as a local `LANE_PERM` inside `rtl/mixing_core.sv`; it now sits
  in `params_pkg::LANE_SHUFFLE` next to `ITER_MUL`, `BLAKE3_PERM`,
  and `BLAKE3_IV` so every consensus-locked constant lives in one
  place and the file matches `ref/b3pow_ref.py:LANE_SHUFFLE`
  name-for-name.  `mixing_core.sv` now imports it via the
  `params_pkg::*` `import` it already does.  Bit-for-bit equivalent to
  the previous local copy; `sim/vectors/*.hex` unchanged.

### Fixed (documentation only)

- **Stale `REG_ID` magic-ID references** updated from the old
  pre-F-1 build-0001 value `0xB3110001` to the current v1.1.1
  build-0002 value `0xB3110002`:
  - `README.md` (top-level RTL README)
  - `rtl/regfile.sv` (table comment; the actual driver already used
    `params_pkg::REG_ID_MAGIC`, so this was a pure stale comment)
  - `sim/tb/tb_b3miner_top.sv` (header comment; the actual test
    compared against `REG_ID_MAGIC`)
  - `docs/HWLOOP.md` (expected boot-log example)
  - `BITSTREAM_LOAD.md` (post-config readback instruction and boot-log
    example)
  Historical references inside this `CHANGELOG.md` and the unit-test
  mock value in `sim/tb/tb_spi_slave.sv` are intentionally left alone
  (the unit TB tests the SPI protocol layer, not consensus).

## v1.1.3 — cross-reference only (no RTL changes)

The b3chain v1.1.3 maintenance release lands the M-14 operator-pinned
chain recovery RPCs (`finalizeblock` / `parkblock` /
`unparkblock` / `unfinalizeblock` / `getfinalizedblockhash`) plus a
watcher detector (`detect_finalized_drift`).  None of this touches
the miner side: the RPCs live in the b3chaind RPC server and the
detector lives in the monitoring daemon.  The RTL reference and
parity vectors are unchanged.

This entry exists so the b3miner-rtl changelog tracks one-to-one
with `b3chain/doc/CHANGELOG.md` for cross-reference convenience; the
authoritative description is the v1.1.3 section there.

## v1.1.2 — first commit into b3chain-main

The tree authored in this directory had never actually been tracked
by git until the b3chain v1.1.2 maintenance release (commit
`c55c08d913` on `b3chain-main`, May 2026).  Nothing about the source
changed — every file here, including the F-1 and F-4 fixes and the
post-F-6 vectors, was already present locally — but `doc/CHANGELOG.md`
and `doc/SECURITY-ROADMAP.md` had been claiming this work was "in
tree" while it was only in the working directory.  v1.1.2 closes that
gap.

Notable contents that are now actually in version control:

- **F-1 (ITER_MUL[7] saturation fix)** — `ref/b3pow_ref.py`
  and `rtl/params_pkg.sv` agree on the corrected ITER_MUL table; all
  17 consensus vectors hash identically against `b3pow_ref.py` and
  `src/test/data/b3pow_consensus_vectors.json`.
- **F-4 (address-uniformity gate)** —
  `ref/tests/test_address_uniformity.py` exercises 2²⁰ random
  (parent, nonce, time) triples and asserts the empirical address
  histogram passes a chi-squared test against the uniform null at
  α = 1e-6.  The test is wired into the `b3miner-rtl` GitHub Actions
  workflow.
- **F-6 (post-genesis-re-mine vectors)** — `ref/gen_vectors.py`
  regenerates `src/test/data/b3pow_consensus_vectors.json` from the
  reference implementation; the workflow re-generates and `diff`s
  against the canonical file on every push.  This is how the
  post-F-6 `expected_pow_hash` values made it into the consensus
  vectors in the first place.

The first CI run after the b3chain v1.1.2 push (`e944ee16cf`) is the
first time this code was exercised end-to-end on a Linux host;
everything passed.

## [unreleased]

### Added

- `SPEC.md` — B3PoW-Scratch **v1.1** (KU5P profile, 1 MB scratchpad)
- `README.md`, `IMPLEMENTATION.md`, `BITSTREAM_LOAD.md` — tree intros
- `rtl/params_pkg.sv` — locked algorithm constants and wyhash secret table
- `ref/b3pow_ref.py` + `ref/gen_vectors.py` + `ref/tests/` — Python
  reference and pytest suite that produces every `sim/vectors/*.hex`
- `build/` — Vivado TCL flow (`create_project`, `synth`, `implement`,
  `bitstream`, `reports`) and XDC pin/timing constraints (KU5P-2FFVB676E)
- `sim/verilator/` — Verilator harness (`sim_main.cpp`, Makefile) and
  XSIM fallback (`sim/xsim/run_xsim.tcl`)
- `ci/` — `lint.sh`, `sim.sh`, `synth_oc.sh`, GitHub Actions workflow
- RTL — `blake3_compress.sv`, `blake3_xof.sv`, `spi_slave.sv`,
  `regfile.sv`, `scratchpad_mem.sv`, `scratch_init.sv`, `mixing_core.sv`,
  `target_compare.sv`, `pow_top.sv`, `xadc_monitor.sv`, `b3miner_top.sv`
- Testbenches for every RTL module under `sim/tb/`

### Changed

- `b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h` —
  corrected `B3_FPGA_MAGIC` from the invalid hex literal `0xB3M10001u`
  to `0xB3110001u` (the `M` was not a hex digit; would not have compiled)
- `b3miner-firmware/components/b3_fpga/README.md` — magic value updated
  to match.

### Fixed

- **CRITICAL (post-verify)** — SPI register reads returned the *previous*
  transaction's data instead of the just-addressed register's data.
  Root cause: `spi_slave.sv` latched `rdata_lat` at SPI bit 7, but
  `regfile.sv` only updated its address pipe on the `req_valid` pulse
  at bit 39.  The address arrived too late.  The first test in every TB
  happened to be `READ REG_ID` and `cmd_addr` reset to `0` (= `REG_ID`)
  on reset, so every existing testbench passed by coincidence.
  - Fix: `spi_slave.sv` now runs on `clk_sys` (100 MHz) and oversamples
    the async SPI pins through 2-FF synchronisers.  Address + direction
    are latched at SPI bit 7 (`cmd_addr`, `cmd_is_read`); the regfile
    drives `req_rdata` purely combinationally from the live address.
    The SPI<->regfile path is now single-clock, eliminating the CDC.
  - `regfile.sv` simplified: dropped the SPI→sys 2-FF chain; `rdata`
    is now an `always_comb` mux off `spi_req_addr`.
  - `b3miner_top.sv`: drop `reset_sync` for the SPI domain (no longer
    needed); fix `wire rst_n_async; assign ...` instead of
    initializer-style `logic` declaration.
  - `tb_spi_slave.sv` rewritten with read-after-write and non-zero-addr
    reads that would have CAUGHT this regression.
  - `tb_regfile.sv` + `tb_b3miner_top.sv` updated for the new
    single-clock interface and to cover the same regression.
  - XDC: `clk_spi` is now a *virtual* I/O-only clock; the false_path is
    from SPI input pins to the slave's `*_s1` flops, not between two
    sets of internal clocks.

### Out of scope

See [`SPEC.md`](SPEC.md) §"Out of scope for v0".
