// ============================================================================
// tb_scratch_init.sv -- run the scratchpad-init pipeline against
// vectors/scratch_init.hex and assert the first 4 blocks of pad match
// the Python reference for prev_block_hash = zero.
// ============================================================================

`timescale 1ns/1ps
`include "vector_reader.svh"
`include "params_pkg.sv"

module tb_scratch_init;
    import params_pkg::*;

    logic clk = 0;
    logic rst_n = 0;
    always #5 clk = ~clk;     // 100 MHz

    logic              start;
    logic [255:0]      prev_block_hash;
    logic              busy, done;
    logic              wb_en   [0:LANES-1];
    logic [ADDR_BITS-1:0] wb_addr [0:LANES-1];
    logic [511:0]      wb_data [0:LANES-1];

    scratch_init u_dut (
        .clk             (clk),
        .rst_n           (rst_n),
        .start           (start),
        .prev_block_hash (prev_block_hash),
        .busy            (busy),
        .done            (done),
        .wb_en           (wb_en),
        .wb_addr         (wb_addr),
        .wb_data         (wb_data)
    );

    // Mirror the writes locally so we can check against the vector.
    logic [511:0] capture [0:LANES-1][0:LANE_BLOCKS-1];
    always_ff @(posedge clk) begin
        for (int L = 0; L < LANES; L++)
            if (wb_en[L]) capture[L][wb_addr[L]] <= wb_data[L];
    end

    initial begin
        start = 0; prev_block_hash = 256'h0;
        repeat (5) @(posedge clk);
        rst_n = 1;
        repeat (5) @(posedge clk);

        // Use prev_block_hash = 0 to match the first vector record.
        prev_block_hash = 256'h0;
        @(posedge clk);
        start = 1;
        @(posedge clk);
        start = 0;

        // Wait for done (16384 blocks × ~10 cycles + some overhead).
        // Cap at 250k clk_sys cycles = 2.5 ms simulated.
        for (int t = 0; t < 250000; t++) begin
            @(posedge clk);
            if (done) break;
        end
        if (!done) $fatal(1, "tb_scratch_init: never finished");

        // Compare the first 4 blocks of lane 0 against vector record "zero".
        begin
            int fd; vector_record_t rec;
            byte unsigned expect_bytes [0:255];
            int found = 0;
            fd = vr_open("scratch_init.hex");
            while (vr_read(fd, rec)) begin
                if (rec.label == "zero") begin
                    // field[0] = prev_hash, field[1] = 256 bytes of first 4 blocks
                    for (int b = 0; b < 256; b++) expect_bytes[b] = rec.fields[1][b];
                    found = 1;
                    break;
                end
            end
            vr_close(fd);
            if (!found) $fatal(1, "tb_scratch_init: 'zero' record missing");

            // Check first 4 blocks (256 bytes) of lane 0.
            for (int blk = 0; blk < 4; blk++) begin
                for (int b = 0; b < 64; b++) begin
                    byte unsigned dut_b = capture[0][blk][8*b +: 8];
                    if (dut_b !== expect_bytes[blk*64 + b]) begin
                        $error("blk %0d byte %0d: dut=%02h exp=%02h",
                            blk, b, dut_b, expect_bytes[blk*64 + b]);
                        $fatal(1, "tb_scratch_init: byte mismatch");
                    end
                end
            end
        end
        $display("tb_scratch_init: first 4 blocks match vector PASS");
        $finish;
    end

    initial begin
        #100ms;
        $fatal(1, "tb_scratch_init watchdog (took too long)");
    end
endmodule
