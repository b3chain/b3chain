// XCKU5P-2FFVB676 board wrapper.
module xcku5p_b3miner_top (
    input  logic sys_clk_p,
    input  logic sys_clk_n,
    input  logic spi_sck,
    input  logic spi_mosi,
    output logic spi_miso,
    input  logic spi_csn,
    output logic share_irq,
    input  logic user_key_n,
    output logic led_busy_n,
    output logic led_share_n
);
    logic clk_ref, clk_mine_raw, clk_sys_raw;
    logic clk_mine, clk_sys, mmcm_feedback, mmcm_locked;
    logic led_busy, led_share, unused_fan_pwm;

    IBUFDS #(
        .DIFF_TERM("FALSE"),
        .IBUF_LOW_PWR("FALSE"),
        .IOSTANDARD("DIFF_SSTL12")
    ) u_clock_input (
        .I(sys_clk_p), .IB(sys_clk_n), .O(clk_ref)
    );

    MMCME4_ADV #(
        .BANDWIDTH("OPTIMIZED"),
        .CLKIN1_PERIOD(10.000),
        .DIVCLK_DIVIDE(1),
        .CLKFBOUT_MULT_F(10.000),
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

    b3miner_core u_core (
        .clk_sys(clk_sys),
        .clk_mine(clk_mine),
        .arst_n(mmcm_locked),
        .spi_sck(spi_sck),
        .spi_mosi(spi_mosi),
        .spi_miso(spi_miso),
        .spi_csn(spi_csn),
        .share_irq(share_irq),
        .led_share(led_share),
        .led_busy(led_busy),
        .fan_tach(1'b0),
        .fan_pwm(unused_fan_pwm)
    );

    assign led_busy_n = ~led_busy;
    assign led_share_n = ~led_share;
    wire _unused_user_key_n = user_key_n;
endmodule
