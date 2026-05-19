// Copyright (c) 2026 The B3Chain Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <arith_uint256.h>
#include <chain.h>
#include <chainparams.h>
#include <consensus/params.h>
#include <pow/lwma3.h>
#include <test/util/setup_common.h>
#include <uint256.h>
#include <util/chaintype.h>

#include <boost/test/unit_test.hpp>

#include <deque>

namespace {

// Build a synthetic CBlockIndex chain with the given solve times and
// constant nBits.  Returns the head of the chain; the deque owns the
// memory.  Caller must keep the deque alive for the duration of the
// test.
const CBlockIndex* BuildChain(std::deque<CBlockIndex>& chain,
                              int64_t start_time,
                              int64_t spacing_seconds,
                              uint32_t nBits,
                              int n_blocks)
{
    BOOST_REQUIRE(n_blocks > 0);
    chain.clear();
    for (int i = 0; i < n_blocks; ++i) {
        chain.emplace_back();
        CBlockIndex& bi = chain.back();
        bi.nHeight = i;
        bi.nTime = static_cast<unsigned int>(start_time + i * spacing_seconds);
        bi.nBits = nBits;
        if (i > 0) {
            chain.back().pprev = &chain[i - 1];
        }
    }
    return &chain.back();
}

// Convenience: compute the multiplicative ratio of two compact targets.
double TargetRatio(uint32_t a, uint32_t b)
{
    arith_uint256 ta, tb;
    ta.SetCompact(a);
    tb.SetCompact(b);
    if (tb == 0) return 0.0;
    // Avoid floating-point overflow on huge 256-bit targets: shift both
    // sides down by enough bits to fit in a uint64_t.
    int shift = 0;
    arith_uint256 max_u64 = arith_uint256(std::numeric_limits<uint64_t>::max());
    arith_uint256 ta_w = ta;
    arith_uint256 tb_w = tb;
    while (ta_w > max_u64 || tb_w > max_u64) {
        ta_w >>= 1;
        tb_w >>= 1;
        ++shift;
    }
    return static_cast<double>(ta_w.GetLow64()) / static_cast<double>(tb_w.GetLow64());
}

}  // namespace

BOOST_FIXTURE_TEST_SUITE(lwma3_tests, BasicTestingSetup)

// Build a Consensus::Params instance with use_lwma3 = true, suitable for
// driving CalculateLwma3Target() directly.
static Consensus::Params LwmaParams()
{
    Consensus::Params p{};
    p.powLimit = uint256{"00000000ffff0000000000000000000000000000000000000000000000000000"};
    p.nPowTargetSpacing = 600;
    p.nPowTargetTimespan = 14 * 24 * 60 * 60;
    p.use_lwma3 = true;
    p.fPowAllowMinDifficultyBlocks = false;
    p.fPowNoRetargeting = false;
    return p;
}

/* T1: stable network -- blocks at exactly target spacing produce a
 * stable target (within tight bounds since LWMA-3 has minor signed-int
 * arithmetic effects). */
BOOST_AUTO_TEST_CASE(lwma3_stable_network)
{
    const auto params = LwmaParams();
    std::deque<CBlockIndex> chain;
    // 120 blocks at exactly target spacing.
    const uint32_t starting_nbits = 0x1d00ffffU;
    const CBlockIndex* tip = BuildChain(chain, 1'700'000'000, params.nPowTargetSpacing,
                                        starting_nbits, 120);
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);
    const double ratio = TargetRatio(new_nbits, starting_nbits);
    BOOST_CHECK_MESSAGE(ratio > 0.9 && ratio < 1.1,
        "stable network: expected target ~ 1.0x, got ratio=" << ratio);
}

/* T2: +10x hashrate shock -- blocks come 10x faster than target.
 * LWMA-3 should drop the target (raise difficulty) significantly. */
BOOST_AUTO_TEST_CASE(lwma3_positive_hashrate_shock)
{
    const auto params = LwmaParams();
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1d00ffffU;
    // Each block takes 1/10 the target spacing -> 10x hashrate.
    const CBlockIndex* tip = BuildChain(chain, 1'700'000'000, params.nPowTargetSpacing / 10,
                                        starting_nbits, 120);
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);
    const double ratio = TargetRatio(new_nbits, starting_nbits);
    BOOST_CHECK_MESSAGE(ratio < 0.5,
        "+10x shock: expected target < 0.5x, got ratio=" << ratio);
    // Verify the target is positive (didn't collapse to zero).
    BOOST_CHECK(new_nbits > 0);
}

