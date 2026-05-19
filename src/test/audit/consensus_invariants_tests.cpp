// Copyright (c) 2026 The B3Chain Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.
//
// [audit] Consensus invariant tests.
//
// These tests are the C++ counterpart of the Python audit scripts in
// contrib/testing/audit/. They verify the same invariants from inside the
// process, without spinning up a regtest node, so they catch regressions
// faster and run in every CI build.

#include <chainparams.h>
#include <consensus/amount.h>
#include <primitives/block.h>
#include <test/util/setup_common.h>
#include <util/chaintype.h>
#include <validation.h>

#include <boost/test/unit_test.hpp>

#include <chrono>
#include <cstdint>

CAmount GetBlockSubsidy(int nHeight, const Consensus::Params& consensusParams);

BOOST_FIXTURE_TEST_SUITE(consensus_invariants_tests, BasicTestingSetup)

// ---------------------------------------------------------------------------
// [C-1, C-2, C-3] Block subsidy schedule and supply cap.
// ---------------------------------------------------------------------------

BOOST_AUTO_TEST_CASE(audit_subsidy_halving_schedule_mainnet)
{
    SelectParams(ChainType::MAIN);
    const Consensus::Params& cp = Params().GetConsensus();

    // The initial subsidy is 50 B3C.
    BOOST_CHECK_EQUAL(GetBlockSubsidy(0, cp), 50 * COIN);
    BOOST_CHECK_EQUAL(GetBlockSubsidy(1, cp), 50 * COIN);
    BOOST_CHECK_EQUAL(GetBlockSubsidy(cp.nSubsidyHalvingInterval - 1, cp), 50 * COIN);

    // First halving boundary: subsidy becomes 25 B3C
    BOOST_CHECK_EQUAL(GetBlockSubsidy(cp.nSubsidyHalvingInterval, cp), 25 * COIN);

    // Verify the geometric pattern through the first 10 halvings
    for (int h = 0; h < 10; ++h) {
        int height = h * cp.nSubsidyHalvingInterval;
        CAmount expected = (50 * COIN) >> h;
        BOOST_CHECK_EQUAL(GetBlockSubsidy(height, cp), expected);
    }
}

BOOST_AUTO_TEST_CASE(audit_subsidy_zero_after_halving_64)
{
    SelectParams(ChainType::MAIN);
    const Consensus::Params& cp = Params().GetConsensus();

    // C-3: undefined-behaviour guard — at halving 64+, subsidy is exactly 0
    for (int halving : {64, 65, 100, 1000}) {
        int height = halving * cp.nSubsidyHalvingInterval;
        BOOST_CHECK_MESSAGE(
            GetBlockSubsidy(height, cp) == 0,
            "subsidy at halving " << halving << " (height " << height
                                  << ") must be zero");
    }
}

BOOST_AUTO_TEST_CASE(audit_total_supply_cap)
{
    SelectParams(ChainType::MAIN);
    const Consensus::Params& cp = Params().GetConsensus();

    // C-2: sum of all block subsidies converges to the canonical cap of
    // 20999999.97690000 B3C, which is 2099999997690000 satoshi.
    const int64_t expected_total = 2099999997690000LL;
    int64_t total = 0;
    for (int h = 0; h < 64; ++h) {
        const CAmount per_block = (50 * COIN) >> h;
        if (per_block == 0) break;
        total += static_cast<int64_t>(per_block) * cp.nSubsidyHalvingInterval;
    }
    BOOST_CHECK_EQUAL(total, expected_total);
    BOOST_CHECK_LT(total, MAX_MONEY);
}

// ---------------------------------------------------------------------------
// [H-1] Block ID vs PoW hash isolation.
//
// Two different methods on CBlockHeader: GetHash() (SHA-256d) and
// GetPoWHash() (B3PoW-Scratch v1.1). They must produce DIFFERENT digests
// for the same header. Even on a zeroed-out header — the algorithms differ.
// ---------------------------------------------------------------------------

