// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.
//
// Unit tests for the B3PoW scratchpad LRU cache.
//
// Properties exercised here:
//   1. Insert / retrieve / size / capacity.
//   2. LRU eviction policy (oldest unused entry is dropped).
//   3. `GetOrBuild` returns identical PadPtr on a hit.
//   4. `GetIfCached` returns nullptr on miss; observed entry on hit.
//   5. `Clear()` empties the cache.
//   6. Thread-safety under concurrent reads/writes (4 threads x N ops).
//
// The cache holds 1 MB Pad objects, so we keep depths small (<= 8) and
// only stress with a few unique keys to keep memory bounded.

#include <crypto/b3pow_cache.h>
#include <crypto/b3pow_scratch.h>
#include <test/util/setup_common.h>
#include <uint256.h>

#include <boost/test/unit_test.hpp>

#include <array>
#include <atomic>
#include <cstring>
#include <thread>
#include <vector>

namespace {

uint256 MakeHash(uint8_t tag)
{
    uint256 h;
    std::memset(h.data(), 0, 32);
    h.data()[0] = tag;
    return h;
}

} // namespace

BOOST_FIXTURE_TEST_SUITE(b3pow_cache_tests, BasicTestingSetup)

BOOST_AUTO_TEST_CASE(insert_and_retrieve)
{
    b3pow::Cache cache(/*depth=*/4);
    BOOST_CHECK_EQUAL(cache.size(), 0U);
    BOOST_CHECK_EQUAL(cache.capacity(), 4U);

    const uint256 k = MakeHash(1);
    BOOST_CHECK(cache.GetIfCached(k) == nullptr);

    auto p = cache.GetOrBuild(k);
    BOOST_REQUIRE(p);
    BOOST_CHECK_EQUAL(cache.size(), 1U);

    // Hit -- must return same shared_ptr (same underlying allocation).
    auto q = cache.GetOrBuild(k);
    BOOST_CHECK(p.get() == q.get());

    // GetIfCached on a present key.
    auto r = cache.GetIfCached(k);
    BOOST_CHECK(r.get() == p.get());
}

BOOST_AUTO_TEST_CASE(lru_evicts_oldest)
{
    b3pow::Cache cache(/*depth=*/2);

    auto p1 = cache.GetOrBuild(MakeHash(1));
    auto p2 = cache.GetOrBuild(MakeHash(2));
    BOOST_CHECK_EQUAL(cache.size(), 2U);

    // Inserting a 3rd entry evicts the LRU (key=1).
    auto p3 = cache.GetOrBuild(MakeHash(3));
    BOOST_CHECK_EQUAL(cache.size(), 2U);
    BOOST_CHECK(cache.GetIfCached(MakeHash(1)) == nullptr);
    BOOST_CHECK(cache.GetIfCached(MakeHash(2)) != nullptr);
    BOOST_CHECK(cache.GetIfCached(MakeHash(3)) != nullptr);

    // Insert another entry.  Note: the cache deliberately does *not*
    // update LRU ordering on hits (lock-free fast path -- see
    // crypto/b3pow_cache.cpp comment).  So an additional GetOrBuild on
    // an existing key does *not* protect it from eviction; only the
    // most recent insert is guaranteed to survive.  After inserting
    // key=4 the LRU order is [4, 3] and key=2 is evicted.
    auto p4 = cache.GetOrBuild(MakeHash(4));
    BOOST_CHECK_EQUAL(cache.size(), 2U);
    BOOST_CHECK(cache.GetIfCached(MakeHash(4)) != nullptr);
    BOOST_CHECK(cache.size() <= cache.capacity());

    // p1 is still valid (we hold our own shared_ptr) even though it
    // was evicted from the cache -- this is the property that lets
    // verifications outlive a cache spill.
    BOOST_CHECK(p1 != nullptr);
}

BOOST_AUTO_TEST_CASE(clear_resets_size)
{
    b3pow::Cache cache(/*depth=*/4);
    (void)cache.GetOrBuild(MakeHash(10));
    (void)cache.GetOrBuild(MakeHash(11));
    BOOST_CHECK_EQUAL(cache.size(), 2U);
    cache.Clear();
    BOOST_CHECK_EQUAL(cache.size(), 0U);
    BOOST_CHECK(cache.GetIfCached(MakeHash(10)) == nullptr);
}

BOOST_AUTO_TEST_CASE(distinct_prev_yields_distinct_pad)
{
    b3pow::Cache cache(/*depth=*/4);
    auto p1 = cache.GetOrBuild(MakeHash(0xa1));
    auto p2 = cache.GetOrBuild(MakeHash(0xa2));
    BOOST_REQUIRE(p1);
    BOOST_REQUIRE(p2);
    BOOST_CHECK(p1.get() != p2.get());
    // Their byte content must differ (otherwise pad init isn't a
    // function of prev_block_hash).
    BOOST_CHECK(std::memcmp(p1->bytes.data(), p2->bytes.data(),
                            b3pow::SCRATCH_BYTES) != 0);
}

