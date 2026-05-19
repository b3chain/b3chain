// ============================================================================
// b3miner_top.sv -- chip-level wrapper for the B3Miner-1 KU5P bitstream.
//
// Pin connectivity (per ../build/xdc/b3miner_pins.xdc):
//
//   clk_ref_{p,n}  : 200 MHz LVDS XO (bank 65 MRCC)
//   spi_*          : 25 MHz mode-0 SPI slave to ESP32-S3
//   share_irq      : level-high IRQ to ESP32-S3
//   led_share      : pulses on every share-found
//   led_busy       : on while mining
//   fan_tach       : open-drain from fan
//   fan_pwm        : 25 kHz PWM to fan tach pin
//
// Clock plan (mirrors ../docs/architecture.md):
//
//   clk_ref  200 MHz  -> MMCM CLKIN1
//   clk_mine 250 MHz  -> MMCM CLKOUT0  (data path)
//   clk_sys  100 MHz  -> MMCM CLKOUT1  (control)
//   clk_spi  25 MHz   -> external spi_sck (async)
//
// Reset distribution:
//   - SYSRSTN held low until MMCM locked AND POR done (~10 ms).
//   - Per-clock-domain reset synchronisers in `reset_sync` cells.
//   - The SPI domain uses its own reset_sync clocked by spi_sck.
//
// During FPGA configuration (DONE = 0) the dedicated config-pin path
// drives CCLK and D0 directly to the config engine.  After DONE = 1
// the same balls become user I/O routed to spi_sck and spi_mosi.
// ============================================================================

`include "params_pkg.sv"

module b3miner_top
    import params_pkg::*;
(
    // Clock
    input  logic              clk_ref_p,
    input  logic              clk_ref_n,

    // SPI slave (from ESP32)
    input  logic              spi_sck,
    input  logic              spi_mosi,
    output logic              spi_miso,
    input  logic              spi_csn,

    // IRQ + LEDs + fan
    output logic              share_irq,
    output logic              led_share,
    output logic              led_busy,
    input  logic              fan_tach,
    output logic              fan_pwm
);

    // -----------------------------------------------------------------------
    // Reference clock buffer (LVDS in)
    // -----------------------------------------------------------------------
    logic clk_ref;

`ifndef SIM
    IBUFGDS #(
        .DIFF_TERM    ("TRUE"),
        .IBUF_LOW_PWR ("FALSE"),
        .IOSTANDARD   ("LVDS")
    ) u_ibufds_clk_ref (
        .O  (clk_ref),
        .I  (clk_ref_p),
        .IB (clk_ref_n)
    );
`else
    assign clk_ref = clk_ref_p;
`endif

    // -----------------------------------------------------------------------
    // MMCM: 200 MHz -> 250 MHz (mine), 100 MHz (sys)
    // -----------------------------------------------------------------------
    logic clk_mine, clk_sys;
    logic clk_mine_bufg, clk_sys_bufg;
    logic mmcm_locked;
    logic mmcm_feedback;

`ifndef SIM
    MMCME4_ADV #(
        .BANDWIDTH         ("OPTIMIZED"),
        .CLKIN1_PERIOD     (5.000),     // 200 MHz
        .DIVCLK_DIVIDE     (1),
        .CLKFBOUT_MULT_F   (5.000),     // VCO = 200 * 5 / 1 = 1000 MHz
        .CLKOUT0_DIVIDE_F  (4.000),     // 1000 / 4 = 250 MHz (clk_mine)
        .CLKOUT1_DIVIDE    (10),        // 1000 / 10 = 100 MHz (clk_sys)
        .CLKOUT0_PHASE     (0.000),
        .CLKOUT1_PHASE     (0.000),
        .STARTUP_WAIT      ("FALSE")
    ) u_mmcm (
        .CLKIN1     (clk_ref),
        .CLKIN2     (1'b0),
        .CLKINSEL   (1'b1),
        .CLKFBIN    (mmcm_feedback),
        .CLKFBOUT   (mmcm_feedback),
        .CLKOUT0    (clk_mine),
        .CLKOUT0B   (),
        .CLKOUT1    (clk_sys),
        .CLKOUT1B   (),
        .CLKOUT2    (), .CLKOUT2B(),
        .CLKOUT3    (), .CLKOUT3B(),
        .CLKOUT4    (), .CLKOUT5(), .CLKOUT6(),
        .LOCKED     (mmcm_locked),
        .PWRDWN     (1'b0),
        .RST        (1'b0),
        .CDDCREQ    (1'b0),  .CDDCDONE(),
        .DCLK       (1'b0),  .DEN(1'b0), .DWE(1'b0),
        .DADDR      (7'h0),  .DI(16'h0),
        .DO         (), .DRDY(),
        .PSCLK      (1'b0), .PSEN(1'b0), .PSINCDEC(1'b0), .PSDONE()
    );

    BUFG u_bufg_mine (.I(clk_mine), .O(clk_mine_bufg));
    BUFG u_bufg_sys  (.I(clk_sys),  .O(clk_sys_bufg));
`else
    // Sim stubs: use clk_ref as both mine and sys
    assign clk_mine_bufg = clk_ref;
    assign clk_sys_bufg  = clk_ref;
    assign mmcm_locked   = 1'b1;
