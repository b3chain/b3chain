// ============================================================================
// blake3_compress.sv -- 7-round BLAKE3 compression function.
//
// Implements the same data-flow as the reference Python (see
// ../ref/b3pow_ref.py::blake3_compress_full) and the GPU miner kernel
// (../b3chain-gpuminer/kernels/blake3.cuh::compress).
//
// Architecture
//   - Iterative: one round per cycle.  7 cycles + 2 latency cycles
//     = 9 cycles per compress.  At 250 MHz this is ~28 M compress/s.
//   - Pipelinable to II=1 by replicating the round logic 7×; left as
//     a future micro-architecture choice (mixing_core.sv only needs
//     1/9 of the available BLAKE3 throughput).
//
// Interface
//   start         : pulse to begin a new compression
//   busy          : high while a compress is in flight
//   done          : 1-cycle pulse when `out_state` is valid
//   cv_i  [8]     : input chaining-value words
//   block_i [16]  : input message block words
//   counter_i     : 64-bit chunk counter
//   block_len_i   : message length in bytes (0..64)
//   flags_i       : BLAKE3 flag set
//   out_state[16] : full 16-word compress output (CV in [0..7], XOF in [8..15])
// ============================================================================

`include "params_pkg.sv"

module blake3_compress
    import params_pkg::*;
(
    input  logic              clk,
    input  logic              rst_n,

    input  logic              start,
    input  logic [31:0]       cv_i        [0:7],
    input  logic [31:0]       block_i     [0:15],
    input  logic [63:0]       counter_i,
    input  logic [31:0]       block_len_i,
    input  logic [31:0]       flags_i,

    output logic              busy,
    output logic              done,
    output logic [31:0]       out_state   [0:15]
);

    // ------------------------------------------------------------------------
    // State registers
    // ------------------------------------------------------------------------
    typedef enum logic [1:0] { S_IDLE, S_RUN, S_DONE } state_e;
    state_e                   state, state_n;
    logic [2:0]               round_idx;   // 0..6
    logic [31:0]              cv_lat        [0:7];
    logic [31:0]              s             [0:15];
    logic [31:0]              m             [0:15];

    // ------------------------------------------------------------------------
    // Round-function combinational logic
    // ------------------------------------------------------------------------
    function automatic logic [31:0] rotr32(input logic [31:0] x, input int n);
        return (x >> n) | (x << (32 - n));
    endfunction

    // Quarter-round mixer g().
    // Applies in-place to the 4 cells {sa, sb, sc, sd} of the state.
    task automatic g(ref logic [31:0] sa, ref logic [31:0] sb,
                     ref logic [31:0] sc, ref logic [31:0] sd,
                     input logic [31:0] mx, input logic [31:0] my);
        sa = sa + sb + mx;
        sd = rotr32(sd ^ sa, 16);
        sc = sc + sd;
        sb = rotr32(sb ^ sc, 12);
        sa = sa + sb + my;
        sd = rotr32(sd ^ sa, 8);
        sc = sc + sd;
        sb = rotr32(sb ^ sc, 7);
    endtask

    // One full BLAKE3 round = 4 column-g + 4 diagonal-g, then permute msg.
    task automatic do_round(ref logic [31:0] st [0:15],
                            ref logic [31:0] mm [0:15]);
        logic [31:0] new_mm [0:15];
        // columns
        g(st[ 0], st[ 4], st[ 8], st[12], mm[ 0], mm[ 1]);
        g(st[ 1], st[ 5], st[ 9], st[13], mm[ 2], mm[ 3]);
        g(st[ 2], st[ 6], st[10], st[14], mm[ 4], mm[ 5]);
        g(st[ 3], st[ 7], st[11], st[15], mm[ 6], mm[ 7]);
        // diagonals
        g(st[ 0], st[ 5], st[10], st[15], mm[ 8], mm[ 9]);
        g(st[ 1], st[ 6], st[11], st[12], mm[10], mm[11]);
        g(st[ 2], st[ 7], st[ 8], st[13], mm[12], mm[13]);
        g(st[ 3], st[ 4], st[ 9], st[14], mm[14], mm[15]);
        // permute message in-place for next round (no-op for the 7th round)
        for (int i = 0; i < 16; i++) new_mm[i] = mm[BLAKE3_PERM[i]];
        mm = new_mm;
    endtask

    // ------------------------------------------------------------------------
    // FSM
    // ------------------------------------------------------------------------
    always_comb begin
        state_n = state;
        unique case (state)
            S_IDLE: if (start) state_n = S_RUN;
            S_RUN:  if (round_idx == 3'd6) state_n = S_DONE;
            S_DONE: state_n = S_IDLE;
            default: state_n = S_IDLE;
        endcase
    end

    assign busy = (state != S_IDLE);
    assign done = (state == S_DONE);

    // ------------------------------------------------------------------------
    // Datapath
    // ------------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            round_idx <= 3'd0;
        end else begin
            state <= state_n;

            unique case (state)
                S_IDLE: if (start) begin
                    // Load initial state per BLAKE3 spec:
                    //   s[0..7]   = cv
                    //   s[8..11]  = IV[0..3]
                    //   s[12..13] = counter
                    //   s[14]     = block_len
                    //   s[15]     = flags
                    for (int i = 0; i < 8; i++) begin
                        s[i]      <= cv_i[i];
                        cv_lat[i] <= cv_i[i];
                    end
                    s[ 8] <= BLAKE3_IV[0];
                    s[ 9] <= BLAKE3_IV[1];
                    s[10] <= BLAKE3_IV[2];
                    s[11] <= BLAKE3_IV[3];
                    s[12] <= counter_i[31:0];
                    s[13] <= counter_i[63:32];
                    s[14] <= block_len_i;
                    s[15] <= flags_i;
                    for (int i = 0; i < 16; i++) m[i] <= block_i[i];
                    round_idx <= 3'd0;
                end

                S_RUN: begin
                    // Run one round per cycle.  do_round() mutates s and m
                    // via ref args; the assignment below latches the new
                    // values back into the registers.
                    logic [31:0] s_next [0:15];
                    logic [31:0] m_next [0:15];
                    for (int i = 0; i < 16; i++) begin
                        s_next[i] = s[i];
                        m_next[i] = m[i];
                    end
                    do_round(s_next, m_next);
                    for (int i = 0; i < 16; i++) begin
                        s[i] <= s_next[i];
                        m[i] <= m_next[i];
                    end
                    round_idx <= round_idx + 3'd1;
                end

                S_DONE: begin
                    // Finalise per BLAKE3 spec:
                    //   out[0..7]  = s[0..7] XOR s[8..15]
                    //   out[8..15] = s[8..15] XOR cv[0..7]
                    for (int i = 0; i < 8; i++) begin
                        out_state[i]     <= s[i]     ^ s[i + 8];
                        out_state[i + 8] <= s[i + 8] ^ cv_lat[i];
                    end
                end

                default: ;
            endcase
        end
    end

endmodule : blake3_compress
