# BITSTREAM_LOAD.md — firmware ↔ FPGA SelectMAP-Serial contract

This is the **contract** between
[`b3miner-firmware/components/b3_fpga/b3_fpga.c::b3_fpga_load_bitstream_from_flash()`](../b3miner-firmware/components/b3_fpga/b3_fpga.c)
and the bitstream produced by this tree (`build/artifacts/b3miner.bin`).
Both sides must agree on the byte order, signal mapping, and timing.

---

## 1. Physical layer

Five signals between ESP32-S3 and XCKU5P, all shared with normal-mode
SPI register access:

| Function | ESP32-S3 GPIO | XCKU5P pin (per SCHEMATIC §5.3) | Direction during config | Direction after `DONE`=1 |
|---|---|---|---|---|
| Config clock | GPIO 12 | `CCLK` (dedicated) | ESP → FPGA | unused (SPI CLK on GPIO 12 drives `SCK`) |
| Config data | GPIO 11 | `D0` / `DIN`             | ESP → FPGA | SPI `MOSI` |
| Done sense | GPIO 13 | `DONE` (open-drain)      | FPGA → ESP | unused |
| Program-B | GPIO 10 | `PROGRAM_B`              | ESP → FPGA (active low) | unused |
| Init-B | GPIO 26 | `INIT_B`                 | FPGA → ESP (active low) | unused |
| CSn / M0 | GPIO 27 | `MODE[0]` strap + `CSn`  | strap | SPI chip-select |

Mode pins on the XCKU5P are strapped (per SCHEMATIC §5.3) for
**slave-serial** (`M[2:0] = 111`).

## 2. Bitstream byte order

Vivado's default `.bin` output is **MSB-first per byte**, matching
SelectMAP. The `build/bitstream.tcl` flow uses:

```tcl
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 1 [current_design]
write_bitstream -bin_file -force build/artifacts/b3miner
```

This produces:

- `build/artifacts/b3miner.bin` — raw bits, ready for SelectMAP-serial load
- `build/artifacts/b3miner.bit` — Vivado wrapper format (debug only)

For slave-serial load, the firmware shifts out `b3miner.bin` **bit by
bit, MSB-first**, on each rising edge of `CCLK`. No bit-reversal
required — Vivado's `-bin_file` is already in slave-serial byte order.

**Common pitfall:** *do not* try to load a `.bit` file directly — it
has a Vivado header that the FPGA will reject. Always use `.bin`.

## 3. Load sequence

The firmware implements this exact sequence (see
[`b3_fpga.c::b3_fpga_load_bitstream_from_flash`](../b3miner-firmware/components/b3_fpga/b3_fpga.c)):

1. Drive `PROGRAM_B` low for ≥ 250 µs (assert reset)
2. Release `PROGRAM_B` high, wait for `INIT_B` to go high (FPGA ready
   for config; typ. ≤ 5 ms for KU5P)
3. For each byte of `b3miner.bin`:
   - For bit `b in [7..0]`:
       - Drive `D0` = bit value
       - Pulse `CCLK` (rising edge clocks the bit)
4. Send at least **64 extra CCLK pulses** with `D0 = 0` (startup
   sequence)
5. Wait for `DONE` to go high (typ. ≤ 50 ms for KU5P at 25 MHz CCLK)
6. Switch GPIO 11–13 to SPI peripheral mode
7. Read `REG_ID` over SPI — must return `0xB3110002` (v1.1.1 build 0002;
   the F-1 fix bumped this from the original `0xB3110001` build 0001 —
   see `CHANGELOG.md` v1.1.2 entry)

If `INIT_B` goes low after `PROGRAM_B` rises **but before step 4
completes**, the FPGA detected a CRC error — abort and retry (up to
3 times before reporting failure).

If `DONE` doesn't go high within 200 ms, the bitstream is corrupt or
the wire mapping is wrong — log and abort.

## 4. Timing constraints

| Signal | Min | Typ | Max | Notes |
|---|---|---|---|---|
| `CCLK` frequency | 1 MHz | 25 MHz | 50 MHz | KU5P slave-serial max is 100 MHz; we use 25 MHz to share SPI clock |
| `PROGRAM_B` low pulse | 250 µs | 1 ms | — | per UG570 §5 |
| `D0` setup before `CCLK` rise | 5 ns | — | — | trivial for ESP32-S3 |
| `D0` hold after `CCLK` rise | 0 ns | — | — | trivial |
| `INIT_B` low → ready | — | 5 ms | 50 ms | post-`PROGRAM_B` |
| `DONE` high after last bit | — | 20 ms | 200 ms | includes startup sequence |

## 5. Bitstream size and storage

XCKU5P-2FFVB676E bitstream is **~12.3 MB** uncompressed,
**~6.5 MB** with `BITSTREAM.GENERAL.COMPRESS TRUE`. The firmware's
`bitstream` partition (per
[`partitions.csv`](../b3miner-firmware/partitions.csv)) is **8 MB**,
which leaves ~1.5 MB of headroom for future feature growth.

If `make bin` produces a `.bin` larger than 7.5 MB, the firmware will
refuse to flash it — bump the partition size in `partitions.csv`
**before** producing the OTA image.

## 6. SelectMAP gating in `b3miner_top.sv`

During config (`DONE = 0`), the dedicated config-pin path inside
the XCKU5P drives `CCLK`/`D0` to the configuration engine. The user
RTL (this tree) is **not active** yet, so no gating logic is required
in `b3miner_top.sv` for those pins.

After `DONE = 1`, the same physical pins become user I/O and are routed
to `spi_slave.sv` via the constraints in
[`build/xdc/b3miner_pins.xdc`](build/xdc/b3miner_pins.xdc). The
firmware switches its GPIO mux at the same instant.

## 7. Post-build verification

After `make bin` succeeds, run the verifier:

```bash
python build/verify_bin.py
# file:  .../b3miner.bin
# size:  6,543,210 bytes  (6.24 MB)
# sync:  AA 99 55 66 at offset 16
# md5:   ab12cd34...
# recorded .../artifacts/manifest.txt
```

The `manifest.txt` produced here is what the firmware's OTA pipeline
reads to refuse to flash a bitstream whose MD5 doesn't match the
expected build artefact.

## 8. Test recipe

On a Vivado host, after `make synth impl bin`:

```bash
ls -la build/artifacts/b3miner.bin
# expect 6–8 MB
md5sum build/artifacts/b3miner.bin
# record this for the firmware OTA manifest

# Upload to ESP32-S3
esptool.py --chip esp32s3 --port /dev/ttyUSB0 \
    write_flash 0x800000 build/artifacts/b3miner.bin
```

Boot the firmware and watch the log:

```
I (1234) b3_fpga: loading bitstream (6453123 bytes)
I (1289) b3_fpga: PROGRAM_B asserted
I (1290) b3_fpga: INIT_B high (5 ms)
I (1342) b3_fpga: DONE high (52 ms)
I (1343) b3_fpga: FPGA ID = 0xB3110002 OK
```

A mismatch means either the bitstream is for a different target
(`XCKU5P-2FFVB676E` only), or the wire mapping changed without
updating both sides.
