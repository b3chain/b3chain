// B3PoW-Scratch v1.1.1 device hash.
// One thread owns one nonce. The parent pad is built on the host and
// copied into this thread's working buffer because the mix mutates it.
//
// Included from miner.cu so nvcc emits it in the same PTX module.

__constant__ uint64_t B3_ITER_MUL[8] = {
    0xA0761D6478BD642FULL, 0xE7037ED1A0B428DBULL,
    0x8EBC6AF09C88C6E3ULL, 0x589965CC75374CC3ULL,
    0x1D8E4E27C47D124FULL, 0xEB44ACCAB455D165ULL,
    0xC863B19A77C75D70ULL, 0x6E5C6F88AA5BDA77ULL
};
__constant__ int B3_SHUFFLE[8] = {1, 6, 3, 0, 5, 2, 7, 4};
__constant__ uint32_t B3_PERM[16] = {2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8};

enum { B3_SCRATCH = 1048576, B3_LANE_BYTES = 131072, B3_BLOCK = 64, B3_ITERS = 2048 };

__device__ __forceinline__ uint64_t b3_rotr64(uint64_t x, unsigned n) {
    return (x >> n) | (x << (64 - n));
}

__device__ void b3_store_le32(uint8_t *p, uint32_t w) {
    p[0] = (uint8_t)w;
    p[1] = (uint8_t)(w >> 8);
    p[2] = (uint8_t)(w >> 16);
    p[3] = (uint8_t)(w >> 24);
}

__device__ void b3pow_mix_lane(const uint32_t cv_in[8], const uint32_t block[16],
                               uint32_t cv_out[8], uint32_t mixed_msg[16]) {
    uint32_t state[16];
    uint32_t m[16];
    #pragma unroll
    for (int i = 0; i < 8; ++i) state[i] = cv_in[i];
    #pragma unroll
    for (int i = 0; i < 4; ++i) state[8 + i] = b3::IV[i];
    state[12] = 0;
    state[13] = 0;
    state[14] = B3_BLOCK;
    state[15] = 0;
    #pragma unroll
    for (int i = 0; i < 16; ++i) m[i] = block[i];
    #pragma unroll
    for (int r = 0; r < 2; ++r) {
        b3::round_fn(state, m);
        uint32_t p[16];
        #pragma unroll
        for (int i = 0; i < 16; ++i) p[i] = m[B3_PERM[i]];
        #pragma unroll
        for (int i = 0; i < 16; ++i) m[i] = p[i];
    }
    #pragma unroll
    for (int i = 0; i < 8; ++i) cv_out[i] = state[i] ^ state[i + 8];
    #pragma unroll
    for (int i = 0; i < 16; ++i) mixed_msg[i] = m[i];
}

