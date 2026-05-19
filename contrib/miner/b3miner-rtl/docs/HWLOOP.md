# HW-in-loop bring-up procedure

This document is the **runbook** for the first physical hardware run of
`b3miner-rtl + b3miner-firmware` on a KU5P + ESP32-S3 dev kit.

**Status:** procedure documented; will be executed once the
Avnet AES-XCKU5P-EVAL kit + ESP32-S3 devkit arrive in the lab.

## Prerequisites

### Hardware

* **Avnet AES-XCKU5P-EVAL** (or equivalent KU5P-2FFVB676E eval board).
* **ESP32-S3-DevKitC-1** (16 MB flash).
* **W5500 SPI-Ethernet breakout** for the stand-alone variant (skip for
  the PCIe-card variant covered separately).
* **USB-UART** for the ESP-IDF monitor output.
* Bench DMM + a recent ESP-IDF + recent Vivado.

### Wiring summary

Use the eval board's FMC HPC header to break out the KU5P SPI / config
pins. Cross-reference the exact ball numbers against
`build/xdc/b3miner_pins.xdc`; the wires below are signal-level only.

| Signal | ESP32-S3 GPIO | KU5P side |
|---|---|---|
| SPI_SCK | 12 | CCLK / FMC SCK |
| SPI_MOSI | 11 | D0 / FMC MOSI |
| SPI_MISO | 13 | FMC MISO |
| SPI_CSn | 10 | FMC CSn |
| PROGRAM_B | 5 | PROG_B |
| INIT_B | 6 | INIT_B |
| DONE | 7 | DONE |
| SHARE_IRQ | 4 | user IRQ |
| GND | GND | GND |

ESP32-S3 IO is 3.3 V; the KU5P bank-65 IO is 1.8 V. Use a TXS0108E
level-shifter breakout (or equivalent) on the SPI/config nets. The
exact part is called out in
[`../../b3miner-hardware/SCHEMATIC.md`](../../b3miner-hardware/SCHEMATIC.md)
§6.5.

### Software

* Vivado ML Standard 2024.1 or later (for `make synth impl bin`).
* ESP-IDF 5.2 or later.
* A reachable b3chain regtest pool (e.g. `pool.local:3333`).

## Step-by-step

The firmware exposes a small diagnostic API for bring-up, gated behind
`CONFIG_B3_DIAG_MODE=y`. All access is local: ESP-IDF monitor over USB,
no network listener needed. The API is documented in
[`../../b3miner-firmware/components/b3_fpga/include/b3_fpga.h`](../../b3miner-firmware/components/b3_fpga/include/b3_fpga.h).

### Step 1 -- bitstream load smoke-test

```bash
cd b3chain/contrib/miner/b3miner-firmware
idf.py -B build-hw -DCONFIG_B3_FPGA_SIM=n -DCONFIG_B3_DIAG_MODE=y build
idf.py -B build-hw flash monitor
```

Expected console output within 10 s of reset:

```
I (1234) b3_fpga: SPI bus init (CLK=12 MOSI=11 MISO=13 CS=10)
I (1235) b3_fpga: PROGRAM_B asserted for 250 us
I (1240) b3_fpga: INIT_B high (5 ms)
I (1242) b3_fpga: loading bitstream from flash partition (size=6453123)
I (1294) b3_fpga: DONE high (52 ms)
I (1295) b3_fpga: FPGA ID = 0xB3110001 OK
```

Diagnostic checklist if the ID line is wrong:

| Observed ID | Likely cause | Where to look |
|---|---|---|
| `0xFFFFFFFF` | FPGA not configured (DONE never high) | re-check PROG_B + INIT_B timing in the boot log |
| `0x00000000` | SPI wires mis-mapped | re-check the wiring table above against the schematic |
| `0xDEADBEEF` | DUT loaded but `regfile.sv` default lane reached host | check MISO byte order in the `regfile`/`spi_slave` post-synth report |
| anything else | mismatched bitstream | run `python build/verify_bin.py` -- the MD5 must match `build/artifacts/manifest.txt` |

### Step 2 -- register read/write self-test

The firmware diagnostic build exposes `b3_diag_*` helpers. Drive them
from the IDF monitor's command interface:

