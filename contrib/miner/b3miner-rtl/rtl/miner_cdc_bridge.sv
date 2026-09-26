// Safe command and result transfer between the 100 MHz control domain and
// the 250 MHz mining domain.  Multi-bit mailboxes remain stable until the
// destination acknowledges the associated toggle.
module miner_cdc_bridge (
    input  logic         clk_sys,
    input  logic         sys_rst_n,
    input  logic         clk_mine,
    input  logic         mine_rst_n,

    input  logic         sys_start_pulse,
    input  logic         sys_abort_pulse,
    input  logic         sys_scratch_init_pulse,
    input  logic         sys_share_ack_pulse,
    input  logic [31:0]  sys_nonce_start,
    input  logic [31:0]  sys_nonce_end,
    input  logic [31:0]  sys_nonce_count,
    input  logic [255:0] sys_prev_hash,
    input  logic [255:0] sys_share_target,
    input  logic [607:0] sys_header_prefix,

    output logic         mine_start_pulse,
    output logic         mine_abort_pulse,
    output logic         mine_scratch_init_pulse,
    output logic         mine_share_ack_pulse,
    output logic [31:0]  mine_nonce_start,
    output logic [31:0]  mine_nonce_end,
    output logic [31:0]  mine_nonce_count,
    output logic [255:0] mine_prev_hash,
    output logic [255:0] mine_share_target,
    output logic [607:0] mine_header_prefix,

    input  logic         mine_status_busy,
    input  logic         mine_status_share,
    input  logic         mine_status_scratch_ready,
    input  logic [31:0]  mine_nonce_lo,
    input  logic [31:0]  mine_nonce_hi,
    input  logic [31:0]  mine_ntime,
    input  logic [31:0]  mine_hash_count,
    input  logic [255:0] mine_pow_hash,

    output logic         sys_status_busy,
    output logic         sys_status_share,
    output logic         sys_status_scratch_ready,
    output logic [31:0]  sys_nonce_lo,
    output logic [31:0]  sys_nonce_hi,
    output logic [31:0]  sys_ntime,
    output logic [31:0]  sys_hash_count,
    output logic [255:0] sys_pow_hash
);
    localparam logic [1:0] CMD_START = 2'd0;
    localparam logic [1:0] CMD_ABORT = 2'd1;
    localparam logic [1:0] CMD_SCRATCH = 2'd2;

    logic [1:0] cmd_mailbox;
    logic [31:0] nonce_start_mailbox, nonce_end_mailbox, nonce_count_mailbox;
    logic [255:0] prev_hash_mailbox, target_mailbox;
    logic [607:0] header_mailbox;
    logic cmd_req_sys, cmd_pending_sys;
    logic cmd_ack_mine;
    (* ASYNC_REG = "TRUE" *) logic [1:0] cmd_ack_sync_sys;
    (* ASYNC_REG = "TRUE" *) logic [1:0] cmd_req_sync_mine;
    logic cmd_req_seen_mine;
    logic [1:0] cmd_mailbox_mine;
    logic cmd_dispatch_pending_mine;

    always_ff @(posedge clk_sys or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            cmd_req_sys       <= 1'b0;
            cmd_pending_sys   <= 1'b0;
            cmd_mailbox       <= CMD_START;
            nonce_start_mailbox <= '0;
            nonce_end_mailbox <= '0;
            nonce_count_mailbox <= '0;
            prev_hash_mailbox <= '0;
            target_mailbox    <= '0;
            header_mailbox    <= '0;
            cmd_ack_sync_sys  <= '0;
        end else begin
            cmd_ack_sync_sys <= {cmd_ack_sync_sys[0], cmd_ack_mine};
            if (cmd_pending_sys && cmd_ack_sync_sys[1] == cmd_req_sys)
                cmd_pending_sys <= 1'b0;

            if (!cmd_pending_sys &&
                (sys_start_pulse || sys_abort_pulse || sys_scratch_init_pulse)) begin
                if (sys_abort_pulse) cmd_mailbox <= CMD_ABORT;
                else if (sys_scratch_init_pulse) cmd_mailbox <= CMD_SCRATCH;
                else cmd_mailbox <= CMD_START;
                nonce_start_mailbox <= sys_nonce_start;
                nonce_end_mailbox <= sys_nonce_end;
                nonce_count_mailbox <= sys_nonce_count;
                prev_hash_mailbox <= sys_prev_hash;
                target_mailbox <= sys_share_target;
                header_mailbox <= sys_header_prefix;
                cmd_req_sys <= ~cmd_req_sys;
                cmd_pending_sys <= 1'b1;
            end
        end
    end

    always_ff @(posedge clk_mine or negedge mine_rst_n) begin
        if (!mine_rst_n) begin
            cmd_req_sync_mine <= '0;
            cmd_req_seen_mine <= 1'b0;
            cmd_ack_mine <= 1'b0;
            mine_start_pulse <= 1'b0;
            mine_abort_pulse <= 1'b0;
            mine_scratch_init_pulse <= 1'b0;
            mine_nonce_start <= '0;
            mine_nonce_end <= '0;
            mine_nonce_count <= '0;
            mine_prev_hash <= '0;
            mine_share_target <= '0;
            mine_header_prefix <= '0;
            cmd_mailbox_mine <= CMD_START;
            cmd_dispatch_pending_mine <= 1'b0;
        end else begin
            cmd_req_sync_mine <= {cmd_req_sync_mine[0], cmd_req_sys};
            mine_start_pulse <= 1'b0;
            mine_abort_pulse <= 1'b0;
            mine_scratch_init_pulse <= 1'b0;
            if (cmd_dispatch_pending_mine) begin
                case (cmd_mailbox_mine)
                    CMD_ABORT: mine_abort_pulse <= 1'b1;
                    CMD_SCRATCH: mine_scratch_init_pulse <= 1'b1;
                    default: mine_start_pulse <= 1'b1;
                endcase
                cmd_dispatch_pending_mine <= 1'b0;
            end
            if (cmd_req_sync_mine[1] != cmd_req_seen_mine) begin
                mine_nonce_start <= nonce_start_mailbox;
                mine_nonce_end <= nonce_end_mailbox;
                mine_nonce_count <= nonce_count_mailbox;
                mine_prev_hash <= prev_hash_mailbox;
                mine_share_target <= target_mailbox;
                mine_header_prefix <= header_mailbox;
                cmd_mailbox_mine <= cmd_mailbox;
                cmd_dispatch_pending_mine <= 1'b1;
                cmd_req_seen_mine <= cmd_req_sync_mine[1];
                cmd_ack_mine <= cmd_req_sync_mine[1];
            end
        end
    end

    // Level status synchronizers.
    (* ASYNC_REG = "TRUE" *) logic [1:0] busy_sync, scratch_sync;
    always_ff @(posedge clk_sys or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            busy_sync <= '0;
            scratch_sync <= '0;
        end else begin
            busy_sync <= {busy_sync[0], mine_status_busy};
            scratch_sync <= {scratch_sync[0], mine_status_scratch_ready};
        end
    end
    assign sys_status_busy = busy_sync[1];
    assign sys_status_scratch_ready = scratch_sync[1];

    // Gray-code the free-running hash counter before crossing domains.
    logic [31:0] hash_gray_mine;
    (* ASYNC_REG = "TRUE" *) logic [31:0] hash_gray_sync1, hash_gray_sync2;
    always_ff @(posedge clk_mine or negedge mine_rst_n) begin
        if (!mine_rst_n) hash_gray_mine <= '0;
        else hash_gray_mine <= mine_hash_count ^ (mine_hash_count >> 1);
    end
    always_ff @(posedge clk_sys or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            hash_gray_sync1 <= '0;
            hash_gray_sync2 <= '0;
        end else begin
            hash_gray_sync1 <= hash_gray_mine;
            hash_gray_sync2 <= hash_gray_sync1;
        end
    end
    function automatic logic [31:0] gray_to_binary(input logic [31:0] gray);
        logic [31:0] value;
        value[31] = gray[31];
        for (int i = 30; i >= 0; i--)
            value[i] = value[i + 1] ^ gray[i];
        return value;
    endfunction
    assign sys_hash_count = gray_to_binary(hash_gray_sync2);

    // One-entry asynchronous share FIFO.  The mining result is held in its
    // mailbox until firmware writes CTRL.share_ack.
    logic share_req_mine, share_pending_mine, share_seen_high_mine;
    logic share_ack_sys;
    logic [31:0] share_nonce_lo_mailbox, share_nonce_hi_mailbox, share_ntime_mailbox;
    logic [255:0] share_hash_mailbox;
    (* ASYNC_REG = "TRUE" *) logic [1:0] share_ack_sync_mine;
    (* ASYNC_REG = "TRUE" *) logic [1:0] share_req_sync_sys;
    logic share_req_seen_sys;

    always_ff @(posedge clk_mine or negedge mine_rst_n) begin
        if (!mine_rst_n) begin
            share_req_mine <= 1'b0;
            share_pending_mine <= 1'b0;
            share_seen_high_mine <= 1'b0;
            share_ack_sync_mine <= '0;
            mine_share_ack_pulse <= 1'b0;
            share_nonce_lo_mailbox <= '0;
            share_nonce_hi_mailbox <= '0;
            share_ntime_mailbox <= '0;
            share_hash_mailbox <= '0;
        end else begin
            share_ack_sync_mine <= {share_ack_sync_mine[0], share_ack_sys};
            mine_share_ack_pulse <= 1'b0;
            if (share_pending_mine && share_ack_sync_mine[1] == share_req_mine) begin
                share_pending_mine <= 1'b0;
                mine_share_ack_pulse <= 1'b1;
            end
            if (!mine_status_share)
                share_seen_high_mine <= 1'b0;
            if (mine_status_share && !share_pending_mine && !share_seen_high_mine) begin
                share_nonce_lo_mailbox <= mine_nonce_lo;
                share_nonce_hi_mailbox <= mine_nonce_hi;
                share_ntime_mailbox <= mine_ntime;
                share_hash_mailbox <= mine_pow_hash;
                share_req_mine <= ~share_req_mine;
                share_pending_mine <= 1'b1;
                share_seen_high_mine <= 1'b1;
            end
        end
    end

    always_ff @(posedge clk_sys or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            share_req_sync_sys <= '0;
            share_req_seen_sys <= 1'b0;
            share_ack_sys <= 1'b0;
            sys_status_share <= 1'b0;
            sys_nonce_lo <= '0;
            sys_nonce_hi <= '0;
            sys_ntime <= '0;
            sys_pow_hash <= '0;
        end else begin
            share_req_sync_sys <= {share_req_sync_sys[0], share_req_mine};
            if (share_req_sync_sys[1] != share_req_seen_sys && !sys_status_share) begin
                sys_nonce_lo <= share_nonce_lo_mailbox;
                sys_nonce_hi <= share_nonce_hi_mailbox;
                sys_ntime <= share_ntime_mailbox;
                sys_pow_hash <= share_hash_mailbox;
                sys_status_share <= 1'b1;
                share_req_seen_sys <= share_req_sync_sys[1];
            end
            if (sys_share_ack_pulse && sys_status_share) begin
                sys_status_share <= 1'b0;
                share_ack_sys <= share_req_sync_sys[1];
            end
        end
    end
endmodule
