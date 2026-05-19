// ============================================================================
// scratch_init.sv -- fill the 1 MB scratchpad from BLAKE3-XOF(prev || i).
//
// Per SPEC.md §6.1:
//
//   for i in 0 .. SCRATCH_BLOCKS - 1:            (16,384)
//       pad[i*64 : (i+1)*64] = BLAKE3-XOF(prev_block_hash || u32_le(i), 64)
//
// The XOF block for index i is independent of the block for index i+1,
// so we just chain blake3_xof calls sequentially.  Each call takes
// ~9 clk_sys cycles (1 compress).  Total init time:
//   16,384 blocks × ~9 cycles / 100 MHz = ~1.47 ms.
//
// Output addresses are striped lane-major: block index `i` lands in
// lane (i / LANE_BLOCKS), partition offset (i % LANE_BLOCKS).  This
// matches the addressing convention in mixing_core / read_scratchpad
// (SPEC §6.4).
// ============================================================================

`include "params_pkg.sv"

module scratch_init
    import params_pkg::*;
(
    input  logic              clk,
    input  logic              rst_n,

    input  logic              start,
    input  logic [255:0]      prev_block_hash,    // 32 bytes, byte0 = bits 7:0

    output logic              busy,
    output logic              done,

    // Drives scratchpad_mem's port B
    output logic              wb_en      [0:LANES-1],
    output logic [ADDR_BITS-1:0] wb_addr [0:LANES-1],
    output logic [511:0]      wb_data    [0:LANES-1]
);

    typedef enum logic [1:0] { S_IDLE, S_LOAD, S_WAIT, S_DONE } state_e;
    state_e state;

    logic [SCRATCH_BLK_ADDR_BITS-1:0] block_idx;   // 0..16383

    // XOF interface
    logic              xof_start;
    logic [31:0]       xof_input_words [0:15];
    logic [31:0]       xof_input_len;
    logic [63:0]       xof_counter_i;
    logic              xof_busy;
    logic              xof_done;
    logic [31:0]       xof_out_words   [0:15];

    blake3_xof u_xof (
        .clk          (clk),
        .rst_n        (rst_n),
        .start        (xof_start),
        .input_words  (xof_input_words),
        .input_len    (xof_input_len),
        .counter_i    (xof_counter_i),
        .busy         (xof_busy),
        .done         (xof_done),
        .out_words    (xof_out_words)
    );

    // Pack prev_block_hash (bytes 0..31) + u32_le(block_idx) into xof_input_words.
    // Input length = 32 + 4 = 36 bytes.
    always_comb begin
        for (int w = 0; w < 16; w++) xof_input_words[w] = 32'h0;
        // prev_block_hash[byte i] -> input_words[i/4][8*(i%4) +: 8]
        for (int i = 0; i < 32; i++) begin
            xof_input_words[i/4][8*(i%4) +: 8] = prev_block_hash[8*i +: 8];
        end
        // u32_le(block_idx) at byte 32..35 -> word 8
        xof_input_words[8] = {{(32-SCRATCH_BLK_ADDR_BITS){1'b0}}, block_idx};
        xof_input_len      = 32'd36;
        xof_counter_i      = 64'd0;
    end

    // Address striping: lane = block_idx[SCRATCH_BLK_ADDR_BITS-1 : ADDR_BITS]
    //                   offs = block_idx[ADDR_BITS-1 : 0]
    logic [2:0]              cur_lane;
    logic [ADDR_BITS-1:0]    cur_offs;
    assign cur_lane = block_idx[SCRATCH_BLK_ADDR_BITS-1 : ADDR_BITS];
    assign cur_offs = block_idx[ADDR_BITS-1 : 0];

    // FSM
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            block_idx <= '0;
            xof_start <= 1'b0;
            for (int L = 0; L < LANES; L++) begin
                wb_en[L]   <= 1'b0;
                wb_addr[L] <= '0;
                wb_data[L] <= 512'h0;
            end
        end else begin
            xof_start <= 1'b0;
            for (int L = 0; L < LANES; L++) wb_en[L] <= 1'b0;

            unique case (state)
                S_IDLE: if (start) begin
                    block_idx <= '0;
                    xof_start <= 1'b1;
                    state     <= S_WAIT;
                end

                S_WAIT: if (xof_done) begin
                    // Pack xof_out_words (16 × 32-bit = 64 bytes) into 512-bit
                    // BRAM word.  Byte order LE: out_words[0] is the first
                    // 4 bytes, bits [7:0] = byte 0.
                    for (int w = 0; w < 16; w++) begin
                        // wb_data is a flat 512 bits per lane.  Place word w
                        // at bits 32*w +: 32, matching scratchpad's storage.
                        wb_data[cur_lane][32*w +: 32] <= xof_out_words[w];
                    end
                    wb_addr[cur_lane] <= cur_offs;
                    wb_en  [cur_lane] <= 1'b1;
                    state             <= S_LOAD;
                end

                S_LOAD: begin
                    // Advance to next block index or finish.
                    if (block_idx == SCRATCH_BLOCKS - 1) begin
                        state <= S_DONE;
                    end else begin
                        block_idx <= block_idx + 1'b1;
                        xof_start <= 1'b1;
                        state     <= S_WAIT;
                    end
                end

                S_DONE: state <= S_IDLE;

                default: state <= S_IDLE;
            endcase
        end
    end

    assign busy = (state != S_IDLE && state != S_DONE);
    assign done = (state == S_DONE);

endmodule : scratch_init
