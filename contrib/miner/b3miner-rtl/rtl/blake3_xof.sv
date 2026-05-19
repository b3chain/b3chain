// ============================================================================
// blake3_xof.sv -- BLAKE3 in extendable-output (XOF) mode.
//
// Used by scratch_init.sv to fill the 1 MB pad from BLAKE3(prev_hash || i).
//
// Constraints
//   - input  ≤ 64 bytes (one BLAKE3 block); enough for SPEC §6.1's
//     `prev_block_hash || u32_le(i)` = 36 bytes.
//   - output ≤ 64 bytes per call (one compress output).  For multi-block
//     output, the caller increments the counter input and re-issues
//     start; the wrapper here is single-shot.
//
// The output bytes are taken in order from the 16-word compress output,
// LE-packed -- matches the standard BLAKE3 XOF order.
// ============================================================================

`include "params_pkg.sv"

module blake3_xof
    import params_pkg::*;
(
    input  logic              clk,
    input  logic              rst_n,

    input  logic              start,
    input  logic [31:0]       input_words   [0:15],   // up to 64 bytes, LE
    input  logic [31:0]       input_len,              // bytes (0..64)
    input  logic [63:0]       counter_i,              // 0 for first block

    output logic              busy,
    output logic              done,
    output logic [31:0]       out_words     [0:15]    // 64 bytes XOF output
);

    // -----------------------------------------------------------------------
    // Flag construction:
    //   Single-block message → CHUNK_START | CHUNK_END | ROOT
    //   First call ever      → counter_i = 0
    //   Output is the full 16-word post-compress state.
    // -----------------------------------------------------------------------
    logic [31:0] flags;
    assign flags = FLAG_CHUNK_START | FLAG_CHUNK_END | FLAG_ROOT;

    // Wire the input directly as the block; cv_i = IV.
    logic [31:0] cv [0:7];
    always_comb for (int i = 0; i < 8; i++) cv[i] = BLAKE3_IV[i];

    // -----------------------------------------------------------------------
    // Compress instance
    // -----------------------------------------------------------------------
    logic [31:0] cmp_out [0:15];

    blake3_compress u_compress (
        .clk          (clk),
        .rst_n        (rst_n),
        .start        (start),
        .cv_i         (cv),
        .block_i      (input_words),
        .counter_i    (counter_i),
        .block_len_i  (input_len),
        .flags_i      (flags),
        .busy         (busy),
        .done         (done),
        .out_state    (cmp_out)
    );

    always_comb for (int i = 0; i < 16; i++) out_words[i] = cmp_out[i];

endmodule : blake3_xof