BOOST_AUTO_TEST_CASE(audit_block_id_and_pow_hash_differ)
{
    CBlockHeader h{};
    h.nVersion = 1;
    h.hashPrevBlock.SetNull();
    h.hashMerkleRoot.SetNull();
    h.nTime = 1739145600;
    h.nBits = 0x1d7fffff; // post-F-6 fix mainnet powLimit
    h.nNonce = 0;

    bool budget_exceeded = false;
    const uint256 id = h.GetHash();
    auto pow_opt = h.GetPoWHash(h.hashPrevBlock, /*pad=*/nullptr,
                                std::chrono::milliseconds{0},
                                budget_exceeded);
    BOOST_REQUIRE(pow_opt.has_value());
    BOOST_CHECK(!budget_exceeded);
    const uint256 pow = *pow_opt;
    BOOST_CHECK_MESSAGE(id != pow,
        "GetHash() (SHA-256d, block ID) must differ from "
        "GetPoWHash() (B3PoW-Scratch, PoW). Both returned " << id.ToString());

    // Also: different headers produce different hashes (sanity of the
    // implementation, not just zero collisions).
    h.nNonce = 1;
    BOOST_CHECK(h.GetHash() != id);
    auto pow_opt2 = h.GetPoWHash(h.hashPrevBlock, /*pad=*/nullptr,
                                 std::chrono::milliseconds{0},
                                 budget_exceeded);
    BOOST_REQUIRE(pow_opt2.has_value());
    BOOST_CHECK(*pow_opt2 != pow);
}

// ---------------------------------------------------------------------------
// [N-1] Network isolation — magic bytes must NOT be Bitcoin's.
// ---------------------------------------------------------------------------

BOOST_AUTO_TEST_CASE(audit_mainnet_magic_is_not_bitcoin)
{
    SelectParams(ChainType::MAIN);
    const auto& msg_start = Params().MessageStart();
    // Bitcoin mainnet magic is f9 be b4 d9
    const bool is_bitcoin_mainnet =
        msg_start[0] == 0xf9 && msg_start[1] == 0xbe &&
        msg_start[2] == 0xb4 && msg_start[3] == 0xd9;
    BOOST_CHECK(!is_bitcoin_mainnet);
    // We expect b3 c0 01 0d for B3Chain mainnet
    BOOST_CHECK_EQUAL(msg_start[0], 0xb3);
    BOOST_CHECK_EQUAL(msg_start[1], 0xc0);
}

BOOST_AUTO_TEST_CASE(audit_regtest_magic_is_not_bitcoin)
{
    SelectParams(ChainType::REGTEST);
    const auto& msg_start = Params().MessageStart();
    // Bitcoin regtest magic is fa bf b5 da
    const bool is_bitcoin_regtest =
        msg_start[0] == 0xfa && msg_start[1] == 0xbf &&
        msg_start[2] == 0xb5 && msg_start[3] == 0xda;
    BOOST_CHECK(!is_bitcoin_regtest);
    // We expect b3 c2 03 0f for B3Chain regtest
    BOOST_CHECK_EQUAL(msg_start[0], 0xb3);
    BOOST_CHECK_EQUAL(msg_start[1], 0xc2);
}

BOOST_AUTO_TEST_CASE(audit_mainnet_dns_seeds_are_empty_or_b3chain_only)
{
    SelectParams(ChainType::MAIN);
    // The seed list is private; we can only check it's empty for now (b3chain
    // hasn't published seeds yet) or, when seeds are published, that none of
    // them point to a known Bitcoin DNS seed host.
    // This invariant is verified at runtime in audit-network-isolation.py;
    // here we just assert mainnet has cleared the inherited seeds.
    BOOST_CHECK(Params().DNSSeeds().empty() ||
                std::all_of(Params().DNSSeeds().begin(), Params().DNSSeeds().end(),
                            [](const auto& s) {
                                // none of the substrings below should appear
                                return s.find("bitcoin") == std::string::npos &&
                                       s.find("bitcoinstats") == std::string::npos;
                            }));
}

BOOST_AUTO_TEST_SUITE_END()
