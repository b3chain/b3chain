// Copyright (c) 2009-2010 Satoshi Nakamoto
// Copyright (c) 2009-2022 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <pow.h>

#include <arith_uint256.h>
#include <chain.h>
#include <crypto/b3pow_cache.h>
#include <crypto/b3pow_scratch.h>
#include <pow/lwma3.h>
#include <primitives/block.h>
#include <uint256.h>
#include <util/check.h>

#include <chrono>
#include <optional>

unsigned int GetNextWorkRequired(const CBlockIndex* pindexLast, const CBlockHeader *pblock, const Consensus::Params& params)
{
    assert(pindexLast != nullptr);
    unsigned int nProofOfWorkLimit = UintToArith256(params.powLimit).GetCompact();

    // b3chain: Early difficulty guard — during the bootstrap phase, if a block
    // takes more than 2x the target time, drop difficulty by 25% per-block to
    // help the chain survive low initial hashrate.  Applied regardless of
    // whether the chain uses LWMA-3 or the legacy 2016-block retarget so
    // bootstrap behaviour is identical between regtest (legacy) and mainnet
    // (LWMA-3).
    if (params.nEarlyDifficultyGuardHeight > 0 &&
        (pindexLast->nHeight + 1) <= params.nEarlyDifficultyGuardHeight &&
        pblock->GetBlockTime() > pindexLast->GetBlockTime() + params.nPowTargetSpacing * 2)
    {
        const arith_uint256 bnPowLimit = UintToArith256(params.powLimit);
        arith_uint256 bnNew;
        bnNew.SetCompact(pindexLast->nBits);
        // Increase target (decrease difficulty) by 25%
        bnNew += (bnNew >> 2);
        if (bnNew > bnPowLimit)
            bnNew = bnPowLimit;
        return bnNew.GetCompact();
    }

    // b3chain M-3 (V-4 mitigation): LWMA-3 difficulty algorithm.
    //
    // When use_lwma3 is on (mainnet / testnet / signet), retarget every
    // block using a sliding window of LWMA3_WINDOW = 60 blocks.  Closes
    // the 2-week-retarget bootstrap window that ETC was reorged through
    // in Aug 2020.  See src/pow/lwma3.h and
    // doc/security/B3POW-51-ATTACK-ANALYSIS.md V-4.
    //
    // Regtest keeps the legacy path because the existing functional
    // tests rely on its 2016-block boundaries.
    if (params.use_lwma3) {
        if (params.fPowNoRetargeting) {
            return pindexLast->nBits;
        }
        // Min-difficulty exception preserved (test networks).
        if (params.fPowAllowMinDifficultyBlocks &&
            pblock->GetBlockTime() > pindexLast->GetBlockTime() + params.nPowTargetSpacing * 2) {
            return nProofOfWorkLimit;
        }
        return b3pow::CalculateLwma3Target(pindexLast, params);
    }

    // Legacy 2016-block linear retarget (Bitcoin/regtest path).
    // Only change once per difficulty adjustment interval
    if ((pindexLast->nHeight+1) % params.DifficultyAdjustmentInterval() != 0)
    {
        if (params.fPowAllowMinDifficultyBlocks)
        {
            // Special difficulty rule for testnet:
            // If the new block's timestamp is more than 2* 10 minutes
            // then it MUST be a min-difficulty block.
            if (pblock->GetBlockTime() > pindexLast->GetBlockTime() + params.nPowTargetSpacing*2)
                return nProofOfWorkLimit;
            else
            {
                // Return the last non-special-min-difficulty-rules-block
                const CBlockIndex* pindex = pindexLast;
                while (pindex->pprev && pindex->nHeight % params.DifficultyAdjustmentInterval() != 0 && pindex->nBits == nProofOfWorkLimit)
                    pindex = pindex->pprev;
                return pindex->nBits;
            }
        }
        return pindexLast->nBits;
    }

    // Go back by what we want to be 14 days worth of blocks
    int nHeightFirst = pindexLast->nHeight - (params.DifficultyAdjustmentInterval()-1);
    assert(nHeightFirst >= 0);
    const CBlockIndex* pindexFirst = pindexLast->GetAncestor(nHeightFirst);
    assert(pindexFirst);

    return CalculateNextWorkRequired(pindexLast, pindexFirst->GetBlockTime(), params);
}

