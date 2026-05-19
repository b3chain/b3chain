// ============================================================================
// tb_blake3_compress.sv -- run vectors/blake3_compress.hex through the DUT
//                          and assert byte-for-byte parity with the
//                          Python reference.
// ============================================================================

`timescale 1ns/1ps
`include "vector_reader.svh"
`include "params_pkg.sv"

module tb_blake3_compress;
    import params_pkg::*;

    logic clk = 0;
    logic rst_n = 0;
    always #2 clk = ~clk;     // 250 MHz

    logic              start;
    logic [31:0]       cv_i        [0:7];
    logic [31:0]       block_i     [0:15];
    logic [63:0]       counter_i;
    logic [31:0]       block_len_i;
    logic [31:0]       flags_i;
    logic              busy;
    logic              done;
    logic [31:0]       out_state   [0:15];

    blake3_compress u_dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (start),
        .cv_i        (cv_i),
        .block_i     (block_i),
        .counter_i   (counter_i),
        .block_len_i (block_len_i),
        .flags_i     (flags_i),
        .busy        (busy),
        .done        (done),
        .out_state   (out_state)
    );

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------
    function automatic logic [31:0] le_word(input byte unsigned b[1024], input int off);
        return {b[off+3], b[off+2], b[off+1], b[off]};
    endfunction

    function automatic logic [63:0] le_qword(input byte unsigned b[1024], input int off);
        return {b[off+7], b[off+6], b[off+5], b[off+4],
                b[off+3], b[off+2], b[off+1], b[off]};
    endfunction

    int fd, n_pass, n_fail, n_total;
    vector_record_t rec;
    logic [31:0] expected [0:15];

    initial begin
        start = 0;
        n_pass = 0; n_fail = 0; n_total = 0;
        repeat (4) @(posedge clk);
        rst_n = 1;
        repeat (4) @(posedge clk);

        fd = vr_open("blake3_compress.hex");
        while (vr_read(fd, rec)) begin
            n_total++;
            // Field layout (matches gen_vectors.py::gen_blake3_compress):
            //   0: cv (32 bytes)
            //   1: block (64 bytes)
            //   2: counter (8 bytes)
            //   3: block_len (4 bytes)
            //   4: flags (4 bytes)
            //   5: expected out (64 bytes)
            for (int i = 0; i < 8;  i++) cv_i[i]    = le_word(rec.fields[0], 4*i);
            for (int i = 0; i < 16; i++) block_i[i] = le_word(rec.fields[1], 4*i);
            counter_i   = le_qword(rec.fields[2], 0);
            block_len_i = le_word (rec.fields[3], 0);
            flags_i     = le_word (rec.fields[4], 0);
            for (int i = 0; i < 16; i++) expected[i] = le_word(rec.fields[5], 4*i);

            @(posedge clk);
            start = 1;
            @(posedge clk);
            start = 0;

            // Wait for `done` (max ~50 cycles).
            for (int t = 0; t < 50; t++) begin
                @(posedge clk);
                if (done) break;
            end
            @(posedge clk);  // out_state latched in S_DONE -> readable next cycle

            // Compare
            begin
                int ok;
                ok = 1;
                for (int i = 0; i < 16; i++) begin
                    if (out_state[i] !== expected[i]) begin
                        ok = 0;
                        $error("[%s] word %0d: dut=%08h expected=%08h",
                            rec.label, i, out_state[i], expected[i]);
                    end
                end
                if (ok) begin
                    $display("[PASS] %s", rec.label);
                    n_pass++;
                end else begin
                    n_fail++;
                end
            end
        end
        vr_close(fd);

        $display("tb_blake3_compress: %0d / %0d PASS", n_pass, n_total);
        if (n_fail != 0) $fatal(1, "tb_blake3_compress FAILED");
        $finish;
    end

    // Watchdog
    initial begin
        #10ms;
        $fatal(1, "tb_blake3_compress watchdog timeout");
    end
endmodule
