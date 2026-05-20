// Copyright (c) 2020-2022 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <chain.h>
#include <chainparams.h>
#include <crypto/b3pow_cache.h>
#include <crypto/b3pow_scratch.h>
#include <pow.h>
#include <primitives/block.h>
#include <streams.h>
#include <test/fuzz/FuzzedDataProvider.h>
#include <test/fuzz/fuzz.h>
#include <test/fuzz/util.h>
#include <test/util/random.h>
#include <util/chaintype.h>
#include <util/check.h>
#include <util/overflow.h>

#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <optional>
#include <span>
#include <string>
#include <vector>

void initialize_pow()
{
    SelectParams(ChainType::MAIN);
}

FUZZ_TARGET(pow, .init = initialize_pow)
{
    FuzzedDataProvider fuzzed_data_provider(buffer.data(), buffer.size());
    const Consensus::Params& consensus_params = Params().GetConsensus();
    std::vector<std::unique_ptr<CBlockIndex>> blocks;
    const uint32_t fixed_time = fuzzed_data_provider.ConsumeIntegral<uint32_t>();
    const uint32_t fixed_bits = fuzzed_data_provider.ConsumeIntegral<uint32_t>();
    LIMITED_WHILE(fuzzed_data_provider.remaining_bytes() > 0, 10000) {
        const std::optional<CBlockHeader> block_header = ConsumeDeserializable<CBlockHeader>(fuzzed_data_provider);
        if (!block_header) {
            continue;
        }
        CBlockIndex& current_block{
            *blocks.emplace_back(std::make_unique<CBlockIndex>(*block_header))};
        {
            CBlockIndex* previous_block = blocks.empty() ? nullptr : PickValue(fuzzed_data_provider, blocks).get();
            const int current_height = (previous_block != nullptr && previous_block->nHeight != std::numeric_limits<int>::max()) ? previous_block->nHeight + 1 : 0;
            if (fuzzed_data_provider.ConsumeBool()) {
                current_block.pprev = previous_block;
            }
            if (fuzzed_data_provider.ConsumeBool()) {
                current_block.nHeight = current_height;
            }
            if (fuzzed_data_provider.ConsumeBool()) {
                const uint32_t seconds = current_height * consensus_params.nPowTargetSpacing;
                if (!AdditionOverflow(fixed_time, seconds)) {
                    current_block.nTime = fixed_time + seconds;
                }
            }
            if (fuzzed_data_provider.ConsumeBool()) {
                current_block.nBits = fixed_bits;
            }
            if (fuzzed_data_provider.ConsumeBool()) {
                current_block.nChainWork = previous_block != nullptr ? previous_block->nChainWork + GetBlockProof(*previous_block) : arith_uint256{0};
            } else {
                current_block.nChainWork = ConsumeArithUInt256(fuzzed_data_provider);
            }
        }
        {
            (void)GetBlockProof(current_block);
            (void)CalculateNextWorkRequired(&current_block, fuzzed_data_provider.ConsumeIntegralInRange<int64_t>(0, std::numeric_limits<int64_t>::max()), consensus_params);
            if (current_block.nHeight != std::numeric_limits<int>::max() && current_block.nHeight - (consensus_params.DifficultyAdjustmentInterval() - 1) >= 0) {
                (void)GetNextWorkRequired(&current_block, &(*block_header), consensus_params);
            }
        }
        {
            const auto& to = PickValue(fuzzed_data_provider, blocks);
            const auto& from = PickValue(fuzzed_data_provider, blocks);
            const auto& tip = PickValue(fuzzed_data_provider, blocks);
            try {
                (void)GetBlockProofEquivalentTime(*to, *from, *tip, consensus_params);
            } catch (const uint_error&) {
            }
        }
        {
            const std::optional<uint256> hash = ConsumeDeserializable<uint256>(fuzzed_data_provider);
            if (hash) {
                (void)CheckProofOfWorkImpl(*hash, fuzzed_data_provider.ConsumeIntegral<unsigned int>(), consensus_params);
            }
        }
    }
}


FUZZ_TARGET(pow_transition, .init = initialize_pow)
{
    FuzzedDataProvider fuzzed_data_provider(buffer.data(), buffer.size());
    const Consensus::Params& consensus_params{Params().GetConsensus()};
    std::vector<std::unique_ptr<CBlockIndex>> blocks;

    const uint32_t old_time{fuzzed_data_provider.ConsumeIntegral<uint32_t>()};
    const uint32_t new_time{fuzzed_data_provider.ConsumeIntegral<uint32_t>()};
    const int32_t version{fuzzed_data_provider.ConsumeIntegral<int32_t>()};
    uint32_t nbits{fuzzed_data_provider.ConsumeIntegral<uint32_t>()};

    const arith_uint256 pow_limit = UintToArith256(consensus_params.powLimit);
    arith_uint256 old_target;
    old_target.SetCompact(nbits);
    if (old_target > pow_limit) {
        nbits = pow_limit.GetCompact();
    }
    // Create one difficulty adjustment period worth of headers
    for (int height = 0; height < consensus_params.DifficultyAdjustmentInterval(); ++height) {
        CBlockHeader header;
        header.nVersion = version;
        header.nTime = old_time;
        header.nBits = nbits;
        if (height == consensus_params.DifficultyAdjustmentInterval() - 1) {
            header.nTime = new_time;
        }
        auto current_block{std::make_unique<CBlockIndex>(header)};
        current_block->pprev = blocks.empty() ? nullptr : blocks.back().get();
        current_block->nHeight = height;
        blocks.emplace_back(std::move(current_block));
    }
    auto last_block{blocks.back().get()};
    unsigned int new_nbits{GetNextWorkRequired(last_block, nullptr, consensus_params)};
    Assert(PermittedDifficultyTransition(consensus_params, last_block->nHeight + 1, last_block->nBits, new_nbits));
}

