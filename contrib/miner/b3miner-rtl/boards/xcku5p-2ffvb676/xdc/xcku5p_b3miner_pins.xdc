# XCKU5P-2FFVB676-260923 schematic-backed miner constraints.

set_property PACKAGE_PIN H23 [get_ports sys_clk_p]
set_property PACKAGE_PIN H24 [get_ports sys_clk_n]
set_property IOSTANDARD DIFF_SSTL12 [get_ports {sys_clk_p sys_clk_n}]

set_property PACKAGE_PIN AF13 [get_ports spi_sck]
set_property PACKAGE_PIN AF15 [get_ports spi_mosi]
set_property PACKAGE_PIN AF14 [get_ports spi_miso]
set_property PACKAGE_PIN AE13 [get_ports spi_csn]
set_property PACKAGE_PIN AD14 [get_ports share_irq]
set_property IOSTANDARD LVCMOS33 [get_ports {spi_sck spi_mosi spi_miso spi_csn share_irq}]

set_property PACKAGE_PIN C12 [get_ports user_key_n]
set_property IOSTANDARD LVCMOS33 [get_ports user_key_n]

set_property PACKAGE_PIN J11 [get_ports led_busy_n]
set_property PACKAGE_PIN H12 [get_ports led_share_n]
set_property IOSTANDARD LVCMOS33 [get_ports {led_busy_n led_share_n}]
set_property DRIVE 4 [get_ports {led_busy_n led_share_n}]
set_property SLEW SLOW [get_ports {led_busy_n led_share_n}]
