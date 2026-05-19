// ============================================================================
// target_compare.sv -- int-LE comparator.
//
// Returns hash_le <= target_le where both are 256-bit unsigned numbers
// encoded little-endian byte-first (byte 0 of the hash is LSB of the
// 256-bit value).  Matches src/pow.cpp::CheckProofOfWorkImpl exactly.
// ============================================================================

`include "params_pkg.sv"

module target_compare
    import params_pkg::*;
(
    input  logic [255:0] hash_le,
    input  logic [255:0] target_le,
    output logic         valid_share
);
    // SystemVerilog comparison of `logic` vectors is unsigned big-int.
    // We treat both inputs as a 256-bit unsigned number where bit 0 of
    // the vector is bit 0 of the number, which matches int.from_bytes(..,
    // 'little'): byte 0 contributes bits [7:0], byte 1 contributes [15:8],
    // and so on.  scratchpad and SPI both deliver bytes in this order.
    assign valid_share = (hash_le <= target_le);
endmodule : target_compare