/* T3: -10x hashrate shock -- blocks come 10x slower than target.
 * LWMA-3 should raise the target (lower difficulty); clamped at +6T
 * upper bound on solve time, the effective increase is large but
 * bounded. */
BOOST_AUTO_TEST_CASE(lwma3_negative_hashrate_shock)
{
    const auto params = LwmaParams();
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1d00ffffU;
    // Each block takes 10x the target spacing -> 0.1x hashrate.  This
    // exceeds the +6T clamp, so each solve time is treated as 6T.
    const CBlockIndex* tip = BuildChain(chain, 1'700'000'000, params.nPowTargetSpacing * 10,
                                        starting_nbits, 120);
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);
    const double ratio = TargetRatio(new_nbits, starting_nbits);
    // Under the +6T clamp, weighted_sum / (T*sum_of_weights) approaches 6.
    BOOST_CHECK_MESSAGE(ratio > 2.0 && ratio < 8.0,
        "-10x shock: expected target ~3-7x, got ratio=" << ratio);
}

/* T4: oscillating solve times -- average target should stay near the
 * starting value, never going to extremes. */
BOOST_AUTO_TEST_CASE(lwma3_oscillating_solve_times)
{
    const auto params = LwmaParams();
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1d00ffffU;

    // Build a chain where odd-indexed blocks are 2T apart and even-indexed
    // blocks are 0.5T apart (alternating fast/slow).
    chain.clear();
    int64_t t = 1'700'000'000;
    const int N = 120;
    for (int i = 0; i < N; ++i) {
        chain.emplace_back();
        CBlockIndex& bi = chain.back();
        bi.nHeight = i;
        bi.nTime = static_cast<unsigned int>(t);
        bi.nBits = starting_nbits;
        if (i > 0) chain.back().pprev = &chain[i - 1];
        int64_t delta = (i % 2 == 0)
            ? (params.nPowTargetSpacing * 2)
            : (params.nPowTargetSpacing / 2);
        t += delta;
    }
    const CBlockIndex* tip = &chain.back();
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);
    const double ratio = TargetRatio(new_nbits, starting_nbits);
    // Average solve time is 1.25T, so target should rise slightly.
    BOOST_CHECK_MESSAGE(ratio > 0.9 && ratio < 1.5,
        "oscillating: expected target ~1.0-1.5x, got ratio=" << ratio);
}

/* T5: short chain (less than window) -- LWMA-3 must not crash and must
 * return a sensible target. */
BOOST_AUTO_TEST_CASE(lwma3_short_chain_below_window)
{
    const auto params = LwmaParams();
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1d00ffffU;
    const CBlockIndex* tip = BuildChain(chain, 1'700'000'000, params.nPowTargetSpacing,
                                        starting_nbits, 10);
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);
    // Should be roughly stable since blocks are at target spacing.
    const double ratio = TargetRatio(new_nbits, starting_nbits);
    BOOST_CHECK_MESSAGE(ratio > 0.5 && ratio < 2.0,
        "short chain: target ratio=" << ratio);
    BOOST_CHECK(new_nbits > 0);
}

// ============================================================================
// b3chain F-6 fix (M-13): two-tier floor tests
//
// The DAA emits a target clamped to:
//   - powLimit (consensus floor)               for next_height <= nEarlyDifficultyGuardHeight
//   - operating_pow_floor_bits (soft floor)    for next_height >  nEarlyDifficultyGuardHeight
// ============================================================================

namespace {

// Build a params instance with both a consensus floor and a stricter
// operating floor.  We use Bitcoin-shaped values for clarity:
//   powLimit         = 0x1d00ffff (target ~ 2^224)
//   operating_floor  = 0x1c00ffff (target ~ 2^216, i.e. 256x stricter)
// The exact numeric values don't matter -- only that operating_floor
// represents a strictly smaller target than powLimit.
Consensus::Params LwmaParamsWithOperatingFloor()
{
    Consensus::Params p{};
    p.powLimit = uint256{"00000000ffff0000000000000000000000000000000000000000000000000000"};
    p.nPowTargetSpacing = 600;
    p.nPowTargetTimespan = 14 * 24 * 60 * 60;
    p.use_lwma3 = true;
    p.fPowAllowMinDifficultyBlocks = false;
    p.fPowNoRetargeting = false;
    p.nEarlyDifficultyGuardHeight = 10'000;
    p.operating_pow_floor_bits = 0x1c00ffffU; // strictly tighter than powLimit
    return p;
}

}  // namespace