// ---------------------------------------------------------------------------
// b3pow_random_header
// ---------------------------------------------------------------------------
// Fuzz the B3PoW-Scratch verifier with random (header, prev_block_hash)
// inputs.  The point is to exercise:
//
//   1. The 80-byte header is parsed deterministically and never reads
//      out-of-bounds (we feed exactly 80 bytes).
//   2. The cache hit/miss + LRU eviction paths don't crash under
//      random keys.
//   3. The wall-clock budget path is exercised both above and below
//      the per-hash cost, so BudgetExceeded and Pass/Fail are all
//      reachable.
//   4. EnableFuzzDeterminism() short-circuits to the cheap oracle in
//      CheckBlockHeaderPoW -- so this fuzz target finishes a hash in
//      microseconds, not the ~6 ms real B3PoW would take.  The
//      `BSAN`/`MSAN`/`ASAN` builds rely on this to stay tractable.
//
// We deliberately do NOT shell out to the Python reference in the
// fuzz harness itself; that integration is wired up as an optional CI
// job (see plan Part E and `tools/ci/b3pow_python_oracle.py`) which
// records discrepancies as fuzz inputs for replay here.
// ---------------------------------------------------------------------------
FUZZ_TARGET(b3pow_random_header, .init = initialize_pow)
{
    SeedRandomStateForTest(SeedRand::ZEROS);
    FuzzedDataProvider fdp(buffer.data(), buffer.size());

    // 1) Fill an 80-byte header from fuzz input, padding with zeros if
    //    we ran short.  Treat the raw bytes as the wire serialisation;
    //    the verifier doesn't care whether the parents/merkle roots
    //    are well-formed -- only the hash matters.
    std::array<uint8_t, b3pow::HEADER_BYTES> raw{};
    const auto sample = fdp.ConsumeBytes<uint8_t>(b3pow::HEADER_BYTES);
    // Guard against empty inputs: `std::vector::data()` returns a
    // null pointer when the vector is empty, and memcpy with a null
    // source pointer is UB even when n==0 (UBSan flags it as
    // "null pointer passed as argument 2, which is declared to never
    // be null").  No-op the copy in that case; `raw` is already
    // zero-initialised above.
    if (!sample.empty()) {
        std::memcpy(raw.data(), sample.data(),
                    std::min(sample.size(), raw.size()));
    }

    // 2) Random prev_block_hash, 32 bytes (drained from fuzz input).
    uint256 prev_hash;
    const auto prev_bytes = fdp.ConsumeBytes<uint8_t>(32);
    if (!prev_bytes.empty()) {
        std::memcpy(prev_hash.data(), prev_bytes.data(),
                    std::min(prev_bytes.size(), size_t{32}));
    }

    // 3) Reconstruct the matching CBlockHeader.  We don't validate the
    //    deserialisation here (random bytes are valid for the fixed
    //    80-byte header layout); we just need a CBlockHeader for the
    //    GetPoWHash() and CheckBlockHeaderPoW() entry points.
    CBlockHeader header;
    {
        DataStream ds{raw};
        try {
            ds >> header;
        } catch (...) {
            return; // malformed wire bytes; nothing to fuzz
        }
    }

    // 4) Exercise the raw b3pow::Hash() API with a random budget.
    //    Budgets are clamped to a small range so that BudgetExceeded
    //    is reachable inside fuzz determinism (which short-circuits
    //    inside CheckBlockHeaderPoW only -- b3pow::Hash itself still
    //    runs the real loop).
    {
        const auto ms = fdp.ConsumeIntegralInRange<int64_t>(0, 200);
        std::chrono::milliseconds budget{ms};
        bool exceeded = false;
        (void)b3pow::Hash(std::span<const uint8_t>{raw}, prev_hash,
                          budget, exceeded);
    }

    // 5) Exercise the cached path: insert a small cache, hit it twice
    //    with the same prev_hash, then with a different one to force
    //    eviction.
    {
        b3pow::Cache cache(/*depth=*/2);
        auto pad = cache.GetOrBuild(prev_hash);
        if (pad) {
            bool exceeded = false;
            (void)b3pow::Hash(std::span<const uint8_t>{raw}, prev_hash,
                              pad, std::chrono::milliseconds{0},
                              exceeded);
            // Force a second insert to drive LRU.
            uint256 alt = prev_hash;
            alt.data()[31] ^= 0xff;
            (void)cache.GetOrBuild(alt);
        }
    }

    // 6) Exercise CheckBlockHeaderPoW end-to-end.  Use a small budget
    //    so all three PoWResult buckets are reachable.
    {
        const Consensus::Params& cparams = Params().GetConsensus();
        b3pow::Cache cache(/*depth=*/1);
        const unsigned int nbits = fdp.ConsumeIntegral<unsigned int>();
        (void)CheckBlockHeaderPoW(header, prev_hash, nbits, cparams, cache);
    }
}
