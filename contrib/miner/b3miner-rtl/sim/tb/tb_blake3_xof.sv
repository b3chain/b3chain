// ============================================================================
// tb_blake3_xof.sv -- vectors/blake3_xof.hex -> DUT -> compare 64 B output.
//
// The vector file's records pack:
//   field[0]: input bytes (0..64 bytes, padded with 0 in the DUT)
//   field[1]: 4-byte LE out_len  (we drive the DUT for 64-byte output only;
//                                  records that ask for >64 are split into
//                                  multiple compress calls by the caller --
//                                  outside this TB's scope.)
//   field[2]: expected XOF output (out_len bytes)
// ============================================================================

`timescale 1ns/1ps
`include "vector_reader.svh"
`include "params_pkg.sv"

module tb_blake3_xof;
    import params_pkg::*;

    logic clk = 0;
    logic rst_n = 0;
    always #2 clk = ~clk;

    logic              start;
    logic [31:0]       input_words [0:15];
    logic [31:0]       input_len;
    logic [63:0]       counter_i;
    logic              busy;
    logic              done;
    logic [31:0]       out_words   [0:15];

    blake3_xof u_dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (start),
        .input_words (input_words),
        .input_len   (input_len),
        .counter_i   (counter_i),
        .busy        (busy),
        .done        (done),
        .out_words   (out_words)
    );

    function automatic logic [31:0] le_word(input byte unsigned b[1024], input int off);
        return {b[off+3], b[off+2], b[off+1], b[off]};
    endfunction

    int fd, n_pass, n_fail, n_total;
    vector_record_t rec;

    initial begin
        start = 0; counter_i = 0;
        n_pass = 0; n_fail = 0; n_total = 0;
        repeat (4) @(posedge clk);
        rst_n = 1;
        repeat (4) @(posedge clk);

        fd = vr_open("blake3_xof.hex");
        while (vr_read(fd, rec)) begin
            n_total++;

            int in_len_bytes = rec.field_lens[0];
            int out_len_bytes = le_word(rec.fields[1], 0);

            // Only verify 64-byte requests in this TB -- bigger ones need
            // multi-block driving handled by the caller of blake3_xof.
            if (out_len_bytes != 64) begin
                $display("[SKIP] %s (out_len=%0d not 64)", rec.label, out_len_bytes);
                continue;
            end

            // Pack input bytes -> 16 words LE, zero-pad rest.
            for (int i = 0; i < 16; i++) input_words[i] = '0;
            for (int i = 0; i < in_len_bytes; i++)
                input_words[i/4][8*(i%4) +: 8] = rec.fields[0][i];

            input_len = in_len_bytes;

            @(posedge clk);
            start = 1;
            @(posedge clk);
            start = 0;
            for (int t = 0; t < 50; t++) begin
                @(posedge clk);
                if (done) break;
            end
            @(posedge clk);

            // Compare 64 bytes vs field[2]
            begin
                int ok = 1;
                for (int b = 0; b < 64; b++) begin
                    byte unsigned dut_b;
                    dut_b = out_words[b/4][8*(b%4) +: 8];
                    if (dut_b !== rec.fields[2][b]) begin
                        ok = 0;
                        $error("[%s] byte %0d: dut=%02h expected=%02h",
                            rec.label, b, dut_b, rec.fields[2][b]);
                    end
                end
                if (ok) begin
                    $display("[PASS] %s", rec.label);
                    n_pass++;
                end else n_fail++;
            end
        end
        vr_close(fd);

        $display("tb_blake3_xof: %0d / %0d PASS (skipping out_len != 64)", n_pass, n_total);
        if (n_fail != 0) $fatal(1, "tb_blake3_xof FAILED");
        $finish;
    end

    initial begin
        #10ms;
        $fatal(1, "tb_blake3_xof watchdog timeout");
    end
endmodule