/* T7 (M-13): post-bootstrap steady-state -- a -10x hashrate shock past
 * the early-difficulty guard window should clamp at operating_pow_floor,
 * not at powLimit.  This is the heart of the F-6 mitigation. */
BOOST_AUTO_TEST_CASE(operating_pow_floor_steady_state)
{
    auto params = LwmaParamsWithOperatingFloor();
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1c00ffffU; // start at the operating floor
    // Build a chain whose head sits well past nEarlyDifficultyGuardHeight.
    const int n = 120;
    chain.clear();
    int64_t t = 1'700'000'000;
    for (int i = 0; i < n; ++i) {
        chain.emplace_back();
        CBlockIndex& bi = chain.back();
        // Shift heights so the next block is at (guard + n).
        bi.nHeight = static_cast<int>(params.nEarlyDifficultyGuardHeight) + i;
        bi.nTime = static_cast<unsigned int>(t);
        bi.nBits = starting_nbits;
        if (i > 0) chain.back().pprev = &chain[i - 1];
        // -10x hashrate shock: blocks come 10x slower than target.  After
        // the +6T solve-time clamp, LWMA-3 wants to raise the target ~6x.
        t += params.nPowTargetSpacing * 10;
    }
    const CBlockIndex* tip = &chain.back();
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);

    // Compute the *unclamped* steady-state target (powLimit clamp only)
    // by running the same window against a params instance with
    // operating_pow_floor_bits disabled.
    auto params_no_floor = params;
    params_no_floor.operating_pow_floor_bits = 0;
    const uint32_t unclamped_nbits = pow::CalculateLwma3Target(tip, params_no_floor);

    arith_uint256 t_new, t_unclamped, t_op_floor;
    t_new.SetCompact(new_nbits);
    t_unclamped.SetCompact(unclamped_nbits);
    t_op_floor.SetCompact(params.operating_pow_floor_bits);

    // Sanity: the unclamped target is wider than the operating floor.
    BOOST_REQUIRE_MESSAGE(t_unclamped > t_op_floor,
        "T7 precondition failed: unclamped target should be wider than the "
        "operating floor; unclamped=" << unclamped_nbits
        << ", op_floor=" << params.operating_pow_floor_bits);
    // Result with operating floor active: clamped at operating floor.
    BOOST_CHECK_EQUAL(new_nbits, params.operating_pow_floor_bits);
    // And the clamped target is strictly tighter than the unclamped one.
    BOOST_CHECK(t_new < t_unclamped);
}

/* T8 (M-13): during the early-difficulty guard window, operating floor
 * is intentionally NOT applied -- a low-hashrate cold start can still
 * reach minimum difficulty (= powLimit). */
BOOST_AUTO_TEST_CASE(operating_pow_floor_disabled_in_bootstrap)
{
    auto params = LwmaParamsWithOperatingFloor();
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1c00ffffU; // start at the operating floor
    // Build a chain whose head sits BEFORE nEarlyDifficultyGuardHeight.
    const int n = 120;
    chain.clear();
    int64_t t = 1'700'000'000;
    for (int i = 0; i < n; ++i) {
        chain.emplace_back();
        CBlockIndex& bi = chain.back();
        // Heights 100..219 -- next block at 220 << guard (10000).
        bi.nHeight = 100 + i;
        bi.nTime = static_cast<unsigned int>(t);
        bi.nBits = starting_nbits;
        if (i > 0) chain.back().pprev = &chain[i - 1];
        // -10x hashrate shock.
        t += params.nPowTargetSpacing * 10;
    }
    const CBlockIndex* tip = &chain.back();
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);

    arith_uint256 t_new, t_op_floor;
    t_new.SetCompact(new_nbits);
    t_op_floor.SetCompact(params.operating_pow_floor_bits);

    // Bootstrap: the target may go ABOVE the operating floor (which
    // would be forbidden in steady state).
    BOOST_CHECK_MESSAGE(t_new > t_op_floor,
        "T8: in bootstrap, operating floor should NOT clamp; got new_nbits="
        << new_nbits << " operating_floor=" << params.operating_pow_floor_bits);

    // But still bounded by powLimit.
    arith_uint256 t_powlimit = UintToArith256(params.powLimit);
    BOOST_CHECK(t_new <= t_powlimit);
}

