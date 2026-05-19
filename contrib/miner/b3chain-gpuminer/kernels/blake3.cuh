// BLAKE3 compression function on CUDA.
//
// We only implement the slice of BLAKE3 that the b3chain miner needs:
//
//   * A double hash of an 80-byte block header  (BLAKE3(BLAKE3(header)))
//   * Both inputs are SHORTER than one chunk (1024 bytes), so we never
//     need the chunk-tree / parent-node code paths.
//   * No keyed mode, no derive-key mode -- only the default hash mode.
//
// First hash: 80 bytes -> 1 full block (64 B, CHUNK_START) + 1 partial
//             block (16 B, CHUNK_END | ROOT)         -> 32-byte CV
// Second hash: 32 bytes -> 1 partial block (32 B, CHUNK_START | CHUNK_END | ROOT)
//                                                    -> 32-byte digest
//
// The reference is the official BLAKE3 spec / reference C impl at
// https://github.com/BLAKE3-team/BLAKE3/blob/master/reference_impl/reference_impl.rs
// IV, MSG_PERMUTATION, the G mixer and the round structure below are
// taken verbatim from the spec.

#ifndef B3CHAIN_BLAKE3_CUH
#define B3CHAIN_BLAKE3_CUH

#include <stdint.h>

namespace b3 {

// --------------------------------------------------------------------
// Spec constants
// --------------------------------------------------------------------

// SHA-256 IV, per BLAKE3 spec section 2.1. Held in __constant__
// device memory so all threads in a warp read it as a broadcast.
// `static` gives it internal linkage to this translation unit.
__device__ __constant__ static const uint32_t IV[8] = {
    0x6A09E667u, 0xBB67AE85u, 0x3C6EF372u, 0xA54FF53Au,
    0x510E527Fu, 0x9B05688Cu, 0x1F83D9ABu, 0x5BE0CD19u,
};

// Flag bits (spec section 2.1).
constexpr uint32_t FLAG_CHUNK_START = 1u << 0;
constexpr uint32_t FLAG_CHUNK_END   = 1u << 1;
// FLAG_PARENT, FLAG_ROOT, FLAG_KEYED_HASH, FLAG_DERIVE_KEY_*: only
// FLAG_ROOT is needed here.
constexpr uint32_t FLAG_ROOT        = 1u << 3;

// Block size in bytes / words.
constexpr uint32_t BLOCK_LEN  = 64;
constexpr uint32_t BLOCK_WORDS = 16;
constexpr uint32_t CV_WORDS   = 8;

// --------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------

__device__ __forceinline__ uint32_t rotr32(uint32_t x, uint32_t n) {
    return (x >> n) | (x << (32 - n));
}

// Round mix.
__device__ __forceinline__ void g(uint32_t *s, int a, int b, int c, int d,
                                  uint32_t mx, uint32_t my) {
    s[a] = s[a] + s[b] + mx;
    s[d] = rotr32(s[d] ^ s[a], 16);
    s[c] = s[c] + s[d];
    s[b] = rotr32(s[b] ^ s[c], 12);
    s[a] = s[a] + s[b] + my;
    s[d] = rotr32(s[d] ^ s[a], 8);
    s[c] = s[c] + s[d];
    s[b] = rotr32(s[b] ^ s[c], 7);
}

// One BLAKE3 round = 4 column G + 4 diagonal G.
__device__ __forceinline__ void round_fn(uint32_t *state, const uint32_t *m) {
    // columns
    g(state, 0, 4,  8, 12, m[ 0], m[ 1]);
    g(state, 1, 5,  9, 13, m[ 2], m[ 3]);
    g(state, 2, 6, 10, 14, m[ 4], m[ 5]);
    g(state, 3, 7, 11, 15, m[ 6], m[ 7]);
    // diagonals
    g(state, 0, 5, 10, 15, m[ 8], m[ 9]);
    g(state, 1, 6, 11, 12, m[10], m[11]);
    g(state, 2, 7,  8, 13, m[12], m[13]);
    g(state, 3, 4,  9, 14, m[14], m[15]);
}

// Apply MSG_PERMUTATION = {2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8}
// to the message words for the next round (spec section 2.2).
__device__ __forceinline__ void permute(uint32_t *m) {
    uint32_t tmp[16] = {
        m[ 2], m[ 6], m[ 3], m[10],
        m[ 7], m[ 0], m[ 4], m[13],
        m[ 1], m[11], m[12], m[ 5],
        m[ 9], m[14], m[15], m[ 8],
    };
    #pragma unroll
    for (int i = 0; i < 16; ++i) m[i] = tmp[i];
}

// Compress one 64-byte block. cv_in[8] are the chaining-value words
// (8 little-endian u32). block_words[16] is the message block as 16 u32
// (also little-endian when read from bytes). out16[16] receives the
// full 16-word state needed for ROOT output expansion; for non-root
// chained calls only out16[0..8] are used.
__device__ __forceinline__ void compress(const uint32_t *cv_in,
                                         const uint32_t *block_words_in,
                                         uint64_t counter,
                                         uint32_t block_len,
                                         uint32_t flags,
                                         uint32_t *out16) {
    uint32_t state[16];
    state[ 0] = cv_in[0];  state[ 1] = cv_in[1];
    state[ 2] = cv_in[2];  state[ 3] = cv_in[3];
    state[ 4] = cv_in[4];  state[ 5] = cv_in[5];
    state[ 6] = cv_in[6];  state[ 7] = cv_in[7];
    state[ 8] = IV[0];     state[ 9] = IV[1];
    state[10] = IV[2];     state[11] = IV[3];
    state[12] = (uint32_t)(counter & 0xffffffffu);
    state[13] = (uint32_t)(counter >> 32);
    state[14] = block_len;
    state[15] = flags;

    uint32_t m[16];
    #pragma unroll
    for (int i = 0; i < 16; ++i) m[i] = block_words_in[i];

    // 7 rounds, with permutation between rounds (NOT after the last).
    round_fn(state, m); permute(m);
    round_fn(state, m); permute(m);
    round_fn(state, m); permute(m);
    round_fn(state, m); permute(m);
    round_fn(state, m); permute(m);
    round_fn(state, m); permute(m);
    round_fn(state, m);

    // Output transform (spec section 2.3): XOR upper half into lower
    // half and lower-cv-bits into upper half. Lower 8 are the chaining
    // value or first 32 bytes of the root output. We always compute
    // all 16 words even for non-root calls -- the caller takes the
    // first 8 -- because the difference is a few cheap XORs and the
    // compiler can DCE the unused stores.
    #pragma unroll
    for (int i = 0; i < 8; ++i) {
        out16[i]     = state[i] ^ state[i + 8];
        out16[i + 8] = state[i + 8] ^ cv_in[i];
    }
}

// Read 4 little-endian bytes as a u32.
__device__ __forceinline__ uint32_t load_le32(const uint8_t *p) {
    return  ((uint32_t)p[0])       |
           (((uint32_t)p[1]) <<  8) |
           (((uint32_t)p[2]) << 16) |
           (((uint32_t)p[3]) << 24);
}

// Pack 16 contiguous u32 words from a 64-byte block. The block is
// expected in already-zero-padded form (the caller pads short blocks).
__device__ __forceinline__ void words_from_bytes(const uint8_t *block_bytes,
                                                 uint32_t *m) {
    #pragma unroll
    for (int i = 0; i < 16; ++i) m[i] = load_le32(block_bytes + i * 4);
}

// Hash an arbitrary <=1024-byte input as a single chunk (spec section
// 2.5: a chunk is at most 16 blocks of 64 bytes). We always set ROOT on
// the last block since this kernel is only used at the top of the tree.
__device__ __forceinline__ void hash_single_chunk(const uint8_t *input,
                                                  uint32_t input_len,
                                                  uint8_t out32[32]) {
    // Pre-conditions: 1 <= input_len <= 1024.
    uint32_t cv[8];
    #pragma unroll
    for (int i = 0; i < 8; ++i) cv[i] = IV[i];

    uint32_t blocks_full = input_len / BLOCK_LEN;
    uint32_t tail        = input_len - blocks_full * BLOCK_LEN;

    // If input is a multiple of 64 the LAST full block is the final
    // block and gets CHUNK_END set; otherwise the partial block does.
    uint32_t total_blocks = blocks_full + (tail > 0 ? 1 : 0);

    uint32_t out16[16];
    uint8_t  pad_block[64];
    uint32_t m[16];

    for (uint32_t bi = 0; bi < total_blocks; ++bi) {
        uint32_t flags = 0;
        if (bi == 0)               flags |= FLAG_CHUNK_START;
        const bool is_last = (bi == total_blocks - 1);
        if (is_last)               flags |= FLAG_CHUNK_END | FLAG_ROOT;

        uint32_t block_len_this;
        if (!is_last || tail == 0) {
            // Full 64-byte block.
            words_from_bytes(input + bi * BLOCK_LEN, m);
            block_len_this = BLOCK_LEN;
        } else {
            // Partial last block: copy `tail` bytes, zero-pad the rest.
            #pragma unroll
            for (int i = 0; i < 64; ++i) pad_block[i] = 0;
            for (uint32_t i = 0; i < tail; ++i) {
                pad_block[i] = input[bi * BLOCK_LEN + i];
            }
            words_from_bytes(pad_block, m);
            block_len_this = tail;
        }

        // counter is 0 for a single-chunk hash (chunk index 0).
        compress(cv, m, /*counter=*/0, block_len_this, flags, out16);

        // Chain unless this is the root: but since this helper always
        // emits ROOT on the last block, we do nothing special here --
        // the cv we feed into the NEXT iteration is out16[0..8], and
        // when it IS the last block we just write those bytes out.
        #pragma unroll
        for (int i = 0; i < 8; ++i) cv[i] = out16[i];
    }

    // Emit cv as 32 little-endian bytes.
    #pragma unroll
    for (int i = 0; i < 8; ++i) {
        out32[i*4 + 0] = (uint8_t)(cv[i]      );
        out32[i*4 + 1] = (uint8_t)(cv[i] >>  8);
        out32[i*4 + 2] = (uint8_t)(cv[i] >> 16);
        out32[i*4 + 3] = (uint8_t)(cv[i] >> 24);
    }
}

// Convenience: compute BLAKE3(BLAKE3(input)) in one call.
__device__ __forceinline__ void double_blake3(const uint8_t *input,
                                               uint32_t input_len,
                                               uint8_t out32[32]) {
    uint8_t h1[32];
    hash_single_chunk(input, input_len, h1);
    hash_single_chunk(h1, 32, out32);
}

} // namespace b3

#endif // B3CHAIN_BLAKE3_CUH
