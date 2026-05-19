## ============================================================================
## b3miner_pins.xdc -- KU5P-2FFVB676E pinout for the B3Miner-1 card
##
## All ball assignments are owned by the contract house's Vivado pin-planner
## (per SCHEMATIC.md §5.2).  The values below are PLACEHOLDERS that compile
## cleanly against the part and respect bank Vcco rules; the contract house
## overrides every PACKAGE_PIN value during PCB layout.
##
## Update this file IN LOCKSTEP with:
##   - b3miner-hardware/SCHEMATIC.md (§5.2, §5.3, §6.5)
##   - b3miner-firmware/components/b3_fpga/b3_fpga.c (GPIO map)
## ============================================================================

## ---- Bank 65 (HP, 1.8V) -- SPI slave + share-IRQ + MMCM ref ----

# Reference clock (200 MHz LVDS differential pair, MRCC pins)
set_property PACKAGE_PIN  A11   [get_ports clk_ref_p]
set_property IOSTANDARD   LVDS  [get_ports clk_ref_p]
set_property PACKAGE_PIN  A10   [get_ports clk_ref_n]
set_property IOSTANDARD   LVDS  [get_ports clk_ref_n]
set_property DIFF_TERM    TRUE  [get_ports {clk_ref_p clk_ref_n}]

# SPI slave (LVCMOS 1.8V single-ended, from ESP32-S3 with 1.8/3.3V level shifter)
set_property PACKAGE_PIN  B12   [get_ports spi_sck]
set_property IOSTANDARD   LVCMOS18 [get_ports spi_sck]
set_property PACKAGE_PIN  C12   [get_ports spi_mosi]
set_property IOSTANDARD   LVCMOS18 [get_ports spi_mosi]
set_property PACKAGE_PIN  D12   [get_ports spi_miso]
set_property IOSTANDARD   LVCMOS18 [get_ports spi_miso]
set_property PACKAGE_PIN  E12   [get_ports spi_csn]
set_property IOSTANDARD   LVCMOS18 [get_ports spi_csn]

# Share-found IRQ output to ESP32-S3 (active high, level-shifted)
set_property PACKAGE_PIN  F12   [get_ports share_irq]
set_property IOSTANDARD   LVCMOS18 [get_ports share_irq]

## ---- Bank 84 (HR, 3.3V) -- LEDs, fan ----

# Activity LED (active high, drives a SOT-23 N-MOSFET → 3 V LED string)
set_property PACKAGE_PIN  AB22  [get_ports led_share]
set_property IOSTANDARD   LVCMOS33 [get_ports led_share]
set_property PACKAGE_PIN  AC22  [get_ports led_busy]
set_property IOSTANDARD   LVCMOS33 [get_ports led_busy]

# Fan tach in (open-drain from fan), fan PWM out (25 kHz to fan tach pin)
set_property PACKAGE_PIN  AD22  [get_ports fan_tach]
set_property IOSTANDARD   LVCMOS33 [get_ports fan_tach]
set_property PULLUP       TRUE  [get_ports fan_tach]
set_property PACKAGE_PIN  AE22  [get_ports fan_pwm]
set_property IOSTANDARD   LVCMOS33 [get_ports fan_pwm]

## ---- Configuration bank (bank 0) -- straps + JTAG ----

## PROGRAM_B, INIT_B, DONE are dedicated config-bank pins (Vivado
## automatically constrains them; no PACKAGE_PIN required).  The
## firmware drives PROGRAM_B and senses INIT_B/DONE via ESP GPIOs
## per SCHEMATIC §5.3.

## ---- DRIVE-strength + slew for everything in bank 65 ----
## SPI runs at 25 MHz which is well within FAST slew at default DRIVE.

set_property SLEW FAST  [get_ports {spi_sck spi_miso spi_csn share_irq}]
set_property DRIVE 8    [get_ports {spi_miso share_irq}]

## ---- DDR4 (bank 66) -- DNI on R0, footprint only ----
## When populated, add a separate xdc/b3miner_ddr4.xdc with the bank-66
## pinout, and instantiate the MIG IP.  Until then, leave bank 66 floating
## with the default pulldowns from create_project.tcl.
