# B3Miner-1 FPGA ↔ ESP32-S3 SPI protocol

## Physical layer

| Signal | ESP32-S3 pin (rev A) | FPGA pin |
|--------|----------------------|----------|
| SPI_CLK | GPIO12 | FPGA_CCLK / SPI_SCK |
| SPI_MOSI | GPIO11 | SPI_MOSI |
| SPI_MISO | GPIO13 | SPI_MISO |
| SPI_CS | GPIO10 | SPI_CS_N |
| SHARE_IRQ | GPIO4 | SHARE_FOUND (open-drain OK) |
| PROG_B | GPIO5 | PROGRAM_B (bitstream load — FILL IN) |
| INIT_B | GPIO6 | INIT_B (input) |
| DONE | GPIO7 | DONE (input) |

Clock: 5 MHz maximum, mode 0. Every transaction is exactly 40 bits (1 cmd + 4 data bytes),
for both reads and writes.

## SPI wire format

```
Bit  | 39 38 37 ... 32 | 31 .................. 0
Field| cmd byte        | 32-bit data (little-endian)

cmd byte = {WR(1)/RD(0), word_index[6:0]}
word_index = byte_offset_in_register_map / 4   (header constants are byte offsets)
```

This gives 128 addressable 32-bit words (= 512 bytes of register space),
which covers `REG_POW_HASH` at byte offset 0x100 (word index 0x40).

For reads, MOSI bytes 1..4 are don't-care; the FPGA drives MISO with
the 32-bit register value, LSB first per byte.

## Register map

See `include/b3_fpga_regs.h`. The `#define`s are byte offsets; the SPI
driver converts to word index by right-shift by 2. Magic ID after
bitstream load: `0xB3110003` (B3PoW-Scratch v1.1.1, miner ABI build
0003). Older builds lack per-nonce header hashing and are rejected.

## Job lifecycle

```
Host                          FPGA
  |                             |
  |-- scratch_init(prev_hash) -->|  (once per block, B3PoW-Scratch)
  |<-- STATUS.scratch_ready ----|
  |                             |
  |-- write HEADER_PREFIX[76] -->|
  |-- write SHARE_TARGET[32] --->|
  |-- write NONCE_START/END ---->|
  |-- CTRL.start -------------->|
  |                             | hash loop
  |<-- IRQ share_found ---------|  (optional)
  |-- read NONCE, POW_HASH ----->|
  |-- CTRL.ack_share ----------->|
```

## Bitstream storage

The generic B3Miner-1 design can store a compressed image in ESP32 flash.
The XCKU5P-2FFVB676 PCB does not route ESP32 configuration signals, so that
profile is JTAG-only unless FPGA QSPI receives separate authorization.

## Test without silicon

Implement `b3_fpga_sim.c` that returns synthetic shares at 1 KH/s for Stratum
integration testing on ESP32-S3 devkit + W5500/ETH.
