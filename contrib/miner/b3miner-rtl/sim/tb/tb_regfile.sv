// ============================================================================
// tb_regfile.sv -- exercise the register file via simulated SPI requests
// and assert that CTRL pulses, status, seed/prev writes, and POW_HASH reads
// all behave per the b3_fpga_regs.h contract.
//
// After the rev-B fix the SPI<->regfile path is single-clock (clk_sys),
// so:
//   - writes: drive addr/wdata/write=1, pulse req_valid for one cycle.
//   - reads: drive addr/write=0 -- rdata is combinational, sample after
//     a couple cycles for safety.
// ============================================================================

`timescale 1ns/1ps
`include "params_pkg.sv"

module tb_regfile;
    import params_pkg::*;

    logic clk_sys = 0;
    logic rst_n   = 0;
    always #5 clk_sys = ~clk_sys;   // 100 MHz

    logic              spi_req_valid;
    logic              spi_req_write;
    logic [6:0]        spi_req_addr;
    logic [31:0]       spi_req_wdata;
    logic [31:0]       spi_req_rdata;
    logic              ctrl_start_pulse, ctrl_abort_pulse, ctrl_scratch_init_pulse;
    logic [31:0]       irq_mask, job_epoch, nonce_start, nonce_end;
    logic [255:0]      seed, prev_hash;
    logic              status_busy = 0;
    logic              status_share = 0;
    logic              status_scratch_ready = 0;
    logic [31:0]       latched_nonce_lo = 0;
    logic [31:0]       latched_nonce_hi = 0;
    logic [31:0]       latched_ntime = 0;
    logic [31:0]       latched_hash_count = 0;
    logic [255:0]      latched_pow_hash = 0;
    logic [31:0]       temp_raw = 32'h97CF;
    logic              share_irq;

    regfile u_dut (
        .clk_sys                 (clk_sys),
        .rst_n                   (rst_n),
        .spi_req_valid           (spi_req_valid),
        .spi_req_write           (spi_req_write),
        .spi_req_addr            (spi_req_addr),
        .spi_req_wdata           (spi_req_wdata),
        .spi_req_rdata           (spi_req_rdata),
        .ctrl_start_pulse        (ctrl_start_pulse),
        .ctrl_abort_pulse        (ctrl_abort_pulse),
        .ctrl_scratch_init_pulse (ctrl_scratch_init_pulse),
        .irq_mask                (irq_mask),
        .job_epoch               (job_epoch),
        .nonce_start             (nonce_start),
        .nonce_end               (nonce_end),
        .seed                    (seed),
        .prev_hash               (prev_hash),
        .status_busy             (status_busy),
        .status_share            (status_share),
        .status_scratch_ready    (status_scratch_ready),
        .latched_nonce_lo        (latched_nonce_lo),
        .latched_nonce_hi        (latched_nonce_hi),
        .latched_ntime           (latched_ntime),
        .latched_hash_count      (latched_hash_count),
        .latched_pow_hash        (latched_pow_hash),
        .temp_raw                (temp_raw),
        .share_irq               (share_irq)
    );

    // One-cycle write commit.
    task automatic do_write(input [6:0] addr, input [31:0] data);
        @(posedge clk_sys);
        spi_req_addr  <= addr;
        spi_req_wdata <= data;
        spi_req_write <= 1'b1;
        spi_req_valid <= 1'b1;
        @(posedge clk_sys);
        spi_req_valid <= 1'b0;
        spi_req_write <= 1'b0;
    endtask

    // Combinational read -- give a couple cycles for delta-cycle settling.
    task automatic do_read(input [6:0] addr, output [31:0] data);
        @(posedge clk_sys);
        spi_req_addr  <= addr;
        spi_req_write <= 1'b0;
        spi_req_valid <= 1'b0;
        repeat (2) @(posedge clk_sys);
        data = spi_req_rdata;
    endtask

    int n_fail = 0;

    initial begin
        spi_req_valid = 0;
        spi_req_write = 0;
        spi_req_addr  = 7'h0;
        spi_req_wdata = 32'h0;
        repeat (5) @(posedge clk_sys);
        rst_n = 1;
        repeat (5) @(posedge clk_sys);

        // ---- Read REG_ID ----
        begin
            logic [31:0] r;
            do_read(REG_ID, r);
            if (r !== REG_ID_MAGIC) begin
                $error("REG_ID read = 0x%08x (expected 0x%08x)", r, REG_ID_MAGIC);
                n_fail++;
            end else $display("[PASS] REG_ID = 0x%08x", r);
        end

        // ---- Write CTRL.start -> see ctrl_start_pulse ----
        do_write(REG_CTRL, 32'h1);
        if (!ctrl_start_pulse_seen) begin
            $error("ctrl_start_pulse did not fire");
            n_fail++;
        end else $display("[PASS] ctrl_start_pulse fired");

        // ---- Write SEED[0..7] then read back ----
        for (int i = 0; i < 8; i++) begin
            do_write(7'(REG_SEED_BASE + i), 32'hCAFE_0000 | i);
        end
        for (int i = 0; i < 8; i++) begin
            logic [31:0] r;
            do_read(7'(REG_SEED_BASE + i), r);
            if (r !== (32'hCAFE_0000 | i)) begin
                $error("SEED[%0d] readback = 0x%08x", i, r);
                n_fail++;
            end
        end
        $display("[PASS] SEED[0..7] write+read");

        // ---- temp_raw passthrough ----
        begin
            logic [31:0] r;
            do_read(REG_TEMP_RAW, r);
            if (r !== 32'h97CF) begin
                $error("TEMP_RAW = 0x%08x (expected 0x97CF)", r);
                n_fail++;
            end else $display("[PASS] TEMP_RAW = 0x%08x", r);
        end

        // ---- POW_HASH passthrough (latched_pow_hash drives the read mux) ----
        latched_pow_hash = 256'h0123456789ABCDEF_0123456789ABCDEF_0123456789ABCDEF_0123456789ABCDEF;
        for (int i = 0; i < 8; i++) begin
            logic [31:0] r;
            do_read(7'(REG_POW_HASH_BASE + i), r);
            if (r !== latched_pow_hash[32*i +: 32]) begin
                $error("POW_HASH[%0d] = 0x%08x  expected 0x%08x",
                    i, r, latched_pow_hash[32*i +: 32]);
                n_fail++;
            end
        end
        $display("[PASS] POW_HASH[0..7] readback");

        if (n_fail != 0) $fatal(1, "tb_regfile: %0d FAIL", n_fail);
        $display("tb_regfile: all checks PASS");
        $finish;
    end

    // Track ctrl_start_pulse on the cycle it asserts.
    logic ctrl_start_pulse_seen = 0;
    always @(posedge clk_sys)
        if (ctrl_start_pulse) ctrl_start_pulse_seen <= 1;

    initial begin
        #1ms;
        $fatal(1, "tb_regfile watchdog");
    end
endmodule
