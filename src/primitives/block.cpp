// Copyright (c) 2009-2010 Satoshi Nakamoto
// Copyright (c) 2009-2019 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <primitives/block.h>

#include <crypto/b3pow_scratch.h>
#include <hash.h>
#include <serialize.h>
#include <streams.h>
#include <tinyformat.h>
#include <util/check.h>

#include <cstdint>
#include <span>
#include <vector>

uint256 CBlockHeader::GetHash() const
{
    return (HashWriter{} << *this).GetHash();
}

std::optional<uint256> CBlockHeader::GetPoWHash(const uint256& prev_block_hash,
                                                const b3pow::PadPtr& pad,
                                                std::chrono::milliseconds budget,
                                                bool& out_budget_exceeded) const
{
    // Note: `prev_block_hash` is taken as an explicit arg (rather than
    // pulled from `hashPrevBlock`) so callers that already have the
    // value in hand (CheckBlockHeader, miner) don't pay an extra copy
    // and so tests can synthesise mismatches.  Consensus integrity
    // depends on the caller passing the *actual* parent hash here.
    DataStream ss{};
    ss << *this;
    Assert(ss.size() == b3pow::HEADER_BYTES);

    std::span<const uint8_t> header_span{
        reinterpret_cast<const uint8_t*>(ss.data()), ss.size()};

    // Build a one-shot pad if the caller didn't supply one.  Hot paths
    // (CheckBlockHeader, mining) MUST pass a cached pad; this branch is
    // only for tests / RPC tools.
    if (pad) {
        return b3pow::Hash(header_span, prev_block_hash, pad,
                           budget, out_budget_exceeded);
    }
    return b3pow::Hash(header_span, prev_block_hash,
                       budget, out_budget_exceeded);
}

std::string CBlock::ToString() const
{
    std::stringstream s;
    s << strprintf("CBlock(hash=%s, ver=0x%08x, hashPrevBlock=%s, hashMerkleRoot=%s, nTime=%u, nBits=%08x, nNonce=%u, vtx=%u)\n",
        GetHash().ToString(),
        nVersion,
        hashPrevBlock.ToString(),
        hashMerkleRoot.ToString(),
        nTime, nBits, nNonce,
        vtx.size());
    for (const auto& tx : vtx) {
        s << "  " << tx->ToString() << "\n";
    }
    return s.str();
}
