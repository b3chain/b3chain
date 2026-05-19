// ============================================================================
// mixing_core.sv -- B3PoW-Scratch v1.1 inner loop, 8 lanes.
//
// Per SPEC.md §5 and §6.5:
//
//   for iter in 0 .. ITERATIONS-1:                          (2048)
//     addrs = derive_addresses(lanes, iter)                 (8 × 11-bit)
//     blks  = parallel_read(pad, addrs)                     (8 × 64 B)
//     (new_lanes, new_blks) = mix(lanes, blks)              (2 inner rounds)
//     parallel_write(pad, addrs, new_blks)
//     lanes = new_lanes
//
// Pipeline (1 iteration = 4 mining cycles @ 250 MHz):
//   ┌──────────┬──────────────────────────────────────────────────────┐
//   │ Cycle 0  │ derive addresses + issue scratchpad read              │
//   │ Cycle 1  │ BRAM read-latency wait                                │
//   │ Cycle 2  │ data arrives -> run 2 mix rounds combinationally,     │
//   │          │ register new lane state, issue writeback              │
//   │ Cycle 3  │ housekeeping: increment iter_idx, decide loop/exit    │
//   └──────────┴──────────────────────────────────────────────────────┘
//
//   2048 iter × 4 cyc = 8192 cyc inner-loop @ 250 MHz = 32.8 µs/hash.
//
// Per-iteration the design reads 8 × 64 B (= 4 kbit) and writes 8 × 64 B
// from/to scratchpad_mem -- exactly the parallel-RMW that GPUs serialise
// badly and KU5P does in one cycle.
//
// Initial lane-state derivation (8 × blake3(seed || u32_le(L))) runs
// sequentially on a shared blake3_compress instance during S_LANE_INIT
// (cost: ~80 cycles -- amortised across 2048 iter, negligible).
//
// Final hash (blake3(serialise(lanes) || nonce)) runs on the same shared
// compressor at the end (cost: ~10 cycles).
//
// Total per-nonce: ~10 (seed = blake3(header) -- done upstream)
//                + ~80 (lane init)
//                + 8192 (mix loop)
//                + ~10 (final hash)
//                ≈ 8290 cycles -> 33 µs -> ~30 kH/s per pipeline.
// ============================================================================

