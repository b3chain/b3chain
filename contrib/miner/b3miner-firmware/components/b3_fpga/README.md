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

Clock: 25 MHz, mode 0. Every transaction is exactly 40 bits (1 cmd + 4 data bytes),
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
bitstream load: `0xB3110002` (B3PoW-Scratch v1.1.1, build 0002 — the
F-1 fix bumped this from `0xB3110001`; old build-0001 bitstreams mine
the v1.1.0 algorithm and are rejected by the v1.1.1 firmware).

## Job lifecycle

```
Host                          FPGA
  |                             |
  |-- scratch_init(prev_hash) -->|  (once per block, B3PoW-Scratch)
  |<-- STATUS.scratch_ready ----|
  |                             |
  |-- write SEED[32] ----------->|
  |-- write NONCE_START/END ---->|
  |-- CTRL.start -------------->|
  |                             | hash loop
  |<-- IRQ share_found ---------|  (optional)
  |-- read NONCE, POW_HASH ----->|
  |-- CTRL.ack_share ----------->|
```

## Bitstream storage

Store KU5P bitstream in external SPI flash at offset `0x800000` (8 MB) or embed
as `b3_fpga_bitstream.bin` linked section. Typical size ~7 MB compressed.

## Test without silicon

Implement `b3_fpga_sim.c` that returns synthetic shares at 1 KH/s for Stratum
integration testing on ESP32-S3 devkit + W5500/ETH.
