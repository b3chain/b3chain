// ============================================================================
// tb_spi_slave.sv -- exercise the SPI slave + a tiny live regfile stub.
//
// Coverage:
//   1. READ REG_ID (addr 0)                         -- baseline / smoke
//   2. WRITE addr 0x20 -> verify req_write+addr+wdata land in stub
//   3. READ addr 0x05 (returns sentinel 0xAA55AA55) -- non-zero addr read
//   4. WRITE addr 0x10 = 0xCAFEBABE, then READ same -- read-after-write
//   5. READ addr 0x05 again                         -- confirms #3 wasn't
//                                                       cached from a
//                                                       previous addr
//
// The pre-fix v1.0 design FAILED checks 3, 4, 5 because rdata_lat was
// captured from the previous transaction's address.  The current
// implementation drives rdata combinationally off the live cmd_addr, so
// all five checks pass.
// ============================================================================

`timescale 1ns/1ps
`include "params_pkg.sv"

module tb_spi_slave;
    import params_pkg::*;

    // 100 MHz clk_sys
    logic clk_sys = 0;
    always #5 clk_sys = ~clk_sys;

    logic rst_n    = 0;
    logic spi_sck  = 0;
    logic spi_mosi = 0;
    logic spi_csn  = 1;
    logic spi_miso;

    logic              req_valid;
    logic              req_write;
    logic [6:0]        req_addr;
    logic [31:0]       req_wdata;
    logic [31:0]       req_rdata;

    spi_slave u_dut (
        .clk_sys   (clk_sys),
        .rst_n     (rst_n),
        .spi_sck   (spi_sck),
        .spi_mosi  (spi_mosi),
        .spi_csn   (spi_csn),
        .spi_miso  (spi_miso),
        .req_valid (req_valid),
        .req_write (req_write),
        .req_addr  (req_addr),
        .req_wdata (req_wdata),
        .req_rdata (req_rdata)
    );

    // ------------------------------------------------------------------------
    // Mini regfile stub: combinational rdata mux + a single writable slot
    // at addr 0x10 (to test read-after-write).  Other readable addresses
    // return fixed sentinels we can recognise.
    // ------------------------------------------------------------------------
    logic [31:0] reg10_stored = 32'h0;
    always_ff @(posedge clk_sys) begin
        if (req_valid && req_write && req_addr == 7'h10)
            reg10_stored <= req_wdata;
    end

    always_comb begin
        unique case (req_addr)
            7'h00:   req_rdata = 32'hB3110001;     // REG_ID
            7'h05:   req_rdata = 32'hAA55AA55;     // sentinel
            7'h10:   req_rdata = reg10_stored;     // read-after-write slot
            7'h7F:   req_rdata = 32'h00112233;     // boundary
            default: req_rdata = 32'hDEADBEEF;
        endcase
    end

    // ------------------------------------------------------------------------
    // SPI bit-banger.  SCK period = 200 ns (5 MHz, comfortably <4x clk_sys
    // so every edge is captured by the 2-FF synchroniser).  In real
    // hardware we run 25 MHz SPI, but slowing it down here just keeps the
    // sim short while still exercising the oversampling logic.
    // ------------------------------------------------------------------------
    localparam int SCK_HALF = 100;   // ns

    task automatic spi_txn(input byte unsigned cmd, input [31:0] data,
                           output [31:0] miso_out);
        byte unsigned bits [0:39];
        miso_out = 32'h0;
        // Build 40 wire bits MSB-first.
        for (int b = 0; b < 8;  b++) bits[b] = cmd[7-b];
        for (int B = 0; B < 4; B++)
            for (int b = 0; b < 8; b++)
                bits[8 + 8*B + b] = data[8*B + (7-b)];

        spi_csn = 0;
        #(SCK_HALF);
        for (int i = 0; i < 40; i++) begin
            spi_mosi = bits[i];
            #(SCK_HALF);
            spi_sck = 1;
            #(SCK_HALF/2);
            if (i >= 8) begin
                int bit_in_byte = (i - 8) % 8;
                int byte_idx    = (i - 8) / 8;
                miso_out[8*byte_idx + (7 - bit_in_byte)] = spi_miso;
            end
            #(SCK_HALF/2);
            spi_sck = 0;
            #(SCK_HALF);
        end
        spi_csn = 1;
        #(SCK_HALF * 4);
    endtask

    int n_fail = 0;

    task automatic check_eq32(input string label,
                              input [31:0] got, input [31:0] exp);
        if (got !== exp) begin
            $error("[FAIL] %s: got 0x%08x  expected 0x%08x", label, got, exp);
            n_fail++;
        end else begin
            $display("[PASS] %s = 0x%08x", label, got);
        end
    endtask

    initial begin
        repeat (10) @(posedge clk_sys);
        rst_n = 1;
        repeat (10) @(posedge clk_sys);

        // ---- 1) READ REG_ID ----
        begin
            logic [31:0] r;
            spi_txn(8'h00, 32'h0, r);
            check_eq32("READ REG_ID", r, 32'hB3110001);
        end

        // ---- 2) WRITE addr 0x20 = 0xCAFEBABE ----
        begin
            logic [31:0] dummy;
            spi_txn(8'h80 | 8'h20, 32'hCAFEBABE, dummy);
            repeat (4) @(posedge clk_sys);
            // req_valid pulses once when the txn completes; sample state.
            // (req_addr / req_wdata stay valid until the next txn changes them.)
            if (!(req_write === 1'b1 && req_addr === 7'h20 && req_wdata === 32'hCAFEBABE)) begin
                $error("[FAIL] WR @0x20: req_write=%0d addr=0x%02x wdata=0x%08x",
                    req_write, req_addr, req_wdata);
                n_fail++;
            end else begin
                $display("[PASS] WR @0x20 decoded: addr=0x20 wdata=0xCAFEBABE");
            end
        end

        // ---- 3) READ addr 0x05 (sentinel 0xAA55AA55) ----
        //         This check would have FAILED the v1.0 design (would have
        //         returned the previous transaction's value instead).
        begin
            logic [31:0] r;
            spi_txn(8'h05, 32'h0, r);
            check_eq32("READ @0x05 sentinel", r, 32'hAA55AA55);
        end

        // ---- 4) WRITE addr 0x10 = 0x12345678, then READ same ----
        begin
            logic [31:0] dummy;
            logic [31:0] r;
            spi_txn(8'h80 | 8'h10, 32'h12345678, dummy);
            repeat (4) @(posedge clk_sys);
            spi_txn(8'h10, 32'h0, r);
            check_eq32("RAW @0x10 read-after-write", r, 32'h12345678);
        end

        // ---- 5) READ addr 0x05 again (still 0xAA55AA55) ----
        //         Confirms we always re-decode the new addr, not a stale
        //         latch from the prior 0x10 read.
        begin
            logic [31:0] r;
            spi_txn(8'h05, 32'h0, r);
            check_eq32("READ @0x05 after 0x10 RAW", r, 32'hAA55AA55);
        end

        // ---- 6) READ addr 0x7F (max addr, sentinel 0x00112233) ----
        begin
            logic [31:0] r;
            spi_txn(8'h7F, 32'h0, r);
            check_eq32("READ @0x7F boundary", r, 32'h00112233);
        end

        if (n_fail != 0) begin
            $error("tb_spi_slave: %0d FAIL", n_fail);
            $fatal(1, "tb_spi_slave FAILED");
        end
        $display("tb_spi_slave: all checks PASS");
        $finish;
    end

    initial begin
        #5ms;
        $fatal(1, "tb_spi_slave watchdog");
    end
endmodule
