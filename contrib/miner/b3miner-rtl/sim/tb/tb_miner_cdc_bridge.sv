`timescale 1ns/1ps

module tb_miner_cdc_bridge;
    logic clk_sys = 0, clk_mine = 0;
    logic sys_rst_n = 0, mine_rst_n = 0;
    always #5 clk_sys = ~clk_sys;
    always #2 clk_mine = ~clk_mine;

    logic sys_start, sys_abort, sys_scratch, sys_ack;
    logic [31:0] sys_start_nonce, sys_end_nonce, sys_nonce_count;
    logic [255:0] sys_prev, sys_target;
    logic [607:0] sys_header;
    logic mine_start, mine_abort, mine_scratch, mine_ack;
    logic [31:0] mine_start_nonce, mine_end_nonce, mine_nonce_count;
    logic [255:0] mine_prev, mine_target;
    logic [607:0] mine_header;
    logic mine_busy, mine_share, mine_scratch_ready;
    logic [31:0] mine_nonce_lo, mine_nonce_hi, mine_ntime, mine_hash_count;
    logic [255:0] mine_hash;
    logic sys_busy, sys_share, sys_scratch_ready;
    logic [31:0] sys_nonce_lo, sys_nonce_hi, sys_ntime, sys_hash_count;
    logic [255:0] sys_hash;

    miner_cdc_bridge u_dut (
        .clk_sys(clk_sys), .sys_rst_n(sys_rst_n),
        .clk_mine(clk_mine), .mine_rst_n(mine_rst_n),
        .sys_start_pulse(sys_start), .sys_abort_pulse(sys_abort),
        .sys_scratch_init_pulse(sys_scratch), .sys_share_ack_pulse(sys_ack),
        .sys_nonce_start(sys_start_nonce), .sys_nonce_end(sys_end_nonce),
        .sys_nonce_count(sys_nonce_count),
        .sys_prev_hash(sys_prev),
        .sys_share_target(sys_target),
        .sys_header_prefix(sys_header),
        .mine_start_pulse(mine_start), .mine_abort_pulse(mine_abort),
        .mine_scratch_init_pulse(mine_scratch),
        .mine_share_ack_pulse(mine_ack),
        .mine_nonce_start(mine_start_nonce), .mine_nonce_end(mine_end_nonce),
        .mine_nonce_count(mine_nonce_count),
        .mine_prev_hash(mine_prev),
        .mine_share_target(mine_target),
        .mine_header_prefix(mine_header),
        .mine_status_busy(mine_busy), .mine_status_share(mine_share),
        .mine_status_scratch_ready(mine_scratch_ready),
        .mine_nonce_lo(mine_nonce_lo), .mine_nonce_hi(mine_nonce_hi),
        .mine_ntime(mine_ntime), .mine_hash_count(mine_hash_count),
        .mine_pow_hash(mine_hash),
        .sys_status_busy(sys_busy), .sys_status_share(sys_share),
        .sys_status_scratch_ready(sys_scratch_ready),
        .sys_nonce_lo(sys_nonce_lo), .sys_nonce_hi(sys_nonce_hi),
        .sys_ntime(sys_ntime), .sys_hash_count(sys_hash_count),
        .sys_pow_hash(sys_hash)
    );

    initial begin
        sys_start = 0; sys_abort = 0; sys_scratch = 0; sys_ack = 0;
        sys_start_nonce = 32'h1122_3344;
        sys_end_nonce = 32'h5566_7788;
        sys_nonce_count = 32'h1020_3040;
        sys_prev = 256'h5678;
        sys_target = 256'h9ABC;
        sys_header = 608'hDEF0;
        mine_busy = 0; mine_share = 0; mine_scratch_ready = 0;
        mine_nonce_lo = 0; mine_nonce_hi = 0; mine_ntime = 0;
        mine_hash_count = 0; mine_hash = 0;

        #30;
        sys_rst_n = 1;
        mine_rst_n = 1;
        repeat (3) @(posedge clk_sys);

        sys_scratch = 1;
        @(posedge clk_sys);
        sys_scratch = 0;
        wait (mine_scratch);
        if (mine_prev !== sys_prev || mine_target !== sys_target ||
            mine_nonce_count !== sys_nonce_count ||
            mine_header !== sys_header)
            $fatal(1, "command mailbox payload mismatch");
        @(posedge clk_mine);
        @(negedge clk_mine);
        if (mine_scratch) $fatal(1, "scratch command wider than one mine cycle");
        $display("cdc command PASS");

        mine_busy = 1;
        mine_scratch_ready = 1;
        wait (sys_busy && sys_scratch_ready);
        $display("cdc level status PASS");

        mine_hash_count = 32'd9;
        repeat (4) @(posedge clk_sys);
        if (sys_hash_count != 9) $fatal(1, "gray counter crossing mismatch");
        $display("cdc hash counter PASS");

        mine_nonce_lo = 32'hAABB_CCDD;
        mine_nonce_hi = 0;
        mine_ntime = 32'h6677_8899;
        mine_hash = 256'hDEAD_BEEF;
        mine_share = 1;
        wait (sys_share);
        $display("cdc share arrived");
        if (sys_nonce_lo !== mine_nonce_lo || sys_ntime !== mine_ntime ||
            sys_hash !== mine_hash)
            $fatal(1, "share mailbox payload mismatch");

        @(negedge clk_sys);
        sys_ack = 1;
        @(negedge clk_sys);
        sys_ack = 0;
        wait (mine_ack);
        $display("cdc ack reached mine");
        mine_share = 0;
        wait (!sys_share);

        $display("tb_miner_cdc_bridge: PASS");
        $finish;
    end

    initial begin
        #100us;
        $fatal(1, "tb_miner_cdc_bridge watchdog");
    end
endmodule
