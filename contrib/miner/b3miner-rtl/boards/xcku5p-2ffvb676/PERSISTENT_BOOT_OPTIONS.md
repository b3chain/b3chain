# Persistent boot options

The current PCB has no ESP32-to-FPGA configuration interface.  Its ESP32
connection is user-mode SPI only.  The generic B3Miner SelectMAP loader must
remain disabled for this board.

## Option A: onboard FPGA QSPI

Use U3 (`MT25QU128ABA1ESE`) on configuration bank 0.  This is the only
standalone boot path already routed on the PCB.  It requires:

1. Verify M0/M1/M2 straps select the intended master-SPI mode.
2. Generate and size-check the exact configuration image.
3. Authorize QSPI erase/program by image SHA-256.
4. Read back and verify the image before power-cycle testing.
5. Preserve volatile JTAG recovery.

No QSPI access is authorized by the miner implementation job.

## Option B: voice-ai JTAG autoload

A user-level service can verify the `.bit` SHA-256 and volatile-program the
FPGA whenever voice-ai and the USB/JTAG bridge are available.  This does not
survive without the host and is not standalone board boot, but it avoids all
flash writes.

## Option C: board revision

Route reviewed ESP32 GPIOs to `PROGRAM_B`, `INIT_B`, `DONE`, CCLK, and DIN
through the correct voltage translation.  The generic ESP32 loader can then
be implemented and tested on that revision.

Until one option is selected, the supported configuration method is volatile
JTAG only.
