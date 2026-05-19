# Changelog

All notable changes to `b3miner-rtl` are recorded here. Newest entries on top.

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
