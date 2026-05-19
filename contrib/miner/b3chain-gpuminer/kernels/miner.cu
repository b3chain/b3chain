// b3chain-gpuminer CUDA kernels.
//
// Two entry points:
//
//  * double_blake3_dump  -- single-input correctness probe used by the
//                           Phase-A test harness. Reads one input from
//                           global memory, hashes it, writes 32 bytes
//                           back. NOT used in the hot path.
//
//  * double_blake3_search -- the real miner kernel. One CUDA thread
//                            patches a different nonce into the host-
//                            supplied 80-byte header template, computes
//                            BLAKE3(BLAKE3(header)), compares against
//                            the share target, and -- on match -- pushes
//                            (nonce, hash) into a small results buffer
//                            via atomicAdd.
//
// The header template and share target live in normal global memory
// allocated on the host. We pass them as kernel pointers; the L1 /
// texture cache will broadcast reads of these tiny buffers across all
// threads in a warp essentially for free, so we don't gain anything
// material by promoting them to __constant__ memory (and we DO save a
// non-trivial chunk of cudarc-binding gymnastics).

#include "blake3.cuh"

namespace b3 {

// Result slot.
struct ShareCandidate {
    uint32_t nonce;
    uint8_t  hash_le[32];
};

__device__ __forceinline__ bool le256_le(const uint8_t *a, const uint8_t *b) {
    // Compare two 32-byte little-endian unsigned integers; return a <= b.
    // Walk from the MOST significant byte (index 31) down.
    #pragma unroll
    for (int i = 31; i >= 0; --i) {
        uint8_t ai = a[i];
        uint8_t bi = b[i];
        if (ai != bi) return ai < bi;
    }
    return true; // equal
}

} // namespace b3

extern "C" __global__
void double_blake3_dump(const uint8_t *input,
                        uint32_t       input_len,
                        uint8_t       *output32)
{
    // Single-thread launch, one input -> one output.
    if (threadIdx.x == 0 && blockIdx.x == 0) {
        b3::double_blake3(input, input_len, output32);
    }
}

extern "C" __global__
void double_blake3_search(const uint8_t        *header_template, // 80 bytes
                          const uint8_t        *share_target,    // 32 bytes
                          uint32_t              nonce_start,
                          uint32_t              nonce_count,
                          uint32_t              max_results,
                          b3::ShareCandidate   *results,
                          uint32_t             *result_count)
{
    uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid >= nonce_count) return;
    uint32_t nonce = nonce_start + tid;

    // Build the 80-byte header by copying the template into local
    // memory and patching the last 4 bytes (nonce, little-endian).
    uint8_t header[80];
    #pragma unroll
    for (int i = 0; i < 76; ++i) header[i] = header_template[i];
    header[76] = (uint8_t)( nonce        & 0xff);
    header[77] = (uint8_t)((nonce >>  8) & 0xff);
    header[78] = (uint8_t)((nonce >> 16) & 0xff);
    header[79] = (uint8_t)((nonce >> 24) & 0xff);

    // Hash twice.
    uint8_t hash[32];
    b3::double_blake3(header, 80, hash);

    // Compare against share target (LE).
    if (!b3::le256_le(hash, share_target)) return;

    // Won! Reserve a slot.
    uint32_t slot = atomicAdd(result_count, 1u);
    if (slot >= max_results) return;
    results[slot].nonce = nonce;
    #pragma unroll
    for (int i = 0; i < 32; ++i) results[slot].hash_le[i] = hash[i];
}
