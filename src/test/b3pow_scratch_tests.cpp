// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.
//
// Consensus-grade parity tests for the C++ port of B3PoW-Scratch v1.1.
//
// The authoritative spec is contrib/miner/b3miner-rtl/SPEC.md and the
// byte-for-byte reference is contrib/miner/b3miner-rtl/ref/b3pow_ref.py.
// The CI gate is the consensus_vectors.json that gen_vectors.py emits;
// this test loads the in-tree copy at src/test/data/b3pow_consensus_vectors.json
// and asserts every entry round-trips through the C++ port unchanged.
//
// If you change b3pow_scratch.cpp and these vectors stop matching, you
// have broken consensus -- regenerate the vectors deliberately (and
// bump SPEC_VERSION) rather than "fixing" the test.

#include <test/data/b3pow_consensus_vectors.json.h>

#include <arith_uint256.h>
#include <chainparams.h>
#include <crypto/b3pow_cache.h>
#include <crypto/b3pow_scratch.h>
#include <pow.h>
#include <test/util/setup_common.h>
#include <uint256.h>
#include <util/strencodings.h>

#include <boost/test/unit_test.hpp>

#include <chrono>
#include <cstdint>
#include <span>
#include <string>
#include <univalue.h>
#include <vector>

namespace {

// Decode a "0x...." or plain hex string into a byte vector.  Used for
// both header_hex (160 hex chars = 80 bytes) and the 32-byte fields.
std::vector<uint8_t> HexToBytes(const std::string& s)
{
    auto opt = TryParseHex<uint8_t>(s);
    BOOST_REQUIRE_MESSAGE(opt.has_value(), "Failed to parse hex string: " + s);
    return *opt;
}

uint256 HexToUint256(const std::string& s)
{
    auto bytes = HexToBytes(s);
    BOOST_REQUIRE_EQUAL(bytes.size(), 32U);
    uint256 out;
    std::memcpy(out.data(), bytes.data(), 32);
    return out;
}

unsigned int ParseNBits(const std::string& s)
{
    std::string hex = s;
    if (hex.rfind("0x", 0) == 0 || hex.rfind("0X", 0) == 0) {
        hex = hex.substr(2);
    }
    BOOST_REQUIRE_EQUAL(hex.size(), 8U);
    auto bytes = HexToBytes(hex);
    BOOST_REQUIRE_EQUAL(bytes.size(), 4U);
    return (uint32_t(bytes[0]) << 24) |
           (uint32_t(bytes[1]) << 16) |
           (uint32_t(bytes[2]) <<  8) |
           (uint32_t(bytes[3]));
}

} // namespace

BOOST_FIXTURE_TEST_SUITE(b3pow_scratch_tests, BasicTestingSetup)

// Parse the embedded JSON exactly once per test process.
UniValue LoadConsensusVectors()
{
    UniValue v;
    BOOST_REQUIRE(v.read(json_tests::b3pow_consensus_vectors));
    BOOST_REQUIRE(v.isObject());
    BOOST_REQUIRE(v.exists("schema_version"));
    BOOST_REQUIRE(v.exists("entries"));
    return v;
}

