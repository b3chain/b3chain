# XCKU5P B3PoW-Scratch miner implementation report

Date: 2026-09-24  
Vivado: 2026.1 build 6511674  
Part: `xcku5p-ffvb676-2-e`  
Top: `xcku5p_b3miner_top`  
Miner ABI: `0xB3110003`  
Consensus version: `0x00010101`

## Correctness fixes

- The FPGA now derives `BLAKE3(header_prefix || nonce)` for every nonce.
- A pristine parent-derived 1 MiB pad is copied into the working pad before
  every nonce. Nonce 0 and nonce 1 both match independent Python fresh-pad
  vectors.
- The share target is a firmware-programmed 256-bit value.
- Share results cross through an acknowledged one-entry FIFO. Firmware ACKs
  only after validation and successful queue insertion.
- Commands use a stable mailbox/toggle handshake; hash count crosses as a
  source-registered Gray value.
- Abort waits for scratch, header-seed, and mixing engines to quiesce.
- Exact nonce count permits testing nonce `0xffffffff`; extranonce2 supports
  the advertised size up to 32 bytes.
- SPI is capped at 5 MHz for the 100 MHz oversampled slave.

## Verification

- Standalone consensus vectors: 17/17 PASS.
- Python reference/contract tests: 45 PASS.
- Verilator lint: PASS.
- Verilator testbenches: 11/11 PASS.
- Full-chip tests include fresh-pad nonce 0/1 parity and abort/restart.
- Mock Stratum test: one B3PoW share submitted, accepted, and independently
  recomputed.
- ESP-IDF 6.2 real-FPGA build: PASS.
- ESP-IDF 6.2 simulated-FPGA build: PASS.

## Vivado implementation

- Elaboration: exact part/top and ten physical ports PASS.
- Clock input: H23/H24, bank 66, `DIFF_SSTL12`, `DIFF_TERM=FALSE`.
- Clocks: 100 MHz input, 250 MHz mining, 100 MHz control, 5 MHz SPI maximum.
- Timing: WNS +0.015 ns, TNS 0; WHS +0.011 ns, THS 0.
- Schedule: 20 mining cycles per iteration (address multiply overlaps the
  former iter-done cycle). Predicted mix rate 250e6/(2048*20) = 6.10 kH/s.
  Coarser 8-step G scheduling missed 250 MHz by 1.096 ns; the closed point
  of that schedule is about 6.3 kH/s, under the 8 kH/s bar, so this
  overlap is the schedule that was built.
- Routing: 109,167 fully routed nets, zero routing errors.
- Utilization: 52,821 LUTs (24.35%), 41,220 registers (9.50%),
  456/480 BRAM tiles (95.00%), 24 DSPs, 10 bonded I/O.
- Power: Vivado vectorless estimate 2.687 W total, 2.192 W dynamic,
  0.495 W static, confidence Medium. This is not a measurement.

DRC reports 32 performance-advisory DSP pipeline warnings. Timing is met, so
they are accepted for this single-pipeline build. Methodology warnings are
reviewed: RAM output-register suggestions, wide address multipliers, expected
async-reset checks, SPI delays relative to its external clock, and the
intentional async grouping of the handshake-isolated 100/250 MHz domains.
CDC has no Critical findings; CDC-15 marks the stable bundled-data mailboxes
that are held until synchronized toggle acknowledgement.
Implementation-only constraints bound sys-to-mine mailbox skew to 4 ns and
mine-to-sys share skew to 10 ns; routed slack is +3.080 ns and +8.978 ns.

## Artifacts

- Bitstream:
  `/data/projects/b3pow-implementation/b3miner-rtl/build/xcku5p_b3miner/xcku5p_b3miner.bit`
  - size: 15,431,348 bytes
  - SHA-256: `efa6fc50a638b6c037289805f2e2272f50913001f88fc57f009dbe98b84e01c7`
- Routed checkpoint SHA-256:
  `38b91a234e9fdc7f1c11ee151eb029cb1ccc2fd39a6f7c8ec7d68ce1f620bf2e`
- Build manifest:
  `boards/xcku5p-2ffvb676/build_manifest.json`
- ESP32 real-FPGA firmware:
  - size: 905,056 bytes
  - SHA-256: `351d7d46eba2c67714e343f36ee2d9868fa3cbb34fa5b52a04a4e2111a650d46`
- ESP32 simulated-FPGA firmware:
  - size: 880,528 bytes
  - SHA-256: `3f7ab164392ae1dd39ea9cc6f2309ca50029eb764ee21c0a44b30486ee66b012`

## Hardware state

The verified autoload service volatile-programmed final share-retaining image
`ad7f897d...` over JTAG before the cable moved to ESP32 USB1. Vivado reported
XCKU5P IDCODE `0x04A62093` and startup HIGH. QSPI was not accessed.

The verified host autoload service is installed on voice-ai. It checks the
bitstream size/SHA-256 before each volatile load and is triggered at host boot
or when the scoped TUL FT2232 USB device is added.

The authorized ESP32 image is flashed. Its boot test read
`REG_ID=0xB3110003`, initialized the scratchpad, and matched fresh-pad nonce 0
and nonce 1 on the final FPGA image. The 30-minute Wi-Fi pool soak
and physical hashrate/temperature/power measurements remain NOT TESTED.
