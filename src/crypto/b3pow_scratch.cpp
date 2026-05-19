// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.

#include <crypto/b3pow_scratch.h>

#include <crypto/common.h>
#include <util/check.h>

extern "C" {
#include <crypto/blake3/blake3.h>
}

#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <span>

namespace b3pow {
namespace {

// ----------------------------------------------------------------------------
// Constants (must match ref/b3pow_ref.py byte-for-byte)
// ----------------------------------------------------------------------------
constexpr std::array<uint32_t, 8> BLAKE3_IV = {
    0x6A09E667u, 0xBB67AE85u, 0x3C6EF372u, 0xA54FF53Au,
    0x510E527Fu, 0x9B05688Cu, 0x1F83D9ABu, 0x5BE0CD19u,
};

constexpr std::array<uint8_t, 16> BLAKE3_PERM = {
    2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8,
};

// wyhash secret table -- one 64-bit odd multiplier per lane (SPEC §3).
// All eight values are odd, well-distributed, pairwise distinct.
// L=7 was previously a duplicate of L=1; fixed in v1.1.1 (F-1, see
// doc/security/B3POW-51-ATTACK-ANALYSIS.md).
constexpr std::array<uint64_t, LANES> ITER_MUL = {
    0xA0761D6478BD642FULL,
    0xE7037ED1A0B428DBULL,
    0x8EBC6AF09C88C6E3ULL,
    0x589965CC75374CC3ULL,
    0x1D8E4E27C47D124FULL,
    0xEB44ACCAB455D165ULL,
    0xC863B19A77C75D70ULL,
    0x6E5C6F88AA5BDA77ULL,
};

// Lane shuffle (cross-lane diffusion, SPEC §6.5).  Chosen so each lane
// sees every other lane within INNER_ROUNDS=2.  Permutation: L' = (5L+1) mod 8.
constexpr std::array<uint8_t, LANES> LANE_SHUFFLE = {1, 6, 3, 0, 5, 2, 7, 4};

// ----------------------------------------------------------------------------
// Low-level helpers
// ----------------------------------------------------------------------------
inline uint32_t rotr32(uint32_t x, unsigned n)
{
    return (x >> n) | (x << (32 - n));
}

inline uint64_t rotr64(uint64_t x, unsigned n)
{
    return (x >> n) | (x << (64 - n));
}

inline uint32_t read_u32_le(const uint8_t* p)
{
    return ReadLE32(p);
}

inline void write_u32_le(uint8_t* p, uint32_t v)
{
    WriteLE32(p, v);
}

inline uint64_t read_u64_le(const uint8_t* p)
{
    return ReadLE64(p);
}

// ----------------------------------------------------------------------------
// BLAKE3 round function (reduced-round mode for mix_step).
// ----------------------------------------------------------------------------
inline void g(uint32_t s[16], unsigned a, unsigned b, unsigned c, unsigned d,
              uint32_t mx, uint32_t my)
{
    s[a] = s[a] + s[b] + mx;
    s[d] = rotr32(s[d] ^ s[a], 16);
    s[c] = s[c] + s[d];
    s[b] = rotr32(s[b] ^ s[c], 12);
    s[a] = s[a] + s[b] + my;
    s[d] = rotr32(s[d] ^ s[a], 8);
    s[c] = s[c] + s[d];
    s[b] = rotr32(s[b] ^ s[c], 7);
}

inline void round_fn(uint32_t state[16], const uint32_t m[16])
{
    g(state, 0, 4,  8, 12, m[ 0], m[ 1]);
    g(state, 1, 5,  9, 13, m[ 2], m[ 3]);
    g(state, 2, 6, 10, 14, m[ 4], m[ 5]);
    g(state, 3, 7, 11, 15, m[ 6], m[ 7]);
    g(state, 0, 5, 10, 15, m[ 8], m[ 9]);
    g(state, 1, 6, 11, 12, m[10], m[11]);
    g(state, 2, 7,  8, 13, m[12], m[13]);
    g(state, 3, 4,  9, 14, m[14], m[15]);
}

inline void permute_msg(uint32_t m[16])
{
    uint32_t tmp[16];
    for (size_t i = 0; i < 16; ++i) tmp[i] = m[BLAKE3_PERM[i]];
    std::memcpy(m, tmp, sizeof(tmp));
}

/** Reduced-round BLAKE3 compress used by mix_step.
 *
 * Matches `blake3_short_compress` in b3pow_ref.py:
 *   state = cv (8) || IV[0..4) (4) || 0 || 0 || BLOCK_BYTES || 0
 *   for r in range(INNER_ROUNDS):
 *       round_fn(state, m)
 *       m = permute_msg(m)
 *   new_cv[i] = state[i] XOR state[i+8]   for i in 0..7
 *   permuted_msg = m                       (passed back to caller)
 */
inline void blake3_short_compress(const uint32_t cv_in[8],
                                  uint32_t m[16],          // in/out (permuted)
                                  uint32_t new_cv_out[8])  // 8 words
{
    uint32_t state[16];
    for (size_t i = 0; i < 8; ++i) state[i] = cv_in[i];
    state[ 8] = BLAKE3_IV[0];
    state[ 9] = BLAKE3_IV[1];
    state[10] = BLAKE3_IV[2];
    state[11] = BLAKE3_IV[3];
    state[12] = 0;
    state[13] = 0;
    state[14] = static_cast<uint32_t>(BLOCK_BYTES);
    state[15] = 0;
    for (unsigned r = 0; r < INNER_ROUNDS; ++r) {
        round_fn(state, m);
        permute_msg(m);
    }
    for (size_t i = 0; i < 8; ++i) new_cv_out[i] = state[i] ^ state[i + 8];
}

// ----------------------------------------------------------------------------
// Wrappers around the existing BLAKE3 library
// ----------------------------------------------------------------------------
inline void blake3_hash_full(const uint8_t* data, size_t len, uint8_t out[BLAKE3_OUT_LEN])
{
    blake3_hasher h;
    blake3_hasher_init(&h);
    blake3_hasher_update(&h, data, len);
    blake3_hasher_finalize(&h, out, BLAKE3_OUT_LEN);
}

inline void blake3_xof_into(const uint8_t* data, size_t len, uint8_t* out, size_t out_len)
{
    blake3_hasher h;
    blake3_hasher_init(&h);
    blake3_hasher_update(&h, data, len);
    blake3_hasher_finalize(&h, out, out_len);
}

// ----------------------------------------------------------------------------
// Pad init (SPEC §6.1)
// ----------------------------------------------------------------------------
void FillScratchpad(const uint256& prev_block_hash, Pad& pad)
{
    // input buffer: 32 bytes prev_hash || 4 bytes LE block index
    uint8_t buf[32 + 4];
    std::memcpy(buf, prev_block_hash.data(), 32);
    for (uint32_t i = 0; i < SCRATCH_BLOCKS; ++i) {
        WriteLE32(buf + 32, i);
        blake3_xof_into(buf, sizeof(buf),
                        pad.bytes.data() + i * BLOCK_BYTES, BLOCK_BYTES);
    }
}

// ----------------------------------------------------------------------------
// Per-iteration helpers (SPEC §6.2-6.7)
// ----------------------------------------------------------------------------
inline void DeriveAddresses(const uint8_t lanes[LANES][32],
                            uint32_t iter_idx,
                            unsigned addrs_out[LANES])
{
    const uint64_t iter64 = static_cast<uint64_t>(iter_idx);
    for (size_t L = 0; L < LANES; ++L) {
        const uint64_t lo = read_u64_le(&lanes[L][0]);
        const uint64_t hi = read_u64_le(&lanes[L][8]);
        const uint64_t mul = (hi ^ iter64) * ITER_MUL[L]; // overflow = mod 2^64 in unsigned
        const uint64_t mixed = lo ^ rotr64(mul, 23);
        addrs_out[L] = static_cast<unsigned>(mixed & ADDR_MASK);
    }
}

inline void MixOneStep(const uint8_t lanes_in[LANES][32],
                       const uint8_t blocks_in[LANES][BLOCK_BYTES],
                       uint8_t lanes_out[LANES][32],
                       uint8_t writebacks[LANES][BLOCK_BYTES])
{
    // Per-lane reduced-round compress.
    uint8_t tmp_lanes[LANES][32];
    for (size_t L = 0; L < LANES; ++L) {
        uint32_t cv_words[8];
        for (size_t i = 0; i < 8; ++i) cv_words[i] = read_u32_le(&lanes_in[L][i * 4]);

        uint32_t m[16];
        for (size_t i = 0; i < 16; ++i) m[i] = read_u32_le(&blocks_in[L][i * 4]);

        uint32_t new_cv[8];
        blake3_short_compress(cv_words, m /*in/out*/, new_cv);

        for (size_t i = 0; i < 8; ++i) write_u32_le(&tmp_lanes[L][i * 4], new_cv[i]);

        // permuted_msg as bytes XOR original block
        for (size_t i = 0; i < 16; ++i) {
            uint32_t in_word = read_u32_le(&blocks_in[L][i * 4]);
            write_u32_le(&writebacks[L][i * 4], in_word ^ m[i]);
        }
    }
    // Apply lane shuffle (cross-lane diffusion).
    for (size_t L = 0; L < LANES; ++L) {
        std::memcpy(lanes_out[L], tmp_lanes[LANE_SHUFFLE[L]], 32);
    }
}

inline const uint8_t* PadBlock(const Pad& pad, size_t lane, unsigned addr)
{
    return pad.bytes.data() + lane * LANE_BYTES + addr * BLOCK_BYTES;
}

inline uint8_t* PadBlockMut(Pad& pad, size_t lane, unsigned addr)
{
    return pad.bytes.data() + lane * LANE_BYTES + addr * BLOCK_BYTES;
}

// ----------------------------------------------------------------------------
// Budget enforcement
//
// We probe `std::chrono::steady_clock` every 256 iterations.  At
// ITERATIONS=2048, that's 8 probes per full hash, ~6 ms granularity.
// The probe itself is ~30 ns on Linux; we deliberately don't probe
// every iteration to keep the inner loop fast.
// ----------------------------------------------------------------------------
inline constexpr unsigned BUDGET_PROBE_STRIDE = 256;

} // anonymous namespace

// ----------------------------------------------------------------------------
// Public API
// ----------------------------------------------------------------------------
PadPtr InitScratchpad(const uint256& prev_block_hash)
{
    auto pad = std::make_shared<Pad>();
    FillScratchpad(prev_block_hash, *pad);
    return pad;
}

std::optional<uint256> Hash(std::span<const uint8_t> header_bytes,
                            const uint256& prev_block_hash,
                            const PadPtr& pad_ptr,
                            std::chrono::milliseconds budget,
                            bool& out_budget_exceeded)
{
    Assert(header_bytes.size() == HEADER_BYTES);
    Assert(pad_ptr != nullptr);

    out_budget_exceeded = false;

    const auto t_start = std::chrono::steady_clock::now();
    const bool enforce_budget = (budget.count() > 0);

    // Lanes: 8 × 32 bytes = 256 bytes (init via blake3(seed || L)).
    uint8_t seed[BLAKE3_OUT_LEN];
    blake3_hash_full(header_bytes.data(), header_bytes.size(), seed);

    uint8_t lanes[LANES][32];
    {
        uint8_t seed_buf[BLAKE3_OUT_LEN + 4];
        std::memcpy(seed_buf, seed, BLAKE3_OUT_LEN);
        for (uint32_t L = 0; L < LANES; ++L) {
            WriteLE32(seed_buf + BLAKE3_OUT_LEN, L);
            blake3_hash_full(seed_buf, sizeof(seed_buf), lanes[L]);
        }
    }

    // Take a *mutable* copy of the pad so concurrent verifiers don't
    // race on writebacks.  This is the price of caching by
    // `prev_block_hash` -- the per-call 1 MB memcpy is ~50 us, dwarfed
    // by the 5 ms init it replaces.
    //
    // (We can't write directly to the cached pad: it's `const PadPtr`
    // and other threads may be reading it concurrently.)
    //
    // Heap-allocate to keep the 1 MB off the stack -- default Windows
    // stack size is 1 MB and we cannot put a Pad-sized object on it.
    auto work_pad = std::make_unique<Pad>();
    std::memcpy(work_pad->bytes.data(), pad_ptr->bytes.data(), SCRATCH_BYTES);

    uint8_t blocks_in[LANES][BLOCK_BYTES];
    uint8_t new_lanes[LANES][32];
    uint8_t writebacks[LANES][BLOCK_BYTES];

    for (unsigned r = 0; r < ITERATIONS; ++r) {
        unsigned addrs[LANES];
        DeriveAddresses(lanes, r, addrs);

        // Per-lane read.
        for (size_t L = 0; L < LANES; ++L) {
            std::memcpy(blocks_in[L], PadBlock(*work_pad, L, addrs[L]), BLOCK_BYTES);
        }

        MixOneStep(lanes, blocks_in, new_lanes, writebacks);

        // Writeback (block XOR mix output -- mix already XOR'd inside).
        for (size_t L = 0; L < LANES; ++L) {
            std::memcpy(PadBlockMut(*work_pad, L, addrs[L]),
                        writebacks[L], BLOCK_BYTES);
        }

        std::memcpy(lanes, new_lanes, sizeof(lanes));

        if (enforce_budget && (r % BUDGET_PROBE_STRIDE) == BUDGET_PROBE_STRIDE - 1) {
            const auto elapsed = std::chrono::steady_clock::now() - t_start;
            if (std::chrono::duration_cast<std::chrono::milliseconds>(elapsed) > budget) {
                out_budget_exceeded = true;
                return std::nullopt;
            }
        }
    }

    // Final hash: blake3(concat(lanes[0..7]) || nonce(4))
    uint8_t final_input[LANES * 32 + 4];
    for (size_t L = 0; L < LANES; ++L) {
        std::memcpy(&final_input[L * 32], lanes[L], 32);
    }
    std::memcpy(&final_input[LANES * 32], header_bytes.data() + 76, 4);

    uint8_t out_bytes[BLAKE3_OUT_LEN];
    blake3_hash_full(final_input, sizeof(final_input), out_bytes);

    // Final budget check (the last iteration could have blown the budget
    // between probes).
    if (enforce_budget) {
        const auto elapsed = std::chrono::steady_clock::now() - t_start;
        if (std::chrono::duration_cast<std::chrono::milliseconds>(elapsed) > budget) {
            out_budget_exceeded = true;
            return std::nullopt;
        }
    }

    uint256 result;
    std::memcpy(result.data(), out_bytes, 32);
    return result;
}

std::optional<uint256> Hash(std::span<const uint8_t> header_bytes,
                            const uint256& prev_block_hash,
                            std::chrono::milliseconds budget,
                            bool& out_budget_exceeded)
{
    auto pad = InitScratchpad(prev_block_hash);
    return Hash(header_bytes, prev_block_hash, pad, budget, out_budget_exceeded);
}

} // namespace b3pow