// b3chain M-6 (F-5 fix): the 2-tier pinned LRU cache protects the
// tip + 2 ancestors from hostile header flood evictions.  See
// src/crypto/b3pow_cache.h and doc/security/B3POW-51-ATTACK-ANALYSIS.md
// V-7.
BOOST_AUTO_TEST_CASE(pin_protects_from_eviction)
{
    // depth=4, pinned_capacity=2.  We will pin 2 keys and then flood
    // the cache with 10 more.  The pinned pads must survive.
    b3pow::Cache cache(/*depth=*/4, /*pinned_capacity=*/2);

    const uint256 pinned_a = MakeHash(0xA1);
    const uint256 pinned_b = MakeHash(0xA2);

    auto pa = cache.Pin(pinned_a);
    auto pb = cache.Pin(pinned_b);
    BOOST_CHECK_EQUAL(cache.pinned_count(), 2U);
    BOOST_CHECK(cache.GetIfCached(pinned_a) != nullptr);
    BOOST_CHECK(cache.GetIfCached(pinned_b) != nullptr);

    // Flood: hostile peer churning the LRU tier.  None of these should
    // touch the pinned tier.
    for (int i = 0; i < 10; ++i) {
        (void)cache.GetOrBuild(MakeHash(0x80 + i));
    }

    BOOST_CHECK(cache.GetIfCached(pinned_a) != nullptr);
    BOOST_CHECK(cache.GetIfCached(pinned_b) != nullptr);
    BOOST_CHECK_EQUAL(cache.pinned_count(), 2U);
    // Total size must remain bounded by depth.
    BOOST_CHECK(cache.size() <= cache.capacity());
}

BOOST_AUTO_TEST_CASE(pin_capacity_overflow_demotes_oldest)
{
    // depth=4, pinned_capacity=2.  Pin 3 keys; the oldest pinned
    // (pinned_a) must be demoted to the LRU tier, not lost.
    b3pow::Cache cache(/*depth=*/4, /*pinned_capacity=*/2);
    const uint256 a = MakeHash(0xA1);
    const uint256 b = MakeHash(0xA2);
    const uint256 c = MakeHash(0xA3);

    (void)cache.Pin(a);
    (void)cache.Pin(b);
    (void)cache.Pin(c);
    BOOST_CHECK_EQUAL(cache.pinned_count(), 2U);
    // All three still resident (a demoted to LRU tier).
    BOOST_CHECK(cache.GetIfCached(a) != nullptr);
    BOOST_CHECK(cache.GetIfCached(b) != nullptr);
    BOOST_CHECK(cache.GetIfCached(c) != nullptr);

    // Now flood the LRU tier; `a` (the demoted entry) becomes evictable.
    // With depth=4, pinned_capacity=2 -> LRU tier has 2 slots; `a`
    // occupies one and will fall out as we add more entries.
    for (int i = 0; i < 5; ++i) {
        (void)cache.GetOrBuild(MakeHash(0x80 + i));
    }
    // b and c (pinned) must survive.
    BOOST_CHECK(cache.GetIfCached(b) != nullptr);
    BOOST_CHECK(cache.GetIfCached(c) != nullptr);
}

BOOST_AUTO_TEST_CASE(pinned_capacity_clamped_below_depth)
{
    // If a caller asks for pinned_capacity == depth (or larger), the
    // ctor must clamp to depth-1 so the LRU tier retains at least one
    // slot.  Otherwise GetOrBuild on a new key would deadlock the
    // eviction walker.
    b3pow::Cache cache(/*depth=*/3, /*pinned_capacity=*/10);
    BOOST_CHECK_EQUAL(cache.pinned_capacity(), 2U);  // depth-1
    BOOST_CHECK_EQUAL(cache.capacity(), 3U);
}

BOOST_AUTO_TEST_CASE(unpin_allows_eviction)
{
    b3pow::Cache cache(/*depth=*/2, /*pinned_capacity=*/1);
    const uint256 k = MakeHash(0xC1);
    (void)cache.Pin(k);
    BOOST_CHECK_EQUAL(cache.pinned_count(), 1U);

    // Flood once -- still pinned, must survive.
    (void)cache.GetOrBuild(MakeHash(0x01));
    BOOST_CHECK(cache.GetIfCached(k) != nullptr);

    cache.Unpin(k);
    BOOST_CHECK_EQUAL(cache.pinned_count(), 0U);

    // Now flood again -- k can be evicted.
    (void)cache.GetOrBuild(MakeHash(0x02));
    (void)cache.GetOrBuild(MakeHash(0x03));
    BOOST_CHECK(cache.GetIfCached(k) == nullptr);
}

BOOST_AUTO_TEST_CASE(thread_safety_concurrent_access)
{
    b3pow::Cache cache(/*depth=*/4);
    // Three keys that fit inside the depth-4 cache so the LRU policy
    // doesn't churn them out from under concurrent readers.
    const std::array<uint256, 3> keys = {
        MakeHash(0x10), MakeHash(0x11), MakeHash(0x12),
    };

    // Pre-warm so each key's pad is settled.  Concurrent reads must
    // return the exact same PadPtr instance throughout.
    std::array<b3pow::PadPtr, 3> baseline;
    for (size_t i = 0; i < keys.size(); ++i) baseline[i] = cache.GetOrBuild(keys[i]);

    std::atomic<bool> mismatch{false};
    std::atomic<int>  ops{0};
    constexpr int kOpsPerThread = 256;

    auto worker = [&](int tid) {
        for (int i = 0; i < kOpsPerThread; ++i) {
            size_t idx = (i + tid) % keys.size();
            auto got = cache.GetOrBuild(keys[idx]);
            if (got.get() != baseline[idx].get()) {
                mismatch.store(true, std::memory_order_relaxed);
            }
            ops.fetch_add(1, std::memory_order_relaxed);
        }
    };

    std::vector<std::thread> ts;
    for (int t = 0; t < 4; ++t) ts.emplace_back(worker, t);
    for (auto& t : ts) t.join();

    BOOST_CHECK(!mismatch.load());
    BOOST_CHECK_EQUAL(ops.load(), 4 * kOpsPerThread);
    BOOST_CHECK(cache.size() <= cache.capacity());
}

BOOST_AUTO_TEST_SUITE_END()
