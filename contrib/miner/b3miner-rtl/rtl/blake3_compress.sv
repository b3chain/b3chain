// ============================================================================
// blake3_compress.sv -- 7-round BLAKE3 compression function.
//
// Implements the same data-flow as the reference Python (see
// ../ref/b3pow_ref.py::blake3_compress_full) and the GPU miner kernel
// (../b3chain-gpuminer/kernels/blake3.cuh::compress).
//
// Architecture
//   - Each G function is split into four registered quarters.
//   - 8 phases/round × 7 rounds + load + done = 58 cycles/compress.
//   - The longer latency is amortized by the memory-hard mixing loop and
//     closes the 250 MHz KU5P timing target.
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
    logic [2:0]               phase_idx;   // 0..7 within one round
    logic [31:0]              cv_lat        [0:7];
    logic [31:0]              s             [0:15];
    logic [31:0]              m             [0:15];

    // ------------------------------------------------------------------------
    // Round-function combinational logic
    // ------------------------------------------------------------------------
    function automatic logic [31:0] rotr32(input logic [31:0] x, input int n);
        return (x >> n) | (x << (32 - n));
    endfunction

    function automatic void g_quarter(
        ref logic [31:0] sa, ref logic [31:0] sb,
        ref logic [31:0] sc, ref logic [31:0] sd,
        input logic [31:0] mx, input logic [31:0] my,
        input logic [1:0] quarter
    );
        case (quarter)
            2'd0: begin
                sa = sa + sb + mx;
                sd = rotr32(sd ^ sa, 16);
            end
            2'd1: begin
                sc = sc + sd;
                sb = rotr32(sb ^ sc, 12);
            end
            2'd2: begin
                sa = sa + sb + my;
                sd = rotr32(sd ^ sa, 8);
            end
            default: begin
                sc = sc + sd;
                sb = rotr32(sb ^ sc, 7);
            end
        endcase
    endfunction

    // ------------------------------------------------------------------------
    // FSM
    // ------------------------------------------------------------------------
    always_comb begin
        state_n = state;
        unique case (state)
            S_IDLE: if (start) state_n = S_RUN;
            S_RUN:  if (round_idx == 3'd6 && phase_idx == 3'd7) state_n = S_DONE;
            S_DONE: state_n = S_IDLE;
            default: state_n = S_IDLE;
        endcase
    end

    assign busy = (state != S_IDLE);
    // ------------------------------------------------------------------------
    // Datapath
    // ------------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            round_idx <= 3'd0;
            phase_idx <= 3'd0;
            done      <= 1'b0;
        end else begin
            state <= state_n;
            done  <= 1'b0;

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
                    phase_idx <= 3'd0;
                end

                S_RUN: begin
                    logic [31:0] s_next [0:15];
                    logic [31:0] m_next [0:15];
                    logic [31:0] m_perm [0:15];
                    for (int i = 0; i < 16; i++) begin
                        s_next[i] = s[i];
                        m_next[i] = m[i];
                        m_perm[i] = m[i];
                    end
                    if (!phase_idx[2]) begin
                        g_quarter(s_next[0], s_next[4], s_next[8], s_next[12],
                                  m_next[0], m_next[1], phase_idx[1:0]);
                        g_quarter(s_next[1], s_next[5], s_next[9], s_next[13],
                                  m_next[2], m_next[3], phase_idx[1:0]);
                        g_quarter(s_next[2], s_next[6], s_next[10], s_next[14],
                                  m_next[4], m_next[5], phase_idx[1:0]);
                        g_quarter(s_next[3], s_next[7], s_next[11], s_next[15],
                                  m_next[6], m_next[7], phase_idx[1:0]);
                    end else begin
                        g_quarter(s_next[0], s_next[5], s_next[10], s_next[15],
                                  m_next[8], m_next[9], phase_idx[1:0]);
                        g_quarter(s_next[1], s_next[6], s_next[11], s_next[12],
                                  m_next[10], m_next[11], phase_idx[1:0]);
                        g_quarter(s_next[2], s_next[7], s_next[8], s_next[13],
                                  m_next[12], m_next[13], phase_idx[1:0]);
                        g_quarter(s_next[3], s_next[4], s_next[9], s_next[14],
                                  m_next[14], m_next[15], phase_idx[1:0]);
                    end
                    if (phase_idx == 3'd7)
                        for (int i = 0; i < 16; i++)
                            m_perm[i] = m_next[BLAKE3_PERM[i]];
                    else
                        for (int i = 0; i < 16; i++) m_perm[i] = m_next[i];
                    for (int i = 0; i < 16; i++) begin
                        s[i] <= s_next[i];
                        m[i] <= m_perm[i];
                    end
                    if (phase_idx == 3'd7) begin
                        phase_idx <= 3'd0;
                        round_idx <= round_idx + 3'd1;
                    end else begin
                        phase_idx <= phase_idx + 3'd1;
                    end
                end

                S_DONE: begin
                    // Finalise per BLAKE3 spec:
                    //   out[0..7]  = s[0..7] XOR s[8..15]
                    //   out[8..15] = s[8..15] XOR cv[0..7]
                    for (int i = 0; i < 8; i++) begin
                        out_state[i]     <= s[i]     ^ s[i + 8];
                        out_state[i + 8] <= s[i + 8] ^ cv_lat[i];
                    end
                    done <= 1'b1;
                end

                default: ;
            endcase
        end
    end

endmodule : blake3_compress
