// Copyright (c) 2019-2021 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <chainparams.h>
#include <consensus/merkle.h>
#include <consensus/validation.h>
#include <core_io.h>
#include <core_memusage.h>
#include <crypto/b3pow_cache.h>
#include <primitives/block.h>
#include <pubkey.h>
#include <streams.h>
#include <test/fuzz/fuzz.h>
#include <test/util/random.h>
#include <util/chaintype.h>
#include <validation.h>

#include <cassert>
#include <string>

void initialize_block()
{
    SelectParams(ChainType::REGTEST);
}

FUZZ_TARGET(block, .init = initialize_block)
{
    // CheckBlock paths in b3chain reach FastRandomContext via the
    // logging/PoW caches, so the global random state is touched.
    // The CI hygiene check (`Check if using libFuzzer ... False`)
    // requires the fuzz target to deterministically reset that
    // state at the top of every iteration; otherwise the corpus
    // input is flagged as non-reproducible (run 26157408950, macOS
    // arm64 fuzz, qa-assets/block/8f1aba6d...).
    SeedRandomStateForTest(SeedRand::ZEROS);
    DataStream ds{buffer};
    CBlock block;
    try {
        ds >> TX_WITH_WITNESS(block);
    } catch (const std::ios_base::failure&) {
        return;
    }
    const Consensus::Params& consensus_params = Params().GetConsensus();
    // Fuzz-only B3PoW cache.  The real PoW check is bypassed via
    // EnableFuzzDeterminism so this cache is never actually populated,
    // but the API requires it.
    b3pow::Cache b3pow_cache_fuzz{/*depth=*/1};
    const uint256 prev_block_hash_for_fuzz = block.hashPrevBlock;
    BlockValidationState validation_state_pow_and_merkle;
    const bool valid_incl_pow_and_merkle = CheckBlock(block, validation_state_pow_and_merkle, consensus_params, prev_block_hash_for_fuzz, b3pow_cache_fuzz, /* fCheckPOW= */ true, /* fCheckMerkleRoot= */ true);
    assert(validation_state_pow_and_merkle.IsValid() || validation_state_pow_and_merkle.IsInvalid() || validation_state_pow_and_merkle.IsError());
    (void)validation_state_pow_and_merkle.Error("");
    BlockValidationState validation_state_pow;
    const bool valid_incl_pow = CheckBlock(block, validation_state_pow, consensus_params, prev_block_hash_for_fuzz, b3pow_cache_fuzz, /* fCheckPOW= */ true, /* fCheckMerkleRoot= */ false);
    assert(validation_state_pow.IsValid() || validation_state_pow.IsInvalid() || validation_state_pow.IsError());
    BlockValidationState validation_state_merkle;
    const bool valid_incl_merkle = CheckBlock(block, validation_state_merkle, consensus_params, prev_block_hash_for_fuzz, b3pow_cache_fuzz, /* fCheckPOW= */ false, /* fCheckMerkleRoot= */ true);
    assert(validation_state_merkle.IsValid() || validation_state_merkle.IsInvalid() || validation_state_merkle.IsError());
    BlockValidationState validation_state_none;
    const bool valid_incl_none = CheckBlock(block, validation_state_none, consensus_params, prev_block_hash_for_fuzz, b3pow_cache_fuzz, /* fCheckPOW= */ false, /* fCheckMerkleRoot= */ false);
    assert(validation_state_none.IsValid() || validation_state_none.IsInvalid() || validation_state_none.IsError());
    if (valid_incl_pow_and_merkle) {
        assert(valid_incl_pow && valid_incl_merkle && valid_incl_none);
    } else if (valid_incl_merkle || valid_incl_pow) {
        assert(valid_incl_none);
    }
    (void)block.GetHash();
    (void)block.ToString();
    (void)BlockMerkleRoot(block);
    if (!block.vtx.empty()) {
        (void)BlockWitnessMerkleRoot(block);
    }
    (void)GetBlockWeight(block);
    (void)GetWitnessCommitmentIndex(block);
    const size_t raw_memory_size = RecursiveDynamicUsage(block);
    const size_t raw_memory_size_as_shared_ptr = RecursiveDynamicUsage(std::make_shared<CBlock>(block));
    assert(raw_memory_size_as_shared_ptr > raw_memory_size);
    CBlock block_copy = block;
    block_copy.SetNull();
    const bool is_null = block_copy.IsNull();
    assert(is_null);
}