unsigned int CalculateNextWorkRequired(const CBlockIndex* pindexLast, int64_t nFirstBlockTime, const Consensus::Params& params)
{
    if (params.fPowNoRetargeting)
        return pindexLast->nBits;

    // Limit adjustment step
    int64_t nActualTimespan = pindexLast->GetBlockTime() - nFirstBlockTime;
    if (nActualTimespan < params.nPowTargetTimespan/4)
        nActualTimespan = params.nPowTargetTimespan/4;
    if (nActualTimespan > params.nPowTargetTimespan*4)
        nActualTimespan = params.nPowTargetTimespan*4;

    // Retarget
    const arith_uint256 bnPowLimit = UintToArith256(params.powLimit);
    arith_uint256 bnNew;

    // Special difficulty rule for Testnet4
    if (params.enforce_BIP94) {
        // Here we use the first block of the difficulty period. This way
        // the real difficulty is always preserved in the first block as
        // it is not allowed to use the min-difficulty exception.
        int nHeightFirst = pindexLast->nHeight - (params.DifficultyAdjustmentInterval()-1);
        const CBlockIndex* pindexFirst = pindexLast->GetAncestor(nHeightFirst);
        bnNew.SetCompact(pindexFirst->nBits);
    } else {
        bnNew.SetCompact(pindexLast->nBits);
    }

    bnNew *= nActualTimespan;
    bnNew /= params.nPowTargetTimespan;

    if (bnNew > bnPowLimit)
        bnNew = bnPowLimit;

    return bnNew.GetCompact();
}

// Check that on difficulty adjustments, the new difficulty does not increase
// or decrease beyond the permitted limits.
bool PermittedDifficultyTransition(const Consensus::Params& params, int64_t height, uint32_t old_nbits, uint32_t new_nbits)
{
    if (params.fPowAllowMinDifficultyBlocks) return true;

    // b3chain M-3: LWMA-3 retargets per-block with its own internal
    // bounds (solve-time clamped to [-5T, +6T] => max ~50% per-window
    // change, much smaller per single block).  The legacy 2016-block
    // bounds-check below is meaningless under LWMA-3 because every
    // block has its own retarget.  Defer to LWMA-3's internal clamps.
    if (params.use_lwma3) return true;

    if (height % params.DifficultyAdjustmentInterval() == 0) {
        int64_t smallest_timespan = params.nPowTargetTimespan/4;
        int64_t largest_timespan = params.nPowTargetTimespan*4;

        const arith_uint256 pow_limit = UintToArith256(params.powLimit);
        arith_uint256 observed_new_target;
        observed_new_target.SetCompact(new_nbits);

        // Calculate the largest difficulty value possible:
        arith_uint256 largest_difficulty_target;
        largest_difficulty_target.SetCompact(old_nbits);
        largest_difficulty_target *= largest_timespan;
        largest_difficulty_target /= params.nPowTargetTimespan;

        if (largest_difficulty_target > pow_limit) {
            largest_difficulty_target = pow_limit;
        }

        // Round and then compare this new calculated value to what is
        // observed.
        arith_uint256 maximum_new_target;
        maximum_new_target.SetCompact(largest_difficulty_target.GetCompact());
        if (maximum_new_target < observed_new_target) return false;

        // Calculate the smallest difficulty value possible:
        arith_uint256 smallest_difficulty_target;
        smallest_difficulty_target.SetCompact(old_nbits);
        smallest_difficulty_target *= smallest_timespan;
        smallest_difficulty_target /= params.nPowTargetTimespan;

        if (smallest_difficulty_target > pow_limit) {
            smallest_difficulty_target = pow_limit;
        }

        // Round and then compare this new calculated value to what is
        // observed.
        arith_uint256 minimum_new_target;
        minimum_new_target.SetCompact(smallest_difficulty_target.GetCompact());
        if (minimum_new_target > observed_new_target) return false;
    } else if (old_nbits != new_nbits) {
        return false;
    }
    return true;
}

// Bypasses the actual proof of work check during fuzz testing with a simplified validation checking whether
// the most significant bit of the last byte of the hash is set.
bool CheckProofOfWork(uint256 hash, unsigned int nBits, const Consensus::Params& params)
{
    if (EnableFuzzDeterminism()) return (hash.data()[31] & 0x80) == 0;
    return CheckProofOfWorkImpl(hash, nBits, params);
}

std::optional<arith_uint256> DeriveTarget(unsigned int nBits, const uint256 pow_limit)
{
    bool fNegative;
    bool fOverflow;
    arith_uint256 bnTarget;

    bnTarget.SetCompact(nBits, &fNegative, &fOverflow);

    // Check range
    if (fNegative || bnTarget == 0 || fOverflow || bnTarget > UintToArith256(pow_limit))
        return {};

    return bnTarget;
}

