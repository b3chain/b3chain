// Copyright (c) 2009-2010 Satoshi Nakamoto
// Copyright (c) 2009-2019 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <primitives/block.h>

#include <hash.h>
#include <serialize.h>
#include <streams.h>
#include <tinyformat.h>

extern "C" {
#include <blake3.h>
}

uint256 CBlockHeader::GetHash() const
{
    return (HashWriter{} << *this).GetHash();
}

uint256 CBlockHeader::GetPoWHash() const
{
    // Serialize header (80 bytes)
    DataStream ss{};
    ss << *this;

    // First BLAKE3-256
    uint8_t hash1[BLAKE3_OUT_LEN];
    blake3_hasher h1;
    blake3_hasher_init(&h1);
    blake3_hasher_update(&h1, (const uint8_t*)ss.data(), ss.size());
    blake3_hasher_finalize(&h1, hash1, BLAKE3_OUT_LEN);

    // Second BLAKE3-256 (double hash)
    uint8_t hash2[BLAKE3_OUT_LEN];
    blake3_hasher h2;
    blake3_hasher_init(&h2);
    blake3_hasher_update(&h2, hash1, BLAKE3_OUT_LEN);
    blake3_hasher_finalize(&h2, hash2, BLAKE3_OUT_LEN);

    uint256 result;
    memcpy(result.data(), hash2, 32);
    return result;
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
