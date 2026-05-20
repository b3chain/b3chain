// Copyright (c) 2016-2022 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <bench/bench.h>
#include <bench/data/block413567.raw.h>
#include <chainparams.h>
#include <common/args.h>
#include <consensus/validation.h>
#include <crypto/b3pow_cache.h>
#include <primitives/block.h>
#include <primitives/transaction.h>
#include <serialize.h>
#include <span.h>
#include <streams.h>
#include <util/chaintype.h>
#include <validation.h>

#include <cassert>
#include <cstddef>
#include <memory>
#include <optional>
#include <vector>

// These are the two major time-sinks which happen after we have fully received
// a block off the wire, but before we can relay the block on to peers using
// compact block relay.

static void DeserializeBlockTest(benchmark::Bench& bench)
{
    DataStream stream(benchmark::data::block413567);
    std::byte a{0};
    stream.write({&a, 1}); // Prevent compaction

    bench.unit("block").run([&] {
        CBlock block;
        stream >> TX_WITH_WITNESS(block);
        bool rewound = stream.Rewind(benchmark::data::block413567.size());
        assert(rewound);
    });
}

static void DeserializeAndCheckBlockTest(benchmark::Bench& bench)
{
    DataStream stream(benchmark::data::block413567);
    std::byte a{0};
    stream.write({&a, 1}); // Prevent compaction

    ArgsManager bench_args;
    const auto chainParams = CreateChainParams(bench_args, ChainType::MAIN);
    b3pow::Cache b3pow_cache_bench{
        static_cast<size_t>(chainParams->GetConsensus().b3pow_cache_depth)};

    bench.unit("block").run([&] {
        CBlock block; // Note that CBlock caches its checked state, so we need to recreate it here
        stream >> TX_WITH_WITNESS(block);
        bool rewound = stream.Rewind(benchmark::data::block413567.size());
        assert(rewound);

        BlockValidationState validationState;
        // b3chain: this benchmark uses an upstream Bitcoin Core
        // mainnet block (413567) hashed with SHA-256d.  b3chain's
        // mainnet consensus uses B3PoW (double-BLAKE3), so the
        // pristine SHA-256d header will never satisfy the b3pow
        // target and `CheckBlock(...,fCheckPOW=true)` would
        // always return false here, making the benchmark abort
        // (bench_sanity_check, e.g. CI run 26167422579 macOS GUI).
        // The PoW check is not what this micro-benchmark measures
        // anyway -- it's the "deserialize + transaction-level
        // CheckBlock" path -- so disable the PoW step.  We keep
        // the merkle-root check (fCheckMerkleRoot=true), which
        // is still meaningful and uses the same cache.
        bool checked = CheckBlock(block, validationState, chainParams->GetConsensus(),
                                  block.hashPrevBlock, b3pow_cache_bench,
                                  /*fCheckPOW=*/false,
                                  /*fCheckMerkleRoot=*/true);
        assert(checked);
    });
}

BENCHMARK(DeserializeBlockTest, benchmark::PriorityLevel::HIGH);
BENCHMARK(DeserializeAndCheckBlockTest, benchmark::PriorityLevel::HIGH);
