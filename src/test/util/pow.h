// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.
//
// Shared helpers for test mining loops.  These exist purely to avoid
// repeating the same B3PoW-pad-init-and-nonce-search pattern in every
// single test that needs a mined block.
//
// Production miners (rpc/mining.cpp, bitcoin-util.cpp) replicate the
// same pattern inline because they need additional control over
// interruption, max_tries, etc.; this helper is intentionally minimal
// (no interruption, no max_tries -- just spin until found).

#ifndef BITCOIN_TEST_UTIL_POW_H
#define BITCOIN_TEST_UTIL_POW_H

#include <consensus/params.h>
#include <crypto/b3pow_scratch.h>
#include <pow.h>
#include <primitives/block.h>

#include <cassert>
#include <chrono>

namespace b3test {

/** Spin nNonce until the B3PoW-Scratch hash of `header` is at-or-below
 *  the target derived from `header.nBits`.  Caller is responsible for
 *  setting up the header (hashPrevBlock, hashMerkleRoot, nTime, nBits).
 *
 *  Uses a one-shot 1 MB scratchpad keyed by `header.hashPrevBlock`.
 *  Budget is disabled (we explicitly want to spin).
 *
 *  Mutates `header.nNonce` in place. */
inline void MineHeaderToTarget(CBlockHeader& header, const Consensus::Params& params)
{
    const auto pad = b3pow::InitScratchpad(header.hashPrevBlock);
    bool budget_exceeded = false;
    while (true) {
        auto pow_hash_opt = header.GetPoWHash(header.hashPrevBlock, pad,
                                              std::chrono::milliseconds{0},
                                              budget_exceeded);
        if (pow_hash_opt && CheckProofOfWork(*pow_hash_opt, header.nBits, params)) {
            return;
        }
        ++header.nNonce;
        assert(header.nNonce); // overflow = nonce space exhausted (regtest test bug)
    }
}

/** Variant for callers that hand us the full CBlock (it has CBlockHeader). */
inline void MineBlockToTarget(CBlock& block, const Consensus::Params& params)
{
    MineHeaderToTarget(static_cast<CBlockHeader&>(block), params);
}

/** Mine until `predicate(pow_hash)` is true, *not* the target check.
 *  Used by tests that want to mine a block whose pow_hash *fails* the
 *  target (e.g. negative tests). */
template <typename Predicate>
inline void MineHeaderUntil(CBlockHeader& header, Predicate&& predicate)
{
    const auto pad = b3pow::InitScratchpad(header.hashPrevBlock);
    bool budget_exceeded = false;
    while (true) {
        auto pow_hash_opt = header.GetPoWHash(header.hashPrevBlock, pad,
                                              std::chrono::milliseconds{0},
                                              budget_exceeded);
        if (pow_hash_opt && predicate(*pow_hash_opt)) return;
        ++header.nNonce;
        assert(header.nNonce);
    }
}

} // namespace b3test

#endif // BITCOIN_TEST_UTIL_POW_H
