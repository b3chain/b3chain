`timescale 1ns/1ps
`include "vector_reader.svh"

module tb_header_seed;
    logic clk = 0, rst_n = 0, start;
    logic [607:0] header_prefix;
    logic [31:0] nonce;
    logic busy, done;
    logic [255:0] seed;
    vector_record_t rec;
    int fd, tested;

    always #2 clk = ~clk;
    header_seed u_dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .abort_i(1'b0),
        .header_prefix(header_prefix), .nonce(nonce),
        .busy(busy), .done(done), .seed(seed)
    );

    initial begin
        start = 0;
        header_prefix = '0;
        nonce = 0;
        tested = 0;
        repeat (4) @(posedge clk);
        rst_n = 1;

        fd = vr_open("full_hash.hex");
        while (vr_read(fd, rec)) begin
            if (rec.label != "zero_header_zero_prev" && rec.label != "nonced")
                continue;
            for (int i = 0; i < 76; i++)
                header_prefix[8*i +: 8] = rec.fields[0][i];
            nonce = {rec.fields[0][79], rec.fields[0][78],
                     rec.fields[0][77], rec.fields[0][76]};
            @(negedge clk);
            start = 1;
            @(negedge clk);
            start = 0;
            wait (done);
            for (int i = 0; i < 32; i++) begin
                byte unsigned got;
                got = seed[8*i +: 8];
                if (got !== rec.fields[2][i])
                    $fatal(1, "%s seed byte %0d got=%02x expected=%02x",
                           rec.label, i, got, rec.fields[2][i]);
            end
            tested++;
            @(posedge clk);
        end
        vr_close(fd);
        if (tested != 2) $fatal(1, "expected two header-seed vectors");
        $display("tb_header_seed: %0d vectors PASS", tested);
        $finish;
    end

    initial begin
        #100us;
        $fatal(1, "tb_header_seed watchdog");
    end
endmodule
