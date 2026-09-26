create_clock -name sys_clk_100mhz -period 10.000 [get_ports sys_clk_p]
create_clock -name spi_clk_5mhz -period 200.000 [get_ports spi_sck]

create_generated_clock -name clk_mine_250mhz \
    -source [get_pins u_mmcm/CLKIN1] \
    -multiply_by 10 -divide_by 4 \
    [get_pins u_mmcm/CLKOUT0]
create_generated_clock -name clk_sys_100mhz \
    -source [get_pins u_mmcm/CLKIN1] \
    -multiply_by 10 -divide_by 10 \
    [get_pins u_mmcm/CLKOUT1]

set_clock_groups -asynchronous \
    -group {spi_clk_5mhz} \
    -group {clk_mine_250mhz} \
    -group {clk_sys_100mhz}

set_input_delay  -clock spi_clk_5mhz -max 12.0 [get_ports spi_mosi]
set_input_delay  -clock spi_clk_5mhz -min  2.0 [get_ports spi_mosi]
set_input_delay  -clock spi_clk_5mhz -max  8.0 [get_ports spi_csn]
set_input_delay  -clock spi_clk_5mhz -min  1.0 [get_ports spi_csn]
set_output_delay -clock spi_clk_5mhz -max 14.0 [get_ports spi_miso]
set_output_delay -clock spi_clk_5mhz -min  2.0 [get_ports spi_miso]

set_output_delay -clock clk_sys_100mhz -max 4.0 [get_ports share_irq]
set_output_delay -clock clk_sys_100mhz -min  0.0 [get_ports share_irq]

# USER_KEY is an asynchronous reset source.  The reset synchronizers mark
# their two stages ASYNC_REG; only the package-pin-to-reset path is excluded.
set_false_path -from [get_ports user_key_n]

# Human-visible indicators have no receiving clock.
set_false_path -to [get_ports {led_busy_n led_share_n}]
