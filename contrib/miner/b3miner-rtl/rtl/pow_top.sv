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
    input  logic [31:0]       nonce_start,
    input  logic [31:0]       nonce_end,
    input  logic [255:0]      seed,           // blake3(header)
    input  logic [255:0]      prev_hash,

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
    output logic [511:0]      wb_data     [0:LANES-1]
);

    // -----------------------------------------------------------------------
    // FSM states
    // -----------------------------------------------------------------------
    typedef enum logic [2:0] {
        S_IDLE,
        S_SCRATCH_INIT,
        S_MINE_START,
        S_MINE_WAIT,
        S_MINE_CHECK,
        S_MINE_NEXT,
        S_MINE_DONE
    } state_e;

    state_e state;

    // Current nonce within the sweep
    logic [31:0] cur_nonce;
    logic [31:0] hash_count;

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

    mixing_core u_mixing (
        .clk      (clk),
        .rst_n    (rst_n),
        .start    (mx_start),
        .seed     (seed),
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

    // -----------------------------------------------------------------------
    // Internal share-threshold check (top 16 bits of LE-encoded hash == 0
    // ≈ 1 share per 65536 nonces).  Future: make this programmable via a
    // new REG_SHARE_THRESHOLD register.
    // -----------------------------------------------------------------------
    wire share_passes = (mx_pow_hash[255:240] == 16'h0000);

    // -----------------------------------------------------------------------
    // FSM body
    // -----------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state                <= S_IDLE;
            si_start             <= 1'b0;
            mx_start             <= 1'b0;
            cur_nonce            <= 32'h0;
            hash_count           <= 32'h0;
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

            // Global abort: drop to IDLE immediately.
            if (ctrl_abort_pulse) begin
                state        <= S_IDLE;
                status_busy  <= 1'b0;
                status_share <= 1'b0;
            end else begin
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
                        if (cur_nonce >= nonce_end) begin
                            state <= S_MINE_DONE;
                        end else begin
                            mx_start <= 1'b1;
                            state    <= S_MINE_WAIT;
                        end
                    end

                    S_MINE_WAIT: if (mx_done) begin
                        hash_count <= hash_count + 32'd1;
                        state      <= S_MINE_CHECK;
                    end

                    S_MINE_CHECK: begin
                        if (share_passes && !status_share) begin
                            // Latch the share; firmware reads + acks via
                            // ctrl_abort.  We continue mining unless aborted.
                            latched_nonce_lo  <= cur_nonce;
                            latched_nonce_hi  <= 32'h0;       // sweep is u32
                            latched_ntime     <= 32'h0;       // host owns time
                            latched_pow_hash  <= mx_pow_hash;
                            status_share      <= 1'b1;
                        end
                        state <= S_MINE_NEXT;
                    end

                    S_MINE_NEXT: begin
                        cur_nonce <= cur_nonce + 32'd1;
                        state     <= S_MINE_START;
                    end

                    S_MINE_DONE: begin
                        status_busy <= 1'b0;
                        state       <= S_IDLE;
                    end

                    default: state <= S_IDLE;
                endcase
            end
        end
    end

    assign latched_hash_count = hash_count;

endmodule : pow_top
