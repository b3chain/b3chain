`include "params_pkg.sv"

// Board-independent miner integration.  Clock generation and I/O standards
// live in board wrappers; this module owns reset, SPI, CDC, mining and status.
module b3miner_core
    import params_pkg::*;
(
    input  logic clk_sys,
    input  logic clk_mine,
    input  logic arst_n,
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
    logic sys_rst_n, mine_rst_n;
    reset_sync u_reset_sync_sys  (.clk(clk_sys),  .arst_n(arst_n), .rst_n(sys_rst_n));
    reset_sync u_reset_sync_mine (.clk(clk_mine), .arst_n(arst_n), .rst_n(mine_rst_n));

    logic spi_req_valid, spi_req_write;
    logic [6:0] spi_req_addr;
    logic [31:0] spi_req_wdata, spi_req_rdata;
    spi_slave u_spi_slave (
        .clk_sys(clk_sys), .rst_n(sys_rst_n),
        .spi_sck(spi_sck), .spi_mosi(spi_mosi), .spi_csn(spi_csn),
        .spi_miso(spi_miso), .req_valid(spi_req_valid),
        .req_write(spi_req_write), .req_addr(spi_req_addr),
        .req_wdata(spi_req_wdata), .req_rdata(spi_req_rdata)
    );

    logic sys_start_pulse, sys_abort_pulse, sys_scratch_pulse, sys_share_ack_pulse;
    logic [31:0] irq_mask, job_epoch, sys_nonce_start, sys_nonce_end, sys_nonce_count;
    logic [255:0] sys_seed, sys_prev_hash, sys_share_target;
    logic [607:0] sys_header_prefix;
    logic sys_status_busy, sys_status_share, sys_status_scratch_ready;
    logic [31:0] sys_nonce_lo, sys_nonce_hi, sys_ntime, sys_hash_count;
    logic [255:0] sys_pow_hash;
    logic [31:0] temp_raw;

    regfile u_regfile (
        .clk_sys(clk_sys), .rst_n(sys_rst_n),
        .spi_req_valid(spi_req_valid), .spi_req_write(spi_req_write),
        .spi_req_addr(spi_req_addr), .spi_req_wdata(spi_req_wdata),
        .spi_req_rdata(spi_req_rdata),
        .ctrl_start_pulse(sys_start_pulse),
        .ctrl_abort_pulse(sys_abort_pulse),
        .ctrl_scratch_init_pulse(sys_scratch_pulse),
        .ctrl_share_ack_pulse(sys_share_ack_pulse),
        .irq_mask(irq_mask), .job_epoch(job_epoch),
        .nonce_start(sys_nonce_start), .nonce_end(sys_nonce_end),
        .nonce_count(sys_nonce_count),
        .seed(sys_seed), .prev_hash(sys_prev_hash),
        .share_target(sys_share_target),
        .header_prefix(sys_header_prefix),
        .status_busy(sys_status_busy), .status_share(sys_status_share),
        .status_scratch_ready(sys_status_scratch_ready),
        .latched_nonce_lo(sys_nonce_lo), .latched_nonce_hi(sys_nonce_hi),
        .latched_ntime(sys_ntime), .latched_hash_count(sys_hash_count),
        .latched_pow_hash(sys_pow_hash), .temp_raw(temp_raw),
        .share_irq(share_irq)
    );

    logic mine_start_pulse, mine_abort_pulse, mine_scratch_pulse, mine_share_ack_pulse;
    logic [31:0] mine_nonce_start, mine_nonce_end, mine_nonce_count;
    logic [255:0] mine_prev_hash, mine_share_target;
    logic [607:0] mine_header_prefix;
    logic mine_status_busy, mine_status_share, mine_status_scratch_ready;
    logic [31:0] mine_nonce_lo, mine_nonce_hi, mine_ntime, mine_hash_count;
    logic [255:0] mine_pow_hash;

    miner_cdc_bridge u_cdc (
        .clk_sys(clk_sys), .sys_rst_n(sys_rst_n),
        .clk_mine(clk_mine), .mine_rst_n(mine_rst_n),
        .sys_start_pulse(sys_start_pulse),
        .sys_abort_pulse(sys_abort_pulse),
        .sys_scratch_init_pulse(sys_scratch_pulse),
        .sys_share_ack_pulse(sys_share_ack_pulse),
        .sys_nonce_start(sys_nonce_start), .sys_nonce_end(sys_nonce_end),
        .sys_nonce_count(sys_nonce_count),
        .sys_prev_hash(sys_prev_hash),
        .sys_share_target(sys_share_target),
        .sys_header_prefix(sys_header_prefix),
        .mine_start_pulse(mine_start_pulse),
        .mine_abort_pulse(mine_abort_pulse),
        .mine_scratch_init_pulse(mine_scratch_pulse),
        .mine_share_ack_pulse(mine_share_ack_pulse),
        .mine_nonce_start(mine_nonce_start), .mine_nonce_end(mine_nonce_end),
        .mine_nonce_count(mine_nonce_count),
        .mine_prev_hash(mine_prev_hash),
        .mine_share_target(mine_share_target),
        .mine_header_prefix(mine_header_prefix),
        .mine_status_busy(mine_status_busy),
        .mine_status_share(mine_status_share),
        .mine_status_scratch_ready(mine_status_scratch_ready),
        .mine_nonce_lo(mine_nonce_lo), .mine_nonce_hi(mine_nonce_hi),
        .mine_ntime(mine_ntime), .mine_hash_count(mine_hash_count),
        .mine_pow_hash(mine_pow_hash),
        .sys_status_busy(sys_status_busy),
        .sys_status_share(sys_status_share),
        .sys_status_scratch_ready(sys_status_scratch_ready),
        .sys_nonce_lo(sys_nonce_lo), .sys_nonce_hi(sys_nonce_hi),
        .sys_ntime(sys_ntime), .sys_hash_count(sys_hash_count),
        .sys_pow_hash(sys_pow_hash)
    );

    logic ra_en [0:LANES-1];
    logic [ADDR_BITS-1:0] ra_addr [0:LANES-1];
    logic [511:0] ra_data [0:LANES-1];
    logic wb_en [0:LANES-1];
    logic [ADDR_BITS-1:0] wb_addr [0:LANES-1];
    logic [511:0] wb_data [0:LANES-1];
    logic init_write, copy_en;
    logic [ADDR_BITS-1:0] copy_addr;

    scratchpad_mem u_scratchpad (
        .clk(clk_mine), .rst_n(mine_rst_n),
        .ra_en(ra_en), .ra_addr(ra_addr), .ra_data(ra_data),
        .wb_en(wb_en), .wb_addr(wb_addr), .wb_data(wb_data),
        .init_write(init_write), .copy_en(copy_en), .copy_addr(copy_addr)
    );

    pow_top u_pow_top (
        .clk(clk_mine), .rst_n(mine_rst_n),
        .ctrl_start_pulse(mine_start_pulse),
        .ctrl_abort_pulse(mine_abort_pulse),
        .ctrl_scratch_init_pulse(mine_scratch_pulse),
        .ctrl_share_ack_pulse(mine_share_ack_pulse),
        .nonce_start(mine_nonce_start), .nonce_end(mine_nonce_end),
        .nonce_count(mine_nonce_count),
        .prev_hash(mine_prev_hash),
        .share_target(mine_share_target),
        .header_prefix(mine_header_prefix),
        .status_busy(mine_status_busy), .status_share(mine_status_share),
        .status_scratch_ready(mine_status_scratch_ready),
        .latched_nonce_lo(mine_nonce_lo), .latched_nonce_hi(mine_nonce_hi),
        .latched_ntime(mine_ntime), .latched_hash_count(mine_hash_count),
        .latched_pow_hash(mine_pow_hash),
        .ra_en(ra_en), .ra_addr(ra_addr), .ra_data(ra_data),
        .wb_en(wb_en), .wb_addr(wb_addr), .wb_data(wb_data),
        .init_write(init_write), .copy_en(copy_en), .copy_addr(copy_addr)
    );

    xadc_monitor u_xadc (.clk(clk_sys), .rst_n(sys_rst_n), .temp_raw(temp_raw));
    assign led_busy = sys_status_busy;
    assign led_share = sys_status_share;

    logic [10:0] pwm_cnt;
    always_ff @(posedge clk_sys or negedge sys_rst_n) begin
        if (!sys_rst_n) pwm_cnt <= '0;
        else pwm_cnt <= pwm_cnt + 1'b1;
    end
    assign fan_pwm = pwm_cnt[10];
    wire _unused_fan_tach = fan_tach;
    wire _unused_job_epoch = ^job_epoch;
    wire _unused_legacy_seed = ^sys_seed;
endmodule

module reset_sync (
    input  logic clk,
    input  logic arst_n,
    output logic rst_n
);
    (* ASYNC_REG = "TRUE" *) logic [1:0] sr = 2'b00;
    always_ff @(posedge clk or negedge arst_n) begin
        if (!arst_n) sr <= 2'b00;
        else sr <= {sr[0], 1'b1};
    end
    assign rst_n = sr[1];
endmodule