bool CheckProofOfWorkImpl(uint256 hash, unsigned int nBits, const Consensus::Params& params)
{
    auto bnTarget{DeriveTarget(nBits, params.powLimit)};
    if (!bnTarget) return false;

    // Check proof of work matches claimed amount.
    //
    // Compare the dereferenced optional value directly rather than
    // going through `optional<T>::operator>(T)`.  libc++'s mixed-type
    // operators are implemented via SFINAE'd helpers that confuse
    // MSan's shadow-tracking when the optional was move-/copy-
    // constructed across a function-return boundary; the spurious
    // "use-of-uninitialized-value" was reported on the MSan-bench
    // job (run 26157408950, bench_sanity_check, b3chain CI) even
    // though every byte of `*bnTarget` is written by SetCompact in
    // DeriveTarget above.  The dereferenced form skips the helper
    // template and produces a straightforward
    // `arith_uint256 > arith_uint256` call.
    if (UintToArith256(hash) > *bnTarget)
        return false;

    return true;
}

PoWResult CheckBlockHeaderPoW(const CBlockHeader& header,
                              const uint256& prev_block_hash,
                              unsigned int nBits,
                              const Consensus::Params& params,
                              b3pow::Cache& cache,
                              HeaderDepth depth)
{
    // 1. Pre-check: derive the target.  Rejects out-of-range nBits and
    //    headers with nBits above the powLimit.  These are free (no
    //    BLAKE3 or scratchpad) and are how Finding 4 / D1 keeps a peer
    //    that sprays garbage headers from spending B3PoW CPU.
    auto bnTarget{DeriveTarget(nBits, params.powLimit)};
    if (!bnTarget) return PoWResult::Fail;

    // 2. Fuzz-determinism bypass: in fuzz builds we don't run the real
    //    PoW.  This matches the existing CheckProofOfWork shortcut so
    //    fuzz harnesses can still construct "valid" headers.
    if (EnableFuzzDeterminism()) {
        // The fuzz oracle uses the SHA-256d header hash, *not* the
        // B3PoW hash -- B3PoW is too slow to fuzz directly and is
        // covered by its own targeted fuzz harness.
        const uint256 cheap_hash = header.GetHash();
        return ((cheap_hash.data()[31] & 0x80) == 0)
                   ? PoWResult::Pass
                   : PoWResult::Fail;
    }

    // 3. Cache lookup / pad init.  GetOrBuild is internally serialized
    //    with shared_mutex; concurrent verifiers against the same parent
    //    pay only the wait, never the rebuild.
    b3pow::PadPtr pad = cache.GetOrBuild(prev_block_hash);

    // 4. Run the hash under the configured wall-clock budget, scaled by
    //    the header's depth below the active tip (M-7, V-9).  A hostile
    //    peer flooding deep-fork headers spends progressively less of
    //    our CPU per header.  Tip-height headers always get the full
    //    budget so honest IBD never trips a budget overrun.
    //
    //    Numerator / denominator semantics (so we can express the
    //    Recent and Deep slices without floating-point division and
    //    keep the regtest's 1000 ms budget exactly representable):
    //       Tip    -> budget * 1 / 1   (e.g. 50 ms mainnet)
    //       Recent -> budget * 1 / 2   (e.g. 25 ms mainnet)
    //       Deep   -> budget * 1 / 5   (e.g. 10 ms mainnet)
    int64_t numerator = 1, denom = 1;
    switch (depth) {
        case HeaderDepth::Tip:    numerator = 1; denom = 1; break;
        case HeaderDepth::Recent: numerator = 1; denom = 2; break;
        case HeaderDepth::Deep:   numerator = 1; denom = 5; break;
    }
    const int64_t base_ms = params.b3pow_verify_budget_ms > 0
                                ? params.b3pow_verify_budget_ms : 0;
    const int64_t scaled_ms = (base_ms * numerator) / denom;
    const auto budget = std::chrono::milliseconds{scaled_ms};
    bool budget_exceeded = false;
    auto pow_opt = header.GetPoWHash(prev_block_hash, pad, budget, budget_exceeded);
    if (!pow_opt) {
        // Budget overrun.  Finding 4 / D1: caller (validation) must
        // surface BLOCK_POW_BUDGET so net_processing can demote the
        // peer.
        return PoWResult::BudgetExceeded;
    }
    if (budget_exceeded) {
        // Defense in depth: Hash() may have completed (returned a hash)
        // but still tripped the budget on the post-loop probe.  Treat
        // that as overrun too -- a peer should not be able to scrape
        // verification under the budget by being just-fast-enough.
        return PoWResult::BudgetExceeded;
    }

    // 5. Compare to target.
    if (UintToArith256(*pow_opt) > *bnTarget) return PoWResult::Fail;
    return PoWResult::Pass;
}
