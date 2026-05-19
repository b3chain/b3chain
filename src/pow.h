// Copyright (c) 2009-2010 Satoshi Nakamoto
// Copyright (c) 2009-present The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_POW_H
#define BITCOIN_POW_H

#include <consensus/params.h>
#include <crypto/b3pow_cache.h>

#include <cstdint>
#include <optional>

class CBlockHeader;
class CBlockIndex;
class uint256;
class arith_uint256;

/**
 * Convert nBits value to target.
 *
 * @param[in] nBits     compact representation of the target
 * @param[in] pow_limit PoW limit (consensus parameter)
 *
 * @return              the proof-of-work target or nullopt if the nBits value
 *                      is invalid (due to overflow or exceeding pow_limit)
 */
std::optional<arith_uint256> DeriveTarget(unsigned int nBits, const uint256 pow_limit);

unsigned int GetNextWorkRequired(const CBlockIndex* pindexLast, const CBlockHeader *pblock, const Consensus::Params&);
unsigned int CalculateNextWorkRequired(const CBlockIndex* pindexLast, int64_t nFirstBlockTime, const Consensus::Params&);

/** Check whether a block hash satisfies the proof-of-work requirement specified by nBits */
bool CheckProofOfWork(uint256 hash, unsigned int nBits, const Consensus::Params&);
bool CheckProofOfWorkImpl(uint256 hash, unsigned int nBits, const Consensus::Params&);

/** Outcome of a B3PoW-Scratch header verification. */
enum class PoWResult {
    /** Header hashes within the target. */
    Pass,
    /** Header hashed cleanly but the result misses the target. */
    Fail,
    /** Wall-clock budget exceeded -- header rejected without a definitive
     *  pass/fail decision.  Treated as fail for consensus, but the caller
     *  must additionally punish the originating peer (Finding 4 / D1). */
    BudgetExceeded,
};

/** Full B3PoW-Scratch v1.1 header verification (cache + budget).
 *
 * Pre-checks (cheap, called by the caller before this entry):
 *   - nBits is in valid range (see DeriveTarget)
 *   - header serialises to exactly 80 bytes
 *
 * This function:
 *   1. Looks up a 1 MB scratchpad in `cache` keyed by `prev_block_hash`,
 *      building one on miss (~5 ms).
 *   2. Runs B3PoW-Scratch under a wall-clock budget of
 *      `params.b3pow_verify_budget_ms`.
 *   3. Compares the resulting pow_hash against the target derived from
 *      `nBits` and `params.powLimit`.
 *
 * Thread-safe wrt concurrent calls into the same `cache`.
 */
/** b3chain M-7 (V-9): how deep below the active tip the header sits.
 *
 *  Used by CheckBlockHeaderPoW to scale the wall-clock budget so that
 *  hostile peers cannot bleed CPU by spraying deep-fork headers. */
enum class HeaderDepth : uint8_t {
    /** Tip ±6: full budget (default).  Cheap to misclassify a stale
     *  header as a tip header, so the default is also the loosest. */
    Tip,
    /** 6 < depth ≤ 100: half budget.  Plausible orphans / honest
     *  reorgs land here. */
    Recent,
    /** depth > 100: one-fifth budget.  Almost certainly a deep-fork
     *  attack or a hopelessly stale peer; we still verify but on a
     *  very short clock. */
    Deep,
};

PoWResult CheckBlockHeaderPoW(const CBlockHeader& header,
                              const uint256& prev_block_hash,
                              unsigned int nBits,
                              const Consensus::Params& params,
                              b3pow::Cache& cache,
                              HeaderDepth depth = HeaderDepth::Tip);

/**
 * Return false if the proof-of-work requirement specified by new_nbits at a
 * given height is not possible, given the proof-of-work on the prior block as
 * specified by old_nbits.
 *
 * This function only checks that the new value is within a factor of 4 of the
 * old value for blocks at the difficulty adjustment interval, and otherwise
 * requires the values to be the same.
 *
 * Always returns true on networks where min difficulty blocks are allowed,
 * such as regtest/testnet.
 */
bool PermittedDifficultyTransition(const Consensus::Params& params, int64_t height, uint32_t old_nbits, uint32_t new_nbits);

#endif // BITCOIN_POW_H