// 1. Every (header_bytes, prev_block_hash) -> pow_hash mapping must
//    round-trip byte-for-byte against the Python reference's output.
BOOST_AUTO_TEST_CASE(consensus_vectors_match_python_ref)
{
    UniValue vectors = LoadConsensusVectors();

    BOOST_CHECK_EQUAL(vectors["schema_version"].getInt<int>(), 1);

    // Confirm SPEC_VERSION agreement (defensive; if Python bumps the
    // version, we must too).
    std::string spec_str = vectors["spec_version"].get_str();
    BOOST_CHECK_EQUAL(spec_str.substr(0, 2), "0x");
    uint32_t spec_in_json = std::stoul(spec_str.substr(2), nullptr, 16);
    BOOST_CHECK_EQUAL(spec_in_json, b3pow::SPEC_VERSION);

    const UniValue& entries = vectors["entries"].get_array();
    BOOST_REQUIRE(entries.size() > 0);

    bool budget_exceeded = false;
    for (size_t i = 0; i < entries.size(); ++i) {
        const UniValue& entry = entries[i];
        const std::string name = entry["name"].get_str();

        auto header_bytes = HexToBytes(entry["header_hex"].get_str());
        BOOST_REQUIRE_MESSAGE(header_bytes.size() == b3pow::HEADER_BYTES,
                              "entry " + name + ": header_hex must be 80 bytes");

        uint256 prev_hash = HexToUint256(entry["prev_block_hash_hex"].get_str());
        uint256 expected_pow = HexToUint256(entry["expected_pow_hash_hex"].get_str());

        auto pow_opt = b3pow::Hash(std::span<const uint8_t>{header_bytes},
                                   prev_hash,
                                   std::chrono::milliseconds{0},
                                   budget_exceeded);
        BOOST_REQUIRE_MESSAGE(pow_opt.has_value(),
                              "entry " + name + ": b3pow::Hash returned nullopt");
        BOOST_CHECK_MESSAGE(!budget_exceeded,
                            "entry " + name + ": budget_exceeded flag must be false with budget=0");
        BOOST_CHECK_MESSAGE(*pow_opt == expected_pow,
            "entry " + name + ": got " + pow_opt->GetHex() +
            ", expected " + expected_pow.GetHex());

        // expected_check_pow is the pure pow_hash <= target boolean
        // (i.e. without any chain-params powLimit ceiling).  We compute
        // it directly here because the per-entry nbits intentionally
        // spans across mainnet (0x1d7fffff, post-F-6 fix), regtest
        // (0x207fffff), and synthetic tight (0x03000001) pow limits,
        // and calling CheckProofOfWork with a single chain's params
        // would force-fail entries whose nbits exceeds that chain's
        // powLimit.  The C++/Python parity contract is only on the
        // (hash, target) comparison.
        unsigned int nbits = ParseNBits(entry["nbits_hex"].get_str());
        bool expected_pass = entry["expected_check_pow"].get_bool();
        arith_uint256 target;
        bool fNegative = false, fOverflow = false;
        target.SetCompact(nbits, &fNegative, &fOverflow);
        BOOST_REQUIRE_MESSAGE(!fNegative && target != 0 && !fOverflow,
                              "entry " + name + ": nbits parses as invalid");
        arith_uint256 hash_arith = UintToArith256(*pow_opt);
        bool got = (hash_arith <= target);
        BOOST_CHECK_MESSAGE(got == expected_pass,
            "entry " + name + ": pow_hash<=target(" + pow_opt->GetHex() +
            ", nbits=" + entry["nbits_hex"].get_str() + ") = " +
            (got ? "true" : "false") + ", expected " +
            (expected_pass ? "true" : "false"));
    }
}

// 2. The pad-with-cache path and the pad-from-init path must produce
//    the same pow_hash.  This is the contract that lets the cache be a
//    pure performance optimisation.
BOOST_AUTO_TEST_CASE(cache_and_oneshot_agree)
{
    UniValue vectors = LoadConsensusVectors();
    const UniValue& entries = vectors["entries"].get_array();

    b3pow::Cache cache(/*depth=*/4);
    bool budget_exceeded = false;

    for (size_t i = 0; i < entries.size(); ++i) {
        const UniValue& entry = entries[i];
        auto header_bytes = HexToBytes(entry["header_hex"].get_str());
        uint256 prev_hash = HexToUint256(entry["prev_block_hash_hex"].get_str());
        uint256 expected_pow = HexToUint256(entry["expected_pow_hash_hex"].get_str());

        // One-shot path (no cache, init pad inline).
        auto h1 = b3pow::Hash(std::span<const uint8_t>{header_bytes},
                              prev_hash,
                              std::chrono::milliseconds{0},
                              budget_exceeded);
        BOOST_REQUIRE(h1.has_value());

        // Cached path (init or reuse pad via cache).
        auto pad = cache.GetOrBuild(prev_hash);
        BOOST_REQUIRE(pad);
        auto h2 = b3pow::Hash(std::span<const uint8_t>{header_bytes},
                              prev_hash,
                              pad,
                              std::chrono::milliseconds{0},
                              budget_exceeded);
        BOOST_REQUIRE(h2.has_value());

        BOOST_CHECK_EQUAL(h1->GetHex(), h2->GetHex());
        BOOST_CHECK_EQUAL(h1->GetHex(), expected_pow.GetHex());
    }
}

