## ============================================================================
## b3miner_falsepaths.xdc -- explicit CDC waivers
##
## Every cross-clock path declared here must have an explicit synchroniser
## in RTL.  See ../../docs/architecture.md "Clock domains" for the inventory.
## ============================================================================

# ---- SPI pins -> SYS domain via spi_slave 2-FF synchronisers ----
# spi_sck / spi_mosi / spi_csn are async inputs; the spi_slave (clk_sys)
# samples each through a 2-FF chain.  Declare the pin-to-FF launch path
# as false to keep Vivado from trying to time it against clk_spi.
set_false_path -from [get_ports {spi_sck spi_mosi spi_csn}] \
               -to   [get_pins -hierarchical -filter {NAME =~ *u_spi_slave/*_s1*}]

# ---- SYS domain -> MINE domain via pow_top.sv handshake ----
# A request pulse is launched on sys, latched on mine via 2-FF sync,
# ack pulse returns the same way.  Bit width = 1 so no skew constraint.
set_false_path -from [get_pins {u_pow_top/start_sync_reg[*]/D}] \
               -to   [get_pins {u_pow_top/start_meta_reg[*]/D}]
set_false_path -from [get_pins {u_pow_top/ack_sync_reg[*]/D}] \
               -to   [get_pins {u_pow_top/ack_meta_reg[*]/D}]

# ---- MINE domain -> SYS domain via async share-found FIFO ----
# The Xilinx FIFO macro handles its own gray-code timing; declare the
# multi-bit data path async.
set_false_path -from [get_clocks clk_mine] -to [get_clocks clk_sys] \
    -through [get_pins -hierarchical -filter {NAME =~ *u_share_fifo/wr_data*}]

# ---- Reset CDC ----
# Async reset deasserted via reset_sync in b3miner_top.sv (2-FF chain).
# Each clock domain has its own synchroniser; the source is the global
# async POR which we exclude from timing.
set_false_path -from [get_pins u_reset_sync_sys/arst_n]
set_false_path -from [get_pins u_reset_sync_mine/arst_n]
