// ============================================================================
// scratchpad_mem.sv -- 1 MB scratchpad as 8 lane partitions.
//
// Each lane gets pristine and working 128 KB BRAM-banked memories:
//   - 2048 entries × 512 bits each (one BLAKE3 block per entry)
//   - Port A: dedicated to lane reads (from mixing_core)
//   - Port B: dedicated to lane writes (from mixing_core / scratch_init)
//
// The pristine copy is restored into the working copy before every nonce;
// consensus requires each nonce to start from the same parent-derived pad.
// The two copies use about 95% of the KU5P's 480 BRAM tiles.
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
    input  logic [511:0]      wb_data     [0:LANES-1],
    input  logic              init_write,
    input  logic              copy_en,
    input  logic [ADDR_BITS-1:0] copy_addr
);

    // -----------------------------------------------------------------------
    // 8 independent dual-port BRAM banks.
    // Style attribute prods Vivado to choose BRAM (not LUTRAM/URAM).
    // -----------------------------------------------------------------------
    genvar L;
    generate
        for (L = 0; L < LANES; L++) begin : g_lane

            (* ram_style = "block" *)
            logic [511:0] work_mem [0:LANE_BLOCKS-1];
            (* ram_style = "block" *)
            logic [511:0] pristine_mem [0:LANE_BLOCKS-1];
            logic [511:0] pristine_copy_data;
            logic copy_en_d;
            logic [ADDR_BITS-1:0] copy_addr_d;

            // Port A : synchronous read
            always_ff @(posedge clk) begin
                if (ra_en[L])
                    ra_data[L] <= work_mem[ra_addr[L]];
            end

            // Pristine pad: init write port + registered copy read port.
            always_ff @(posedge clk) begin
                if (!rst_n) begin
                    copy_en_d <= 1'b0;
                    copy_addr_d <= '0;
                end else begin
                    copy_en_d <= copy_en;
                    copy_addr_d <= copy_addr;
                    if (copy_en)
                        pristine_copy_data <= pristine_mem[copy_addr];
                end
                if (init_write && wb_en[L])
                    pristine_mem[wb_addr[L]] <= wb_data[L];
            end

            // Working pad write port. Copy data is written one cycle after
            // the corresponding pristine read.
            always_ff @(posedge clk) begin
                if (init_write && wb_en[L]) begin
                    work_mem[wb_addr[L]] <= wb_data[L];
                end else if (copy_en_d) begin
                    work_mem[copy_addr_d] <= pristine_copy_data;
                end else if (wb_en[L]) begin
                    work_mem[wb_addr[L]] <= wb_data[L];
                end
            end
        end
    endgenerate

endmodule : scratchpad_mem
