`include "params_pkg.sv"

// Generic B3Miner-1 wrapper: 200 MHz LVDS reference, 250 MHz mining clock,
// 100 MHz control clock.  Board-specific wrappers instantiate b3miner_core.
module b3miner_top (
    input  logic clk_ref_p,
    input  logic clk_ref_n,
    input  logic spi_sck,
    input  logic spi_mosi,
    output logic spi_miso,
    input  logic spi_csn,
    output logic share_irq,
    output logic led_share,
    output logic led_busy,
    input  logic fan_tach,
    output logic fan_pwm
);
    logic clk_ref, clk_mine_raw, clk_sys_raw;
    logic clk_mine, clk_sys, mmcm_locked, mmcm_feedback;

`ifndef SIM
    IBUFGDS #(
        .DIFF_TERM("TRUE"),
        .IBUF_LOW_PWR("FALSE"),
        .IOSTANDARD("LVDS")
    ) u_ibufds_clk_ref (
        .O(clk_ref), .I(clk_ref_p), .IB(clk_ref_n)
    );

    MMCME4_ADV #(
        .BANDWIDTH("OPTIMIZED"),
        .CLKIN1_PERIOD(5.000),
        .DIVCLK_DIVIDE(1),
        .CLKFBOUT_MULT_F(5.000),
        .CLKOUT0_DIVIDE_F(4.000),
        .CLKOUT1_DIVIDE(10),
        .STARTUP_WAIT("FALSE")
    ) u_mmcm (
        .CLKIN1(clk_ref), .CLKIN2(1'b0), .CLKINSEL(1'b1),
        .CLKFBIN(mmcm_feedback), .CLKFBOUT(mmcm_feedback),
        .CLKOUT0(clk_mine_raw), .CLKOUT0B(),
        .CLKOUT1(clk_sys_raw), .CLKOUT1B(),
        .CLKOUT2(), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(),
        .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .LOCKED(mmcm_locked), .PWRDWN(1'b0), .RST(1'b0),
        .CDDCREQ(1'b0), .CDDCDONE(), .DCLK(1'b0), .DEN(1'b0),
        .DWE(1'b0), .DADDR(7'h0), .DI(16'h0), .DO(), .DRDY(),
        .PSCLK(1'b0), .PSEN(1'b0), .PSINCDEC(1'b0), .PSDONE()
    );
    BUFG u_bufg_mine (.I(clk_mine_raw), .O(clk_mine));
    BUFG u_bufg_sys  (.I(clk_sys_raw),  .O(clk_sys));
`else
    assign clk_ref = clk_ref_p;
    assign clk_mine = clk_ref;
    assign clk_sys = clk_ref;
    assign mmcm_locked = 1'b1;
`endif

    b3miner_core u_core (
        .clk_sys(clk_sys), .clk_mine(clk_mine), .arst_n(mmcm_locked),
        .spi_sck(spi_sck), .spi_mosi(spi_mosi), .spi_miso(spi_miso),
        .spi_csn(spi_csn), .share_irq(share_irq),
        .led_share(led_share), .led_busy(led_busy),
        .fan_tach(fan_tach), .fan_pwm(fan_pwm)
    );
endmodule
