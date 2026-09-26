# XCKU5P-2FFVB676 miner board contract

This profile targets the production part `xcku5p-ffvb676-2-e` on the
`XCKU5P-2FFVB676-260923` schematic.  The locked schematic SHA-256 is
`d998cf69d8f473b555960a34d5135bc56c2b37aec62a1285ea7545d907f363b5`.

## FPGA user-I/O contract

| Function | RTL port | Net | FPGA ball | Bank / rail | Standard | Direction |
|---|---|---|---|---|---|---|
| 100 MHz clock P | `sys_clk_p` | `SYS_CLK_P` | H23 | 66 / VDD1.2 | DIFF_SSTL12 | input |
| 100 MHz clock N | `sys_clk_n` | `SYS_CLK_N` | H24 | 66 / VDD1.2 | DIFF_SSTL12 | input |
| SPI clock | `spi_sck` | `ESP32_SPI_CLK` | AF13 | 84 / VDD_Bank84 | LVCMOS33 | input |
| SPI MOSI | `spi_mosi` | `ESP32_SPI_MOSI` | AF15 | 84 / VDD_Bank84 | LVCMOS33 | input |
| SPI MISO | `spi_miso` | `ESP32_SPI_MISO` | AF14 | 84 / VDD_Bank84 | LVCMOS33 | output |
| SPI chip select | `spi_csn` | `ESP32_SPI_CS` | AE13 | 84 / VDD_Bank84 | LVCMOS33 | input |
| Share IRQ | `share_irq` | `ESP32_RX1` | AD14 | 84 / VDD_Bank84 | LVCMOS33 | output |
| Reserved user key | `user_key_n` | `USER_KEY` | C12 | 87 / VDD3.3 | LVCMOS33 | input |
| Busy LED | `led_busy_n` | `LED2` | J11 | 86 / VDD3.3 | LVCMOS33 | active-low output |
| Share LED | `led_share_n` | `LED3` | H12 | 87 / VDD3.3 | LVCMOS33 | active-low output |

The clock uses external resistor R58; the input buffer must keep
`DIFF_TERM("FALSE")`.  The clock standard remains the user's accepted
engineering assumption, not a measured loaded-swing result.

Bank 84 is powered by `VDD_Bank84`.  Page 13 shows U13 (TMI3255TF), R99
33.2 kOhm and R102 10 kOhm generating this rail; page 4 uses the same rail
for the ESP32-S3 module.  The intended user-I/O standard is LVCMOS33.

## ESP32 module-side mapping

| Net | ESP32-S3 GPIO | Module pin |
|---|---|---|
| `ESP32_SPI_CS` | GPIO10 | 18 |
| `ESP32_SPI_MOSI` | GPIO11 | 19 |
| `ESP32_SPI_CLK` | GPIO12 | 20 |
| `ESP32_SPI_MISO` | GPIO13 | 21 |
| `ESP32_TX1` | GPIO17 | 10 |
| `ESP32_RX1` / share IRQ | GPIO18 | 11 |

This mapping is direct schematic evidence from page 4.  It supersedes the
placeholder GPIO descriptions in the generic B3Miner-1 documentation.
The clk_sys-oversampled slave is limited to 5 MHz.

## Configuration boundary

This PCB does **not** connect ESP32 GPIOs to `PROGRAM_B`, `INIT_B`, `DONE`,
or the dedicated configuration data pins.  Page 6 connects bank-0
configuration pins to the onboard MT25QU128 QSPI device, JTAG, and board
control circuitry.  Therefore the generic ESP32 SelectMAP loader cannot
configure this PCB without a hardware modification.

Bring-up must use volatile JTAG.  Standalone persistent boot would require
an explicitly authorized FPGA-QSPI flow or a board revision.  No QSPI write
is authorized by this contract.

## Unused generic B3Miner-1 ports

The current PCB profile has no verified miner fan tach/PWM pair.  The board
wrapper must tie `fan_tach` inactive and must not drive an unverified fan
pin.  Ethernet, DDR, PCIe, QSFP, and configuration-flash pins are outside
this miner profile.