__device__ void b3pow_hash_nonce(const uint8_t header[80],
                                 const uint8_t *pristine,
                                 uint8_t *work,
                                 uint8_t out32[32]) {
    for (int i = 0; i < B3_SCRATCH; i += 16) {
        *reinterpret_cast<uint4 *>(work + i) = *reinterpret_cast<const uint4 *>(pristine + i);
    }

    uint8_t seed[32];
    b3::hash_single_chunk(header, 80, seed);

    uint32_t lanes[8][8];
    for (int L = 0; L < 8; ++L) {
        uint8_t msg[36];
        #pragma unroll
        for (int i = 0; i < 32; ++i) msg[i] = seed[i];
        b3_store_le32(msg + 32, (uint32_t)L);
        uint8_t dig[32];
        b3::hash_single_chunk(msg, 36, dig);
        #pragma unroll
        for (int w = 0; w < 8; ++w) lanes[L][w] = b3::load_le32(dig + w * 4);
    }

    for (int iter = 0; iter < B3_ITERS; ++iter) {
        int addr[8];
        uint32_t blocks[8][16];
        uint32_t next_cv[8][8];
        for (int L = 0; L < 8; ++L) {
            uint64_t lo = (uint64_t)lanes[L][0] | ((uint64_t)lanes[L][1] << 32);
            uint64_t hi = (uint64_t)lanes[L][2] | ((uint64_t)lanes[L][3] << 32);
            uint64_t mul = (hi ^ (uint64_t)iter) * B3_ITER_MUL[L];
            uint64_t mixed = lo ^ b3_rotr64(mul, 23);
            addr[L] = (int)(mixed & 2047u);
            const uint8_t *src = work + L * B3_LANE_BYTES + addr[L] * B3_BLOCK;
            #pragma unroll
            for (int w = 0; w < 16; ++w) blocks[L][w] = b3::load_le32(src + w * 4);
        }
        for (int L = 0; L < 8; ++L) {
            uint32_t mixed_msg[16];
            b3pow_mix_lane(lanes[L], blocks[L], next_cv[L], mixed_msg);
            uint8_t *dst = work + L * B3_LANE_BYTES + addr[L] * B3_BLOCK;
            #pragma unroll
            for (int w = 0; w < 16; ++w) {
                uint32_t x = blocks[L][w] ^ mixed_msg[w];
                b3_store_le32(dst + w * 4, x);
            }
        }
        uint32_t shuffled[8][8];
        for (int L = 0; L < 8; ++L) {
            int src = B3_SHUFFLE[L];
            #pragma unroll
            for (int w = 0; w < 8; ++w) shuffled[L][w] = next_cv[src][w];
        }
        for (int L = 0; L < 8; ++L) {
            #pragma unroll
            for (int w = 0; w < 8; ++w) lanes[L][w] = shuffled[L][w];
        }
    }

    uint8_t final_msg[260];
    for (int L = 0; L < 8; ++L) {
        #pragma unroll
        for (int w = 0; w < 8; ++w) b3_store_le32(final_msg + (L * 8 + w) * 4, lanes[L][w]);
    }
    final_msg[256] = header[76];
    final_msg[257] = header[77];
    final_msg[258] = header[78];
    final_msg[259] = header[79];
    b3::hash_single_chunk(final_msg, 260, out32);
}

extern "C" __global__
void b3pow_scratch_dump(const uint8_t *header,
                        const uint8_t *pristine,
                        uint8_t *work,
                        uint8_t *output32) {
    if (threadIdx.x == 0 && blockIdx.x == 0) {
        uint8_t hdr[80];
        #pragma unroll
        for (int i = 0; i < 80; ++i) hdr[i] = header[i];
        b3pow_hash_nonce(hdr, pristine, work, output32);
    }
}

extern "C" __global__
void b3pow_scratch_search(const uint8_t *header_template,
                          const uint8_t *share_target,
                          const uint8_t *pristine,
                          uint8_t *work_base,
                          uint32_t nslots,
                          uint32_t nonce_start,
                          uint32_t nonce_count,
                          uint32_t max_results,
                          b3::ShareCandidate *results,
                          uint32_t *result_count) {
    uint32_t slot = blockIdx.x * blockDim.x + threadIdx.x;
    if (slot >= nslots) return;
    uint8_t *work = work_base + (size_t)slot * B3_SCRATCH;
    for (uint32_t i = slot; i < nonce_count; i += nslots) {
        uint32_t nonce = nonce_start + i;
        uint8_t header[80];
        #pragma unroll
        for (int b = 0; b < 76; ++b) header[b] = header_template[b];
        header[76] = (uint8_t)(nonce & 0xff);
        header[77] = (uint8_t)((nonce >> 8) & 0xff);
        header[78] = (uint8_t)((nonce >> 16) & 0xff);
        header[79] = (uint8_t)((nonce >> 24) & 0xff);
        uint8_t hash[32];
        b3pow_hash_nonce(header, pristine, work, hash);
        if (!b3::le256_le(hash, share_target)) continue;
        uint32_t out_slot = atomicAdd(result_count, 1u);
        if (out_slot >= max_results) return;
        results[out_slot].nonce = nonce;
        #pragma unroll
        for (int b = 0; b < 32; ++b) results[out_slot].hash_le[b] = hash[b];
    }
}
