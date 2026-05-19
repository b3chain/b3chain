## ============================================================================
## b3miner_timing.xdc -- clock + I/O timing for B3Miner-1
##
## Targets (mirrors ../../rtl/params_pkg.sv::CLK_*_MHZ):
##   clk_ref   200.0 MHz   external LVDS XO       (bank 65 MRCC)
##   clk_mine  250.0 MHz   MMCM CLKOUT0           (data path)
##   clk_sys   100.0 MHz   MMCM CLKOUT1           (control)
##   clk_spi    25.0 MHz   external (ESP32 SCK)   (bank 65, async)
## ============================================================================

# ---- External primary clocks ----
create_clock -name clk_ref -period 5.000  [get_ports clk_ref_p]
# clk_spi is a *virtual* input clock used to constrain the SPI pin timing.
# The SPI slave is internally clocked by clk_sys and oversamples the
# async SPI pins, so clk_spi has no flops inside the FPGA.
create_clock -name clk_spi -period 40.000 [get_ports spi_sck]

# ---- Derived clocks (the MMCM in b3miner_top.sv generates these) ----
# These get named automatically by Vivado from the MMCM output ports,
# but we restate them so the synthesis report has consistent names.
# (Use `report_clocks` post-synth to verify.)
create_generated_clock -name clk_mine \
    -source [get_pins u_mmcm/CLKIN1] \
    -multiply_by 5 -divide_by 4 \
    [get_pins u_mmcm/CLKOUT0]
create_generated_clock -name clk_sys \
    -source [get_pins u_mmcm/CLKIN1] \
    -divide_by 2 \
    [get_pins u_mmcm/CLKOUT1]

# ---- Clock groups ----
# clk_spi only times the SPI pins (no internal flops on this clock).  The
# SPI slave's 2-FF synchronisers cross spi_sck/mosi/csn into clk_sys
# safely, so declare the SPI virtual clock asynchronous to the MMCM
# family.
set_clock_groups -asynchronous \
    -group {clk_spi} \
    -group {clk_mine clk_sys}

# ---- I/O timing ----
# SPI is mode-0 (CPOL=0, CPHA=0): MOSI sampled on SCK rising edge,
# MISO updated on SCK falling edge.
# ESP32-S3 spec (DS, §3.10): tco_max = 7 ns, tho_min = 1 ns on MOSI.
# Allow generous margins -- we run at 25 MHz (40 ns period).
set_input_delay  -clock clk_spi  -max 12.0 [get_ports spi_mosi]
set_input_delay  -clock clk_spi  -min  2.0 [get_ports spi_mosi]
set_input_delay  -clock clk_spi  -max  8.0 [get_ports spi_csn]
set_input_delay  -clock clk_spi  -min  1.0 [get_ports spi_csn]
set_output_delay -clock clk_spi  -max 14.0 [get_ports spi_miso]
set_output_delay -clock clk_spi  -min  2.0 [get_ports spi_miso]

# Share-IRQ output to ESP -- ESP samples at 80 MHz, we have lots of margin.
set_output_delay -clock clk_sys  -max 6.0 [get_ports share_irq]
set_output_delay -clock clk_sys  -min 0.0 [get_ports share_irq]

# LEDs/fan -- DC paths, no timing required.
set_false_path -to [get_ports {led_share led_busy fan_pwm}]
set_false_path -from [get_ports fan_tach]

# ---- Maximum delay on critical paths ----
# The mixing_core inner loop is the design's bottleneck.  Bound the
# combinational delay through it; helps Vivado place denser when it has
# slack to give up.
# Adjust after the first impl run shows where the critical path actually
# lives (likely BRAM-out -> blake3_compress xor chain).
set_max_delay -from [get_cells -hierarchical -filter {NAME =~ *u_mixing/*}] \
              -to   [get_cells -hierarchical -filter {NAME =~ *u_mixing/*}] \
              4.0