```
b3-diag reg-id            # expects REG_ID_MAGIC
b3-diag reg-loopback 0x80 0x12345678   # write+read REG_NONCE_START, compare
b3-diag reg-loopback-block REG_SEED    # writes 8 words, reads them back
```

A failure here means the SPI slave isn't decoding the wire format
correctly. The unit TB `tb_spi_slave.sv` covers the same patterns in
simulation -- if HW disagrees, re-run that TB against the latest RTL
and compare to the post-synth waveform.

### Step 3 -- scratchpad init timing

```
b3-diag scratch-init        # drives REG_PREV_HASH=0 + CTRL.scratch_init
b3-diag wait-scratch-ready  # polls STATUS until bit 2 is set
```

Expected: STATUS.scratch_ready asserts in 1.4-2.0 ms. Anything more
than 5 s means `scratch_init.sv` is stuck; attach the Vivado ILA to
`mixing_core.b3_done` and re-run.

### Step 4 -- single-hash byte-parity check

The b3pow_ref.py Python reference is the spec. To prove the FPGA's
mining path matches it for one (header, prev) pair:

```bash
# On the host: compute the reference values
cd b3chain/contrib/miner/b3miner-rtl/ref
python -c "
import b3pow_ref as r, struct
header = bytes(76) + struct.pack('<I', 0)
prev   = bytes(32)
seed   = r.blake3_hash(header)
print('seed =', seed.hex())
print('pow  =', r.b3pow_scratch(header, prev).pow_hash.hex())
"
```

Then in the IDF monitor:

```
b3-diag set-seed <seed_hex>
b3-diag set-prev 00000000...00         # 32 zero bytes
b3-diag single-shot 0                  # nonce = 0
b3-diag read-pow-hash
```

The `read-pow-hash` output must match the Python `pow` byte-for-byte.
If it doesn't, fall through the layered TBs (`tb_b3miner_top`,
`tb_mixing_core`, `tb_scratch_init`, `tb_blake3_compress`) until one
fails -- that's the layer with the bug.

### Step 5 -- regtest pool soak test

Configure a local b3chain testnet pool with maximum-easy difficulty
(see [`../../testnet/pool/README.md`](../../testnet/pool/README.md))
and point the firmware's stratum URL at it:

```
idf.py erase-flash
idf.py -DCONFIG_B3_STRATUM_DEFAULT_URL=stratum+tcp://pool.local:3333 \
       -DCONFIG_B3_STRATUM_DEFAULT_USER=b3miner-1.test build flash monitor
```

Expected steady-state behaviour after ~30 s:

* `b3_stratum_v1: subscribed, job=<id>` every job update
* `b3_fpga_worker: share submitted nonce=0x... ntime=0x...` ≥ 1/min
* `b3_stratum_v1: share accepted (#N)` ≥ 1/min
* Die temperature (`b3_fpga_read_die_celsius()`) stable below 70 °C
  with the passive heatsink defined in SCHEMATIC §5.7.

Acceptance gate: 30 minutes of operation with **zero** "share rejected
- hash mismatch" log lines. If any appear, capture the rejected
share's (header, prev_hash, nonce, pow_hash) tuple and re-run it
through `b3pow_ref.py` to identify whether the FPGA or the pool is
disagreeing.

## Failure-triage decision tree

```
boot log shows "FPGA ID OK" ?
├─ NO  -> Step 1 checklist
└─ YES -> reg-loopback passes ?
         ├─ NO  -> Step 2 (SPI / regfile.sv)
         └─ YES -> scratch_init completes ?
                  ├─ NO  -> Step 3 (scratch_init.sv / blake3_xof.sv)
                  └─ YES -> single-shot byte parity ?
                           ├─ NO  -> Step 4 layered TB fall-through
                           └─ YES -> 30-min soak ?
                                    ├─ NO  -> intermittent error: log + re-run
                                    └─ YES -> ACCEPT this revision; tag b3miner-rtl-v1.1.0
```

## What to record after a successful run

Update [`../CHANGELOG.md`](../CHANGELOG.md) with the bring-up date,
bitstream MD5, observed hashrate, observed die temperature, and the
exact Vivado strategy that closed timing (see
[`TIMING_CLOSURE.md`](TIMING_CLOSURE.md)). That snapshot is what the
next builder reproduces.
