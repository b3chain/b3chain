// ============================================================================
// scratchpad_mem.sv -- 1 MB scratchpad as 8 lane partitions.
//
// Each lane gets its own 128 KB true-dual-port BRAM-banked memory:
//   - 2048 entries × 512 bits each (one BLAKE3 block per entry)
//   - Port A: dedicated to lane reads (from mixing_core)
//   - Port B: dedicated to lane writes (from mixing_core / scratch_init)
//
// Total resource: 8 lanes × ceil(2048 × 512 / 36864) = 8 × 29 = ~232
// 36-kb BRAMs in BRAM18 mode, or 8 × 15 = 120 BRAM36s.  Vivado will
// pack as it sees fit -- target is < 50% of KU5P's 432 BRAMs.
//
// scratch_init drives port B in BLOCK_BYTES units to fill from XOF.
// mixing_core has TWO request streams (read on port A, write on port B);
// the two pipelines never collide because the FSM in pow_top sequences
// them so init completes before mining starts.
// ============================================================================

`include "params_pkg.sv"

module scratchpad_mem
    import params_pkg::*;
(
    input  logic              clk,
    input  logic              rst_n,

    // -------- Port A : read (mixing_core) --------
    input  logic              ra_en       [0:LANES-1],
    input  logic [ADDR_BITS-1:0] ra_addr  [0:LANES-1],
    output logic [511:0]      ra_data     [0:LANES-1],

    // -------- Port B : write (mixing_core OR scratch_init) --------
    input  logic              wb_en       [0:LANES-1],
    input  logic [ADDR_BITS-1:0] wb_addr  [0:LANES-1],
    input  logic [511:0]      wb_data     [0:LANES-1]
);

    // -----------------------------------------------------------------------
    // 8 independent dual-port BRAM banks.
    // Style attribute prods Vivado to choose BRAM (not LUTRAM/URAM).
    // -----------------------------------------------------------------------
    genvar L;
    generate
        for (L = 0; L < LANES; L++) begin : g_lane

            (* ram_style = "block" *)
            logic [511:0] mem [0:LANE_BLOCKS-1];

            // Port A : synchronous read
            always_ff @(posedge clk) begin
                if (ra_en[L])
                    ra_data[L] <= mem[ra_addr[L]];
            end

            // Port B : synchronous write
            always_ff @(posedge clk) begin
                if (wb_en[L])
                    mem[wb_addr[L]] <= wb_data[L];
            end
        end
    endgenerate

endmodule : scratchpad_mem
