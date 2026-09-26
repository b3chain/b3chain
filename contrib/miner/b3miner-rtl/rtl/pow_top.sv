// ============================================================================
// pow_top.sv -- top-level mining FSM.
//
// Coordinates scratch_init.sv, mixing_core.sv, scratchpad_mem.sv and
// target_compare.sv, driven by control pulses from regfile.sv.
//
// Two long-running operations:
//
//   1) Scratchpad init (~1.5 ms, once per `prev_block_hash`).
//      Triggered by regfile.ctrl_scratch_init_pulse.
//      Sets STATUS.scratch_ready when done.
//
//   2) Mining sweep (one nonce ≈ 33 µs).
//      Triggered by regfile.ctrl_start_job_pulse with valid nonce_start /
//      nonce_end.  Iterates nonces, calls mixing_core, compares the
//      output against an INTERNAL share threshold (top 16 bits == 0;
//      ≈ 1 share / 65536 nonces), and latches the first share for the
//      firmware to read.  Continues to next nonce after share latched
//      so the firmware can pipeline reads while we keep mining.
//
// All paths obey ctrl_abort_pulse: aborts return to S_IDLE with no
// further side effects on this job (the next start_job re-runs init_lanes).
// ============================================================================

`include "params_pkg.sv"

module pow_top
    import params_pkg::*;
(
    input  logic              clk,
    input  logic              rst_n,

    // ---- From regfile (sys domain) ----
    input  logic              ctrl_start_pulse,
    input  logic              ctrl_abort_pulse,
    input  logic              ctrl_scratch_init_pulse,
    input  logic              ctrl_share_ack_pulse,
    input  logic [31:0]       nonce_start,
    input  logic [31:0]       nonce_end,
    input  logic [31:0]       nonce_count,
    input  logic [255:0]      prev_hash,
    input  logic [255:0]      share_target,
    input  logic [607:0]      header_prefix,

    // ---- To regfile (status + latched share) ----
    output logic              status_busy,
    output logic              status_share,
    output logic              status_scratch_ready,
    output logic [31:0]       latched_nonce_lo,
    output logic [31:0]       latched_nonce_hi,
    output logic [31:0]       latched_ntime,        // unused for now
    output logic [31:0]       latched_hash_count,
    output logic [255:0]      latched_pow_hash,

    // ---- Scratchpad (shared by scratch_init + mixing_core) ----
    output logic              ra_en       [0:LANES-1],
    output logic [ADDR_BITS-1:0] ra_addr  [0:LANES-1],
    input  logic [511:0]      ra_data     [0:LANES-1],
    output logic              wb_en       [0:LANES-1],
    output logic [ADDR_BITS-1:0] wb_addr  [0:LANES-1],
    output logic [511:0]      wb_data     [0:LANES-1],
    output logic              init_write,
    output logic              copy_en,
    output logic [ADDR_BITS-1:0] copy_addr
);

    // -----------------------------------------------------------------------
    // FSM states
    // -----------------------------------------------------------------------
    typedef enum logic [3:0] {
        S_IDLE,
        S_SCRATCH_INIT,
        S_MINE_START,
        S_COPY,
        S_SEED_WAIT,
        S_MINE_WAIT,
        S_MINE_CHECK,
        S_MINE_NEXT,
        S_MINE_DONE,
        S_ABORT_WAIT
    } state_e;

    state_e state;

    // Current nonce within the sweep
    logic [31:0] cur_nonce;
    logic [31:0] hash_count;
    logic [ADDR_BITS-1:0] copy_idx;

    // -----------------------------------------------------------------------
    // scratch_init instance
    // -----------------------------------------------------------------------
    logic              si_start;
    logic              si_busy;
    logic              si_done;
    logic              si_wb_en   [0:LANES-1];
    logic [ADDR_BITS-1:0] si_wb_addr [0:LANES-1];
    logic [511:0]      si_wb_data [0:LANES-1];

    scratch_init u_scratch_init (
        .clk             (clk),
        .rst_n           (rst_n),
        .start           (si_start),
        .abort_i         (ctrl_abort_pulse),
        .prev_block_hash (prev_hash),
        .busy            (si_busy),
        .done            (si_done),
        .wb_en           (si_wb_en),
        .wb_addr         (si_wb_addr),
        .wb_data         (si_wb_data)
    );

    // -----------------------------------------------------------------------
    // mixing_core instance
    // -----------------------------------------------------------------------
    logic              mx_start;
    logic              mx_busy;
    logic              mx_done;
    logic [255:0]      mx_pow_hash;
    logic              mx_ra_en   [0:LANES-1];
    logic [ADDR_BITS-1:0] mx_ra_addr [0:LANES-1];
    logic              mx_wb_en   [0:LANES-1];
    logic [ADDR_BITS-1:0] mx_wb_addr [0:LANES-1];
    logic [511:0]      mx_wb_data [0:LANES-1];
    logic              hs_start, hs_busy, hs_done;
    logic [255:0]      nonce_seed;

    header_seed u_header_seed (
        .clk(clk),
        .rst_n(rst_n),
        .start(hs_start),
        .abort_i(ctrl_abort_pulse),
        .header_prefix(header_prefix),
        .nonce(cur_nonce),
        .busy(hs_busy),
        .done(hs_done),
        .seed(nonce_seed)
    );

    mixing_core u_mixing (
        .clk      (clk),
        .rst_n    (rst_n),
        .start    (mx_start),
        .abort_i  (ctrl_abort_pulse),
        .seed     (nonce_seed),
        .nonce    (cur_nonce),
        .busy     (mx_busy),
        .done     (mx_done),
        .pow_hash (mx_pow_hash),
        .ra_en    (mx_ra_en),
        .ra_addr  (mx_ra_addr),
        .ra_data  (ra_data),
        .wb_en    (mx_wb_en),
        .wb_addr  (mx_wb_addr),
        .wb_data  (mx_wb_data)
    );

    // -----------------------------------------------------------------------
    // Scratchpad-port arbitration:
    //   Port B writes: scratch_init when busy, mixing_core otherwise.
    //   Port A reads : always mixing_core (init doesn't read).
    // -----------------------------------------------------------------------
    always_comb begin
        for (int L = 0; L < LANES; L++) begin
            ra_en[L]   = mx_ra_en[L];
            ra_addr[L] = mx_ra_addr[L];
            if (si_busy) begin
                wb_en[L]   = si_wb_en[L];
                wb_addr[L] = si_wb_addr[L];
                wb_data[L] = si_wb_data[L];
            end else begin
                wb_en[L]   = mx_wb_en[L];
                wb_addr[L] = mx_wb_addr[L];
                wb_data[L] = mx_wb_data[L];
            end
        end
    end
    assign init_write = si_busy;
    assign copy_en = state == S_COPY;
    assign copy_addr = copy_idx;

    // -----------------------------------------------------------------------
    // Programmable little-endian share target.
    // -----------------------------------------------------------------------
    logic share_passes;
    target_compare u_target_compare (
        .hash_le     (mx_pow_hash),
        .target_le   (share_target),
        .valid_share (share_passes)
    );

    // -----------------------------------------------------------------------
    // FSM body
    // -----------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state                <= S_IDLE;
            si_start             <= 1'b0;
            mx_start             <= 1'b0;
            hs_start             <= 1'b0;
            cur_nonce            <= 32'h0;
            hash_count           <= 32'h0;
            copy_idx             <= '0;
            status_busy          <= 1'b0;
            status_share         <= 1'b0;
            status_scratch_ready <= 1'b0;
            latched_nonce_lo     <= 32'h0;
            latched_nonce_hi     <= 32'h0;
            latched_ntime        <= 32'h0;
            latched_pow_hash     <= 256'h0;
        end else begin
            si_start <= 1'b0;
            mx_start <= 1'b0;
            hs_start <= 1'b0;

            // Global abort: drop to IDLE immediately.
            if (ctrl_abort_pulse) begin
                state        <= S_ABORT_WAIT;
                status_busy  <= 1'b1;
                status_share <= 1'b0;
            end else begin
                if (ctrl_share_ack_pulse)
                    status_share <= 1'b0;
                unique case (state)
                    S_IDLE: begin
                        status_busy <= 1'b0;
                        if (ctrl_scratch_init_pulse) begin
                            si_start             <= 1'b1;
                            state                <= S_SCRATCH_INIT;
                            status_scratch_ready <= 1'b0;
                            status_busy          <= 1'b1;
                        end else if (ctrl_start_pulse) begin
                            cur_nonce  <= nonce_start;
                            hash_count <= 32'h0;
                            state      <= S_MINE_START;
                            status_busy<= 1'b1;
                            status_share <= 1'b0;
                        end
                    end

                    S_SCRATCH_INIT: if (si_done) begin
                        status_scratch_ready <= 1'b1;
                        status_busy          <= 1'b0;
                        state                <= S_IDLE;
                    end

                    S_MINE_START: begin
                        if (hash_count >= nonce_count) begin
                            state <= S_MINE_DONE;
                        end else begin
                            copy_idx <= '0;
                            state    <= S_COPY;
                        end
                    end

                    S_COPY: begin
                        if (copy_idx == LANE_BLOCKS - 1) begin
                            hs_start <= 1'b1;
                            state <= S_SEED_WAIT;
                        end else begin
                            copy_idx <= copy_idx + 1'b1;
                        end
                    end

                    S_SEED_WAIT: if (hs_done) begin
                        mx_start <= 1'b1;
                        state <= S_MINE_WAIT;
                    end

                    S_MINE_WAIT: if (mx_done) begin
                        hash_count <= hash_count + 32'd1;
                        state      <= S_MINE_CHECK;
                    end

                    S_MINE_CHECK: begin
                        if (share_passes) begin
                            if (!status_share) begin
                                latched_nonce_lo  <= cur_nonce;
                                latched_nonce_hi  <= 32'h0;
                                latched_ntime     <= 32'h0;
                                latched_pow_hash  <= mx_pow_hash;
                                status_share      <= 1'b1;
                                state <= S_MINE_NEXT;
                            end
                            // Hold this candidate until the previous share is
                            // acknowledged; never discard a passing nonce.
                        end else begin
                            state <= S_MINE_NEXT;
                        end
                    end

                    S_MINE_NEXT: begin
                        cur_nonce <= cur_nonce + 32'd1;
                        state     <= S_MINE_START;
                    end

                    S_MINE_DONE: begin
                        status_busy <= 1'b0;
                        state       <= S_IDLE;
                    end

                    S_ABORT_WAIT: begin
                        if (!si_busy && !mx_busy && !hs_busy) begin
                            status_busy <= 1'b0;
                            state <= S_IDLE;
                        end
                    end

                    default: state <= S_IDLE;
                endcase
            end
        end
    end

    assign latched_hash_count = hash_count;
    wire _unused_hs_busy = hs_busy;
    wire _unused_nonce_end = ^nonce_end;

endmodule : pow_top
