`include "params_pkg.sv"

// Compute BLAKE3(header[0:75] || u32_le(nonce)) for each nonce.  An 80-byte
// header occupies two BLAKE3 blocks in one chunk.
module header_seed
    import params_pkg::*;
(
    input  logic         clk,
    input  logic         rst_n,
    input  logic         start,
    input  logic         abort_i,
    input  logic [607:0] header_prefix,
    input  logic [31:0]  nonce,
    output logic         busy,
    output logic         done,
    output logic [255:0] seed
);
    typedef enum logic [2:0] {
        S_IDLE, S_FIRST_START, S_FIRST_WAIT,
        S_SECOND_START, S_SECOND_WAIT, S_DONE
    } state_e;
    state_e state;

    logic [607:0] prefix_latched;
    logic [31:0] nonce_latched;
    logic [255:0] first_cv;
    logic cmp_start, cmp_busy, cmp_done;
    logic [31:0] cmp_cv [0:7];
    logic [31:0] cmp_block [0:15];
    logic [31:0] cmp_out [0:15];
    logic [31:0] cmp_block_len, cmp_flags;

    always_comb begin
        for (int i = 0; i < 8; i++)
            cmp_cv[i] = (state == S_SECOND_START || state == S_SECOND_WAIT)
                ? first_cv[32*i +: 32] : BLAKE3_IV[i];
        for (int i = 0; i < 16; i++) cmp_block[i] = '0;
        if (state == S_SECOND_START || state == S_SECOND_WAIT) begin
            cmp_block[0] = prefix_latched[512 +: 32];
            cmp_block[1] = prefix_latched[544 +: 32];
            cmp_block[2] = prefix_latched[576 +: 32];
            cmp_block[3] = nonce_latched;
            cmp_block_len = 32'd16;
            cmp_flags = FLAG_CHUNK_END | FLAG_ROOT;
        end else begin
            for (int i = 0; i < 16; i++)
                cmp_block[i] = prefix_latched[32*i +: 32];
            cmp_block_len = 32'd64;
            cmp_flags = FLAG_CHUNK_START;
        end
    end

    blake3_compress u_compress (
        .clk(clk), .rst_n(rst_n), .start(cmp_start),
        .cv_i(cmp_cv), .block_i(cmp_block), .counter_i(64'd0),
        .block_len_i(cmp_block_len), .flags_i(cmp_flags),
        .busy(cmp_busy), .done(cmp_done), .out_state(cmp_out)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            cmp_start <= 1'b0;
            prefix_latched <= '0;
            nonce_latched <= '0;
            first_cv <= '0;
            seed <= '0;
        end else if (abort_i) begin
            state <= S_IDLE;
            cmp_start <= 1'b0;
        end else begin
            cmp_start <= 1'b0;
            case (state)
                S_IDLE: if (start && !cmp_busy) begin
                    prefix_latched <= header_prefix;
                    nonce_latched <= nonce;
                    state <= S_FIRST_START;
                end
                S_FIRST_START: begin
                    cmp_start <= 1'b1;
                    state <= S_FIRST_WAIT;
                end
                S_FIRST_WAIT: if (cmp_done) begin
                    for (int i = 0; i < 8; i++)
                        first_cv[32*i +: 32] <= cmp_out[i];
                    state <= S_SECOND_START;
                end
                S_SECOND_START: begin
                    cmp_start <= 1'b1;
                    state <= S_SECOND_WAIT;
                end
                S_SECOND_WAIT: if (cmp_done) begin
                    for (int i = 0; i < 8; i++)
                        seed[32*i +: 32] <= cmp_out[i];
                    state <= S_DONE;
                end
                S_DONE: state <= S_IDLE;
                default: state <= S_IDLE;
            endcase
        end
    end

    assign busy = (state != S_IDLE && state != S_DONE) || cmp_busy;
    assign done = state == S_DONE;
    wire _unused_cmp_busy = cmp_busy;
endmodule
