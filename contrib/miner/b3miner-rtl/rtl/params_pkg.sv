// =============================================================================
// params_pkg.sv  -- locked B3PoW-Scratch v1.1 (KU5P profile) constants
// -----------------------------------------------------------------------------
// AUTHORITATIVE SPEC: ../SPEC.md
// PYTHON REFERENCE  : ../ref/b3pow_ref.py
//
// Any change here that is not mirrored byte-for-byte in both of the above
// is a consensus break. The ref-test gate in ci/sim.sh enforces parity.
// =============================================================================

`ifndef B3PARAMS_PKG_DONE
`define B3PARAMS_PKG_DONE

package params_pkg;

  // ------------------------------------------------------------------------
  // Spec version (mirrors SPEC.md §3)
  // ------------------------------------------------------------------------
  // Packed 4-byte tag: 00 (RESV) / 01 (major) / 01 (minor) / 01 (patch).
  // v1.1.1 = F-1 fix (ITER_MUL[7] made distinct).  Firmware must read
  // 0xB3110002 from REG_ID (offset 0x00) -- old 0xB3110001 bitstreams
  // mine the v1.1.0 algorithm and are rejected.
  // The high byte 0xB3 is the project tag; the low 24 bits encode version.
  localparam logic [31:0] SPEC_VERSION = 32'h00010101;
  localparam logic [31:0] REG_ID_MAGIC = 32'hB3110002;

  // ------------------------------------------------------------------------
  // Scratchpad
  // ------------------------------------------------------------------------
  localparam int SCRATCH_BYTES = 32'd1_048_576;   // 1 MB
  localparam int LANES         = 32'd8;
  localparam int LANE_BYTES    = SCRATCH_BYTES / LANES;     // 131072
  localparam int BLOCK_BYTES   = 32'd64;                    // BLAKE3 block
  localparam int LANE_BLOCKS   = LANE_BYTES / BLOCK_BYTES;  // 2048
  localparam int ADDR_BITS     = $clog2(LANE_BLOCKS);       // 11

  // ------------------------------------------------------------------------
  // Mixing loop
  // ------------------------------------------------------------------------
  localparam int ITERATIONS    = 32'd2_048;
  localparam int INNER_ROUNDS  = 32'd2;
  localparam int LANE_BITS     = 32'd256;
  localparam int STATE_BITS    = LANE_BITS * LANES;          // 2048

  // ------------------------------------------------------------------------
  // BLAKE3 primitive constants
  // ------------------------------------------------------------------------
  localparam logic [31:0] BLAKE3_IV [0:7] = '{
    32'h6A09E667, 32'hBB67AE85, 32'h3C6EF372, 32'hA54FF53A,
    32'h510E527F, 32'h9B05688C, 32'h1F83D9AB, 32'h5BE0CD19
  };

  localparam int BLAKE3_ROUNDS = 7;

  // MSG_PERMUTATION (BLAKE3 spec, identical to the GPU miner kernel)
  localparam int BLAKE3_PERM [0:15] = '{
    2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8
  };

  localparam logic [31:0] FLAG_CHUNK_START = 32'h0000_0001;
  localparam logic [31:0] FLAG_CHUNK_END   = 32'h0000_0002;
  localparam logic [31:0] FLAG_ROOT        = 32'h0000_0008;

  // ------------------------------------------------------------------------
  // wyhash secret table -- per-lane multiplicative mixer (SPEC.md §6.3)
  // Indexed by lane number L ∈ [0, LANES-1].
  // ------------------------------------------------------------------------
  localparam logic [63:0] ITER_MUL [0:LANES-1] = '{
    64'hA0761D6478BD642F,  // L0
    64'hE7037ED1A0B428DB,  // L1
    64'h8EBC6AF09C88C6E3,  // L2
    64'h589965CC75374CC3,  // L3
    64'h1D8E4E27C47D124F,  // L4
    64'hEB44ACCAB455D165,  // L5
    64'hC863B19A77C75D70,  // L6
    64'h6E5C6F88AA5BDA77   // L7 (F-1 fix: now pairwise distinct, see SPEC.md §3)
  };

  // ------------------------------------------------------------------------
  // Cross-lane shuffle permutation -- applied to the lane state vector at
  // the end of every mix_step (SPEC.md §6.5).
  //
  //   new_lanes[L] = next_lanes[LANE_SHUFFLE[L]]   for L in 0..LANES-1
  //
  // Permutation: L' = (5 * L + 1) mod 8 -- chosen so each lane sees every
  // other lane within INNER_ROUNDS = 2 with the minimum number of swaps.
  // MUST stay byte-identical to ref/b3pow_ref.py:LANE_SHUFFLE; any change
  // is a consensus break.  Promoted from mixing_core.sv in v1.1.4 so that
  // ITER_MUL, BLAKE3_PERM, and LANE_SHUFFLE all live in one place.
  // ------------------------------------------------------------------------
  localparam logic [2:0] LANE_SHUFFLE [0:LANES-1] = '{
    3'd1, 3'd6, 3'd3, 3'd0, 3'd5, 3'd2, 3'd7, 3'd4
  };

  // ------------------------------------------------------------------------
  // SPI / regfile (mirror of b3miner-firmware/.../b3_fpga_regs.h)
  // ------------------------------------------------------------------------
  localparam logic [6:0] REG_ID            = 7'h00;
  localparam logic [6:0] REG_STATUS        = 7'h04 >> 2;  // word-addressed in HW
  localparam logic [6:0] REG_CTRL          = 7'h08 >> 2;
  localparam logic [6:0] REG_IRQ_MASK      = 7'h0C >> 2;
  localparam logic [6:0] REG_NONCE_LO      = 7'h10 >> 2;
  localparam logic [6:0] REG_NONCE_HI      = 7'h14 >> 2;
  localparam logic [6:0] REG_NTIME         = 7'h18 >> 2;
  localparam logic [6:0] REG_JOB_EPOCH     = 7'h1C >> 2;
  localparam logic [6:0] REG_HASH_COUNT    = 7'h20 >> 2;
  localparam logic [6:0] REG_TEMP_RAW      = 7'h24 >> 2;
  localparam logic [6:0] REG_SEED_BASE     = 7'h40 >> 2;  // 8 × 32-bit
  localparam logic [6:0] REG_PREV_BASE     = 7'h60 >> 2;  // 8 × 32-bit
  // The byte offsets 0x80, 0x84, and 0x100 don't fit in a 7-bit literal,
  // so encode the word offset (= byte / 4) directly.  These mirror
  // b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h:
  //   B3_FPGA_REG_NONCE_START = 0x80  -> word 0x20
  //   B3_FPGA_REG_NONCE_END   = 0x84  -> word 0x21
  //   B3_FPGA_REG_POW_HASH    = 0x100 -> word 0x40
  localparam logic [6:0] REG_NONCE_START   = 7'h20;       // byte 0x80 / 4
  localparam logic [6:0] REG_NONCE_END     = 7'h21;       // byte 0x84 / 4
  localparam logic [6:0] REG_POW_HASH_BASE = 7'h40;       // byte 0x100 / 4 (8 × 32-bit RO)

  // STATUS bits
  localparam int STATUS_BUSY    = 0;
  localparam int STATUS_SHARE   = 1;
  localparam int STATUS_SCRATCH = 2;

  // CTRL bits (write-1, auto-clear)
  localparam int CTRL_START_JOB    = 0;
  localparam int CTRL_ABORT        = 1;
  localparam int CTRL_SCRATCH_INIT = 2;

  // ------------------------------------------------------------------------
  // Clocks (mirrors b3miner_timing.xdc)
  // ------------------------------------------------------------------------
  localparam real CLK_REF_MHZ  = 200.0;
  localparam real CLK_MINE_MHZ = 250.0;
  localparam real CLK_SYS_MHZ  = 100.0;
  localparam real CLK_SPI_MHZ  = 25.0;

  // ------------------------------------------------------------------------
  // Derived widths
  // ------------------------------------------------------------------------
  // Byte address into a single lane partition.
  localparam int LANE_BYTE_ADDR_BITS = $clog2(LANE_BYTES);   // 17
  // Block address into a single lane partition (= ADDR_BITS).
  localparam int LANE_BLK_ADDR_BITS  = ADDR_BITS;            // 11
  // Total scratch block address.
  localparam int SCRATCH_BLOCKS      = SCRATCH_BYTES / BLOCK_BYTES;  // 16384
  localparam int SCRATCH_BLK_ADDR_BITS = $clog2(SCRATCH_BLOCKS);     // 14

endpackage : params_pkg

`endif  // B3PARAMS_PKG_DONE
