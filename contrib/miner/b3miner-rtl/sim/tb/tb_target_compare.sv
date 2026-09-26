`timescale 1ns/1ps

module tb_target_compare;
    logic [255:0] hash_le, target_le;
    logic valid_share;

    target_compare u_dut (
        .hash_le(hash_le),
        .target_le(target_le),
        .valid_share(valid_share)
    );

    initial begin
        hash_le = 256'h0;
        target_le = 256'h0;
        #1;
        if (!valid_share) $fatal(1, "equal target must pass");

        hash_le = 256'h101;
        target_le = 256'h100;
        #1;
        if (valid_share) $fatal(1, "hash above target must fail");

        hash_le = 256'hFFFF;
        target_le = {16'h0000, {240{1'b1}}};
        #1;
        if (!valid_share) $fatal(1, "default 16-bit prefix target must pass");

        hash_le = {16'h0001, 240'h0};
        #1;
        if (valid_share) $fatal(1, "nonzero top prefix must fail default target");

        $display("tb_target_compare: PASS");
        $finish;
    end
endmodule