`endif

    // -----------------------------------------------------------------------
    // Reset synchronisers (one per domain)
    //
    // The SPI slave runs on clk_sys (oversampled SPI inputs), so we no
    // longer need a separate spi_sck-clocked reset_sync.  Two domains
    // total: clk_sys (control + SPI) and clk_mine (data path).
    // -----------------------------------------------------------------------
    wire rst_n_async;
    assign rst_n_async = mmcm_locked;
    logic sys_rst_n, mine_rst_n;

    reset_sync u_reset_sync_sys  (.clk(clk_sys_bufg ), .arst_n(rst_n_async), .rst_n(sys_rst_n ));
    reset_sync u_reset_sync_mine (.clk(clk_mine_bufg), .arst_n(rst_n_async), .rst_n(mine_rst_n));

    // -----------------------------------------------------------------------
    // SPI slave (now clk_sys-clocked, oversamples async SPI pins)
    // -----------------------------------------------------------------------
    logic              spi_req_valid;
    logic              spi_req_write;
    logic [6:0]        spi_req_addr;
    logic [31:0]       spi_req_wdata;
    logic [31:0]       spi_req_rdata;

    spi_slave u_spi_slave (
        .clk_sys      (clk_sys_bufg),
        .rst_n        (sys_rst_n),
        .spi_sck      (spi_sck),
        .spi_mosi     (spi_mosi),
        .spi_csn      (spi_csn),
        .spi_miso     (spi_miso),
        .req_valid    (spi_req_valid),
        .req_write    (spi_req_write),
        .req_addr     (spi_req_addr),
        .req_wdata    (spi_req_wdata),
        .req_rdata    (spi_req_rdata)
    );

    // -----------------------------------------------------------------------
    // Regfile + pow_top (sys domain)
    // -----------------------------------------------------------------------
    logic              ctrl_start_pulse;
    logic              ctrl_abort_pulse;
    logic              ctrl_scratch_init_pulse;
    logic [31:0]       irq_mask, job_epoch, nonce_start, nonce_end;
    logic [255:0]      seed, prev_hash;

    logic              status_busy, status_share, status_scratch_ready;
    logic [31:0]       latched_nonce_lo, latched_nonce_hi, latched_ntime;
    logic [31:0]       latched_hash_count;
    logic [255:0]      latched_pow_hash;
    logic [31:0]       temp_raw;

    regfile u_regfile (
        .clk_sys            (clk_sys_bufg),
        .rst_n              (sys_rst_n),
        .spi_req_valid      (spi_req_valid),
        .spi_req_write      (spi_req_write),
        .spi_req_addr       (spi_req_addr),
        .spi_req_wdata      (spi_req_wdata),
        .spi_req_rdata      (spi_req_rdata),
        .ctrl_start_pulse   (ctrl_start_pulse),
        .ctrl_abort_pulse   (ctrl_abort_pulse),
        .ctrl_scratch_init_pulse(ctrl_scratch_init_pulse),
        .irq_mask           (irq_mask),
        .job_epoch          (job_epoch),
        .nonce_start        (nonce_start),
        .nonce_end           (nonce_end),
        .seed               (seed),
        .prev_hash          (prev_hash),
        .status_busy        (status_busy),
        .status_share       (status_share),
        .status_scratch_ready(status_scratch_ready),
        .latched_nonce_lo   (latched_nonce_lo),
        .latched_nonce_hi   (latched_nonce_hi),
        .latched_ntime      (latched_ntime),
        .latched_hash_count (latched_hash_count),
        .latched_pow_hash   (latched_pow_hash),
        .temp_raw           (temp_raw),
        .share_irq          (share_irq)
    );

    // -----------------------------------------------------------------------
    // Scratchpad + pow_top
    // -----------------------------------------------------------------------
    logic              ra_en   [0:LANES-1];
    logic [ADDR_BITS-1:0] ra_addr [0:LANES-1];
    logic [511:0]      ra_data [0:LANES-1];
    logic              wb_en   [0:LANES-1];
    logic [ADDR_BITS-1:0] wb_addr [0:LANES-1];
    logic [511:0]      wb_data [0:LANES-1];

    scratchpad_mem u_scratchpad (
        .clk     (clk_mine_bufg),
        .rst_n   (mine_rst_n),
        .ra_en   (ra_en),
        .ra_addr (ra_addr),
        .ra_data (ra_data),
        .wb_en   (wb_en),
        .wb_addr (wb_addr),
        .wb_data (wb_data)
    );

    pow_top u_pow_top (
        .clk                    (clk_mine_bufg),
        .rst_n                  (mine_rst_n),
        .ctrl_start_pulse       (ctrl_start_pulse),
        .ctrl_abort_pulse       (ctrl_abort_pulse),
        .ctrl_scratch_init_pulse(ctrl_scratch_init_pulse),
        .nonce_start            (nonce_start),
        .nonce_end              (nonce_end),
        .seed                   (seed),
        .prev_hash              (prev_hash),
        .status_busy            (status_busy),
        .status_share           (status_share),
        .status_scratch_ready   (status_scratch_ready),
        .latched_nonce_lo       (latched_nonce_lo),
        .latched_nonce_hi       (latched_nonce_hi),
        .latched_ntime          (latched_ntime),
        .latched_hash_count     (latched_hash_count),
        .latched_pow_hash       (latched_pow_hash),
        .ra_en                  (ra_en),
        .ra_addr                (ra_addr),
        .ra_data                (ra_data),
        .wb_en                  (wb_en),
        .wb_addr                (wb_addr),
        .wb_data                (wb_data)
    );

    // -----------------------------------------------------------------------
    // XADC
    // -----------------------------------------------------------------------
    xadc_monitor u_xadc (
        .clk      (clk_sys_bufg),
        .rst_n    (sys_rst_n),
        .temp_raw (temp_raw)
    );

    // -----------------------------------------------------------------------
    // LEDs + fan (cosmetic)
    // -----------------------------------------------------------------------
    assign led_busy  = status_busy;
    assign led_share = status_share;

    // Trivial 50% PWM at ~25 kHz (full speed for v1; firmware can take
    // over fan control later by adding a REG_FAN_PWM register).
    logic [10:0] pwm_cnt;
    always_ff @(posedge clk_sys_bufg or negedge sys_rst_n) begin
        if (!sys_rst_n) pwm_cnt <= 11'h0;
        else            pwm_cnt <= pwm_cnt + 11'h1;
    end
    assign fan_pwm = pwm_cnt[10];

    // fan_tach is currently unused (could feed back via xadc or a counter
    // for RPM reporting in a future register).
    wire _unused_fan_tach = fan_tach;

endmodule : b3miner_top

// ============================================================================
// reset_sync -- 2-FF async-assert / sync-deassert reset bridge.
//
// The init value `2'b00` is honoured by Vivado (INIT attribute) and by
// simulation (initial value), so we always come out of POR with a clean
// reset whether or not `arst_n` ever sees a falling edge.
// ============================================================================
module reset_sync (
    input  logic clk,
    input  logic arst_n,    // async reset, active low
    output logic rst_n
);
    logic [1:0] sr = 2'b00;
    always_ff @(posedge clk or negedge arst_n) begin
        if (!arst_n) sr <= 2'b00;
        else         sr <= {sr[0], 1'b1};
    end
    assign rst_n = sr[1];
endmodule