// 3. The cache_pair_* entries share a prev_block_hash but use different
//    nonces; running the second one should hit the cache and produce
//    bit-identical results to running it with a freshly-initialised pad.
BOOST_AUTO_TEST_CASE(cache_pair_uses_shared_pad)
{
    UniValue vectors = LoadConsensusVectors();
    const UniValue& entries = vectors["entries"].get_array();

    const UniValue* pair0 = nullptr;
    const UniValue* pair1 = nullptr;
    for (size_t i = 0; i < entries.size(); ++i) {
        const std::string name = entries[i]["name"].get_str();
        if (name == "cache_pair_nonce_0") pair0 = &entries[i];
        else if (name == "cache_pair_nonce_1") pair1 = &entries[i];
    }
    BOOST_REQUIRE(pair0 != nullptr);
    BOOST_REQUIRE(pair1 != nullptr);

    uint256 prev_hash = HexToUint256((*pair0)["prev_block_hash_hex"].get_str());
    BOOST_CHECK_EQUAL(prev_hash.GetHex(),
                      HexToUint256((*pair1)["prev_block_hash_hex"].get_str()).GetHex());

    b3pow::Cache cache(/*depth=*/2);

    auto pad_first = cache.GetOrBuild(prev_hash);
    auto pad_second = cache.GetOrBuild(prev_hash);
    BOOST_REQUIRE(pad_first);
    BOOST_REQUIRE(pad_second);
    // Same shared_ptr -- second call hit the cache.
    BOOST_CHECK(pad_first.get() == pad_second.get());

    bool budget_exceeded = false;
    for (const UniValue* entry : {pair0, pair1}) {
        auto header_bytes = HexToBytes((*entry)["header_hex"].get_str());
        uint256 expected_pow = HexToUint256((*entry)["expected_pow_hash_hex"].get_str());
        auto h = b3pow::Hash(std::span<const uint8_t>{header_bytes},
                             prev_hash,
                             pad_first,
                             std::chrono::milliseconds{0},
                             budget_exceeded);
        BOOST_REQUIRE(h.has_value());
        BOOST_CHECK_EQUAL(h->GetHex(), expected_pow.GetHex());
    }
}

// 4. Bonus: invariant that nontrivial_prev's pow_hash differs from the
//    same header with prev_block_hash=0.  Guards against accidentally
//    skipping the parent in pad init.
BOOST_AUTO_TEST_CASE(nontrivial_prev_changes_hash)
{
    UniValue vectors = LoadConsensusVectors();
    const UniValue& entries = vectors["entries"].get_array();

    const UniValue* loose = nullptr;
    const UniValue* nontrivial = nullptr;
    for (size_t i = 0; i < entries.size(); ++i) {
        const std::string name = entries[i]["name"].get_str();
        if (name == "mainnet_target_loose_pass") loose = &entries[i];
        else if (name == "nontrivial_prev") nontrivial = &entries[i];
    }
    BOOST_REQUIRE(loose != nullptr);
    BOOST_REQUIRE(nontrivial != nullptr);

    BOOST_CHECK_EQUAL((*loose)["header_hex"].get_str(),
                      (*nontrivial)["header_hex"].get_str());

    BOOST_CHECK((*loose)["prev_block_hash_hex"].get_str() !=
                (*nontrivial)["prev_block_hash_hex"].get_str());
    BOOST_CHECK((*loose)["expected_pow_hash_hex"].get_str() !=
                (*nontrivial)["expected_pow_hash_hex"].get_str());
}

BOOST_AUTO_TEST_SUITE_END()