/* T9 (M-13): operating floor disabled (= 0) reproduces legacy behaviour
 * -- target clamped only at powLimit. */
BOOST_AUTO_TEST_CASE(operating_pow_floor_disabled_zero)
{
    auto params = LwmaParamsWithOperatingFloor();
    params.operating_pow_floor_bits = 0; // disable
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1c00ffffU;
    const int n = 120;
    chain.clear();
    int64_t t = 1'700'000'000;
    for (int i = 0; i < n; ++i) {
        chain.emplace_back();
        CBlockIndex& bi = chain.back();
        bi.nHeight = static_cast<int>(params.nEarlyDifficultyGuardHeight) + i;
        bi.nTime = static_cast<unsigned int>(t);
        bi.nBits = starting_nbits;
        if (i > 0) chain.back().pprev = &chain[i - 1];
        t += params.nPowTargetSpacing * 10;
    }
    const CBlockIndex* tip = &chain.back();
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);
    arith_uint256 t_new, t_pl;
    t_new.SetCompact(new_nbits);
    t_pl = UintToArith256(params.powLimit);
    BOOST_CHECK(t_new <= t_pl);
}

/* T10 (M-13): mis-configured operating_pow_floor_bits that decodes
 * wider than powLimit must be ignored (defense-in-depth runtime guard). */
BOOST_AUTO_TEST_CASE(operating_pow_floor_wider_than_powlimit_ignored)
{
    auto params = LwmaParamsWithOperatingFloor();
    // 0x207fffff = regtest's wide-open floor (target ~ 2^238); much wider
    // than this params instance's powLimit (~ 2^224).  Runtime guard in
    // CalculateLwma3Target should ignore this bogus floor and fall back
    // to powLimit clamping.
    params.operating_pow_floor_bits = 0x207fffffU;
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1d00ffffU;
    const int n = 120;
    chain.clear();
    int64_t t = 1'700'000'000;
    for (int i = 0; i < n; ++i) {
        chain.emplace_back();
        CBlockIndex& bi = chain.back();
        bi.nHeight = static_cast<int>(params.nEarlyDifficultyGuardHeight) + i;
        bi.nTime = static_cast<unsigned int>(t);
        bi.nBits = starting_nbits;
        if (i > 0) chain.back().pprev = &chain[i - 1];
        t += params.nPowTargetSpacing * 10;
    }
    const CBlockIndex* tip = &chain.back();
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);
    arith_uint256 t_new, t_pl;
    t_new.SetCompact(new_nbits);
    t_pl = UintToArith256(params.powLimit);
    // Result must be at most powLimit, not the absurdly-wide bogus floor.
    BOOST_CHECK(t_new <= t_pl);
}

/* T6: clamping on extreme negative solve times.  A reversed-timestamp
 * window should not be allowed to crater the target. */
BOOST_AUTO_TEST_CASE(lwma3_negative_solve_time_clamp)
{
    const auto params = LwmaParams();
    std::deque<CBlockIndex> chain;
    const uint32_t starting_nbits = 0x1d00ffffU;

    // 120 blocks all with the same timestamp -> each solve_time becomes
    // 0 (or negative for blocks after the first); the clamp+min-weighted-sum
    // guard prevents target from going to zero.
    chain.clear();
    int64_t t = 1'700'000'000;
    for (int i = 0; i < 120; ++i) {
        chain.emplace_back();
        CBlockIndex& bi = chain.back();
        bi.nHeight = i;
        bi.nTime = static_cast<unsigned int>(t);
        bi.nBits = starting_nbits;
        if (i > 0) chain.back().pprev = &chain[i - 1];
    }
    const CBlockIndex* tip = &chain.back();
    const uint32_t new_nbits = pow::CalculateLwma3Target(tip, params);
    // Target must not collapse to zero or to a numerical glitch.
    arith_uint256 t_new;
    t_new.SetCompact(new_nbits);
    BOOST_CHECK(t_new > 0);
    // With the min-weighted-sum floor, target should drop significantly
    // (high effective hashrate) but not vanish.
    const double ratio = TargetRatio(new_nbits, starting_nbits);
    BOOST_CHECK_MESSAGE(ratio > 0.0 && ratio < 0.5,
        "negative solve times clamp: expected target << 0.5x, got ratio=" << ratio);
}

BOOST_AUTO_TEST_SUITE_END()