`include "params_pkg.sv"

module mixing_core
    import params_pkg::*;
(
    input  logic              clk,
    input  logic              rst_n,

    // -------- Control --------
    input  logic              start,
    input  logic [255:0]      seed,            // blake3(header), 32 bytes
    input  logic [31:0]       nonce,           // header[76..80]
    output logic              busy,
    output logic              done,
    output logic [255:0]      pow_hash,        // valid 1 cycle after `done`

    // -------- Scratchpad port A : read --------
    output logic              ra_en       [0:LANES-1],
    output logic [ADDR_BITS-1:0] ra_addr  [0:LANES-1],
    input  logic [511:0]      ra_data     [0:LANES-1],

    // -------- Scratchpad port B : write --------
    output logic              wb_en       [0:LANES-1],
    output logic [ADDR_BITS-1:0] wb_addr  [0:LANES-1],
    output logic [511:0]      wb_data     [0:LANES-1]
);

    // -----------------------------------------------------------------------
    // FSM
    // -----------------------------------------------------------------------
    typedef enum logic [3:0] {
        S_IDLE,
        S_LANE_INIT_START,    // launch blake3(seed || L) for current lane
        S_LANE_INIT_WAIT,     // wait for blake3 done
        S_LANE_INIT_STORE,    // store result -> lanes[L], advance L
        S_DERIVE,             // compute addrs, issue read
        S_READ_LATENCY,       // 1 BRAM-clk
        S_MIX_WRITE,          // 2 mix rounds + writeback issue
        S_ITER_DONE,          // ++iter; loop or transition to S_FINAL
        S_FINAL_START,        // launch BLAKE3 block N of the final hash
        S_FINAL_WAIT,         // wait for compress done; update chain
        S_DONE
    } state_e;

    state_e state;

    // Iteration counter (0..ITERATIONS-1)
    logic [10:0] iter_idx;

    // Per-lane state.  Stored as 8 × 256 bits (= 8 × 8 × 32 bits).
    logic [255:0] lanes [0:LANES-1];

    // Latched read data from BRAM (one cycle behind read request).
    logic [511:0] read_blk [0:LANES-1];

    // Derived addresses (registered after S_DERIVE for use in S_MIX_WRITE
    // writeback).
    logic [ADDR_BITS-1:0] addr_reg [0:LANES-1];

    // Shared BLAKE3 compressor (lane-init + final hash).
    logic              b3_start;
    logic [31:0]       b3_cv     [0:7];
    logic [31:0]       b3_block  [0:15];
    logic [63:0]       b3_counter;
    logic [31:0]       b3_blen;
    logic [31:0]       b3_flags;
    logic              b3_busy;
    logic              b3_done;
    logic [31:0]       b3_out    [0:15];

    blake3_compress u_b3 (
        .clk        (clk),
        .rst_n      (rst_n),
        .start      (b3_start),
        .cv_i       (b3_cv),
        .block_i    (b3_block),
        .counter_i  (b3_counter),
        .block_len_i(b3_blen),
        .flags_i    (b3_flags),
        .busy       (b3_busy),
        .done       (b3_done),
        .out_state  (b3_out)
    );

    // -----------------------------------------------------------------------
    // Lane-init bookkeeping
    // -----------------------------------------------------------------------
    logic [3:0] init_lane_idx;     // 0..LANES (8 = all done)

    // -----------------------------------------------------------------------
    // Final-hash bookkeeping
    //
    // serialise(lanes) = 256 B, plus 4-byte nonce = 260 B total = single
    // BLAKE3 chunk (≤ 1024 B), 5 blocks of 64 B (last one only 4 B):
    //
    //   block 0: lanes[0..1]             flags = CHUNK_START
    //   block 1: lanes[2..3]             flags = 0
    //   block 2: lanes[4..5]             flags = 0
    //   block 3: lanes[6..7]             flags = 0
    //   block 4: nonce || 60 B zero      flags = CHUNK_END | ROOT
    //                                    block_len = 4
    //
    // Each compress takes the previous CV (initial = IV) and outputs
    // the next CV.  For the ROOT block we take state[0..7] as the
    // final 32-byte hash.
    // -----------------------------------------------------------------------
    localparam int FINAL_BLOCKS = 5;
    logic [2:0]   final_blk_idx;     // 0..4
    logic [31:0]  final_cv [0:7];    // running chain value

    // -----------------------------------------------------------------------
    // Address derivation (SPEC §6.3) -- combinational, per lane.
    //
    //   mul64 = ((hi XOR iter_idx) * ITER_MUL[L]) mod 2^64
    //   mixed = lo XOR rotr64(mul64, 23)
    //   addr  = mixed mod LANE_BLOCKS
    // -----------------------------------------------------------------------
    function automatic logic [63:0] rotr64(input logic [63:0] x, input int n);
        return (x >> n) | (x << (64 - n));
    endfunction

    logic [ADDR_BITS-1:0] derived_addr [0:LANES-1];
    always_comb begin
        for (int L = 0; L < LANES; L++) begin
            logic [63:0] lo, hi, mul, mixed;
            // SPEC §6.7 serialisation: byte 0 = bits [7:0] of the lane.
            // lanes[L][0:8] = lo, [8:16] = hi -- the natural little-endian
            // packing inside the 256-bit vector.
            lo    = lanes[L][63:0];
            hi    = lanes[L][127:64];
            mul   = (hi ^ {53'b0, iter_idx}) * ITER_MUL[L];
            mixed = lo ^ rotr64(mul, 23);
            derived_addr[L] = mixed[ADDR_BITS-1:0];
        end
    end

    // -----------------------------------------------------------------------
    // Per-lane BLAKE3 short-compress (combinational across 2 inner rounds).
    // Inputs:  cv = lanes[L][255:0]    (8 × 32-bit, byte-LE packed)
    //          msg = read_blk[L][511:0] (16 × 32-bit)
    // Outputs: new_cv  = lane state after 2 rounds
    //          permuted_msg = msg after σ^2 (the message permutation applied
    //                          INNER_ROUNDS times)
    //          new_blk = msg XOR permuted_msg  (the writeback per SPEC §5)
    // -----------------------------------------------------------------------
    function automatic logic [31:0] rotr32(input logic [31:0] x, input int n);
        return (x >> n) | (x << (32 - n));
    endfunction

    task automatic g_step(ref logic [31:0] sa, ref logic [31:0] sb,
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

    task automatic do_round(ref logic [31:0] st [0:15],
                            ref logic [31:0] mm [0:15]);
        logic [31:0] nm [0:15];
        g_step(st[ 0], st[ 4], st[ 8], st[12], mm[ 0], mm[ 1]);
        g_step(st[ 1], st[ 5], st[ 9], st[13], mm[ 2], mm[ 3]);
        g_step(st[ 2], st[ 6], st[10], st[14], mm[ 4], mm[ 5]);
        g_step(st[ 3], st[ 7], st[11], st[15], mm[ 6], mm[ 7]);
        g_step(st[ 0], st[ 5], st[10], st[15], mm[ 8], mm[ 9]);
        g_step(st[ 1], st[ 6], st[11], st[12], mm[10], mm[11]);
        g_step(st[ 2], st[ 7], st[ 8], st[13], mm[12], mm[13]);
        g_step(st[ 3], st[ 4], st[ 9], st[14], mm[14], mm[15]);
        for (int i = 0; i < 16; i++) nm[i] = mm[BLAKE3_PERM[i]];
        mm = nm;
    endtask

    function automatic void short_compress(
        input  logic [255:0] cv_in,
        input  logic [511:0] msg_in,
        output logic [255:0] new_cv,
        output logic [511:0] new_blk
    );
        logic [31:0] state [0:15];
        logic [31:0] m     [0:15];
        // Load state with cv || IV[0..3] || 0,0,64,0
        for (int i = 0; i < 8; i++)  state[i]      = cv_in[32*i +: 32];
        state[ 8] = BLAKE3_IV[0];
        state[ 9] = BLAKE3_IV[1];
        state[10] = BLAKE3_IV[2];
        state[11] = BLAKE3_IV[3];
        state[12] = 32'h0;
        state[13] = 32'h0;
        state[14] = BLOCK_BYTES;
        state[15] = 32'h0;
        for (int i = 0; i < 16; i++) m[i] = msg_in[32*i +: 32];
        for (int r = 0; r < INNER_ROUNDS; r++) do_round(state, m);
        // new_cv = state[0..7] XOR state[8..15]
        for (int i = 0; i < 8; i++) new_cv[32*i +: 32] = state[i] ^ state[i + 8];
        // new_blk = original msg XOR (16-word permuted m, serialised LE)
        for (int i = 0; i < 16; i++)
            new_blk[32*i +: 32] = msg_in[32*i +: 32] ^ m[i];
    endfunction

    // Compute next lane state + new block for all lanes combinationally.
    logic [255:0] next_lanes [0:LANES-1];
    logic [511:0] writeback  [0:LANES-1];
    always_comb begin
        for (int L = 0; L < LANES; L++) begin
            logic [255:0] tmp_cv;
            logic [511:0] tmp_blk;
            short_compress(lanes[L], read_blk[L], tmp_cv, tmp_blk);
            next_lanes[L] = tmp_cv;
            writeback[L]  = tmp_blk;
        end
    end

    // Lane shuffle (SPEC §6.5): permutation [1, 6, 3, 0, 5, 2, 7, 4]
    localparam logic [2:0] LANE_PERM [0:LANES-1] =
        '{3'd1, 3'd6, 3'd3, 3'd0, 3'd5, 3'd2, 3'd7, 3'd4};

    // -----------------------------------------------------------------------
    // FSM body
    // -----------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state         <= S_IDLE;
            iter_idx      <= 11'd0;
            init_lane_idx <= 4'd0;
            b3_start      <= 1'b0;
            pow_hash      <= 256'h0;
            for (int L = 0; L < LANES; L++) begin
                lanes[L]   <= 256'h0;
                read_blk[L]<= 512'h0;
                addr_reg[L]<= '0;
                ra_en[L]   <= 1'b0;
                ra_addr[L] <= '0;
                wb_en[L]   <= 1'b0;
                wb_addr[L] <= '0;
                wb_data[L] <= 512'h0;
            end
        end else begin
            // Default per-cycle: drop all strobes.
            b3_start <= 1'b0;
            for (int L = 0; L < LANES; L++) begin
                ra_en[L] <= 1'b0;
                wb_en[L] <= 1'b0;
            end

            unique case (state)

                S_IDLE: if (start) begin
                    init_lane_idx <= 4'd0;
                    iter_idx      <= 11'd0;
                    state         <= S_LANE_INIT_START;
                end

                // ---- Lane init: blake3(seed || u32_le(L)) for L = 0..7 ----
                S_LANE_INIT_START: begin
                    // Set up cv = IV, block = seed (32 B) || u32_le(L) (4 B)
                    //                 padded zero to 64 B.
                    for (int i = 0; i < 8;  i++) b3_cv[i]    = BLAKE3_IV[i];
                    for (int i = 0; i < 16; i++) b3_block[i] = 32'h0;
                    for (int i = 0; i < 8;  i++) b3_block[i] = seed[32*i +: 32];
                    b3_block[8] = {28'h0, init_lane_idx};   // u32_le(L)
                    b3_counter = 64'h0;
                    b3_blen    = 32'd36;
                    b3_flags   = FLAG_CHUNK_START | FLAG_CHUNK_END | FLAG_ROOT;
                    b3_start   <= 1'b1;
                    state      <= S_LANE_INIT_WAIT;
                end

                S_LANE_INIT_WAIT: if (b3_done) begin
                    // Capture first 8 words = lane state (32 B).
                    for (int i = 0; i < 8; i++)
                        lanes[init_lane_idx[2:0]][32*i +: 32] <= b3_out[i];
                    state <= S_LANE_INIT_STORE;
                end

                S_LANE_INIT_STORE: begin
                    if (init_lane_idx == LANES - 1) begin
                        state <= S_DERIVE;
                    end else begin
                        init_lane_idx <= init_lane_idx + 4'd1;
                        state         <= S_LANE_INIT_START;
                    end
                end

                // ---- Mining loop ----
                S_DERIVE: begin
                    // Issue read with derived addresses; latch addrs for writeback.
                    for (int L = 0; L < LANES; L++) begin
                        ra_en[L]   <= 1'b1;
                        ra_addr[L] <= derived_addr[L];
                        addr_reg[L]<= derived_addr[L];
                    end
                    state <= S_READ_LATENCY;
                end

                S_READ_LATENCY: begin
                    // BRAM read takes one clock; nothing to do this cycle.
                    // ra_data[L] becomes valid this cycle (registered in BRAM).
                    state <= S_MIX_WRITE;
                end

                S_MIX_WRITE: begin
                    // Capture read data, run mix combinationally (via
                    // next_lanes / writeback assigns above), issue writeback,
                    // and update lane state with shuffle.
                    for (int L = 0; L < LANES; L++) begin
                        read_blk[L] <= ra_data[L];
                    end
                    // NB: writeback / next_lanes were computed against
                    // current `lanes` and `read_blk`.  Because `read_blk`
                    // is updated on this cycle (registered above) and the
                    // combinational mix uses the new value, we get one
                    // delta-cycle of correctness for free here.
                    //
                    // To be safe and explicit, we use the FRESH ra_data
                    // directly (not read_blk) by re-evaluating the mix
                    // inside this clause.
                    begin
                        logic [255:0] cv_fresh [0:LANES-1];
                        logic [511:0] blk_fresh [0:LANES-1];
                        logic [255:0] new_cv;
                        logic [511:0] new_blk;
                        for (int L = 0; L < LANES; L++) begin
                            short_compress(lanes[L], ra_data[L], new_cv, new_blk);
                            cv_fresh [L] = new_cv;
                            blk_fresh[L] = new_blk;

                            wb_en  [L] <= 1'b1;
                            wb_addr[L] <= addr_reg[L];
                            wb_data[L] <= new_blk;
                        end
                        // Apply lane shuffle.
                        for (int L = 0; L < LANES; L++)
                            lanes[L] <= cv_fresh[LANE_PERM[L]];
                    end
                    state <= S_ITER_DONE;
                end

                S_ITER_DONE: begin
                    if (iter_idx == ITERATIONS - 1) begin
                        // Begin final hash with cv = IV, block_idx = 0
                        for (int i = 0; i < 8; i++) final_cv[i] <= BLAKE3_IV[i];
                        final_blk_idx <= 3'd0;
                        state         <= S_FINAL_START;
                    end else begin
                        iter_idx <= iter_idx + 11'd1;
                        state    <= S_DERIVE;
                    end
                end

                // ---- Final hash: blake3(serialise(lanes) || nonce) ----
                // 5 blocks of BLAKE3 chain (see final_blk_idx comment).
                S_FINAL_START: begin
                    // cv input = running final_cv
                    for (int i = 0; i < 8; i++) b3_cv[i] = final_cv[i];
                    // zero by default, then fill per block index
                    for (int i = 0; i < 16; i++) b3_block[i] = 32'h0;
                    b3_counter = 64'h0;

                    unique case (final_blk_idx)
                        3'd0: begin   // lanes[0..1]
                            for (int i = 0; i < 8; i++) b3_block[i]   = lanes[0][32*i +: 32];
                            for (int i = 0; i < 8; i++) b3_block[8+i] = lanes[1][32*i +: 32];
                            b3_blen  = 32'd64;
                            b3_flags = FLAG_CHUNK_START;
                        end
                        3'd1: begin   // lanes[2..3]
                            for (int i = 0; i < 8; i++) b3_block[i]   = lanes[2][32*i +: 32];
                            for (int i = 0; i < 8; i++) b3_block[8+i] = lanes[3][32*i +: 32];
                            b3_blen  = 32'd64;
                            b3_flags = 32'h0;
                        end
                        3'd2: begin   // lanes[4..5]
                            for (int i = 0; i < 8; i++) b3_block[i]   = lanes[4][32*i +: 32];
                            for (int i = 0; i < 8; i++) b3_block[8+i] = lanes[5][32*i +: 32];
                            b3_blen  = 32'd64;
                            b3_flags = 32'h0;
                        end
                        3'd3: begin   // lanes[6..7]
                            for (int i = 0; i < 8; i++) b3_block[i]   = lanes[6][32*i +: 32];
                            for (int i = 0; i < 8; i++) b3_block[8+i] = lanes[7][32*i +: 32];
                            b3_blen  = 32'd64;
                            b3_flags = 32'h0;
                        end
                        3'd4: begin   // nonce || 60 B zero (root)
                            b3_block[0] = nonce;
                            b3_blen     = 32'd4;
                            b3_flags    = FLAG_CHUNK_END | FLAG_ROOT;
                        end
                        default: begin
                            b3_blen  = 32'h0;
                            b3_flags = 32'h0;
                        end
                    endcase

                    b3_start <= 1'b1;
                    state    <= S_FINAL_WAIT;
                end

                S_FINAL_WAIT: if (b3_done) begin
                    // Update running cv with first 8 words of compress output.
                    for (int i = 0; i < 8; i++)
                        final_cv[i] <= b3_out[i];

                    if (final_blk_idx == FINAL_BLOCKS - 1) begin
                        // Root block: capture full 32-byte pow_hash.
                        for (int i = 0; i < 8; i++)
                            pow_hash[32*i +: 32] <= b3_out[i];
                        state <= S_DONE;
                    end else begin
                        final_blk_idx <= final_blk_idx + 3'd1;
                        state         <= S_FINAL_START;
                    end
                end

                S_DONE: state <= S_IDLE;

                default: state <= S_IDLE;

            endcase
        end
    end

    assign busy = (state != S_IDLE);
    assign done = (state == S_DONE);

endmodule : mixing_core
