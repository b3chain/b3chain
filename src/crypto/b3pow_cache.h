// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.
//
// LRU cache for B3PoW scratchpads keyed by `prev_block_hash`.
//
// Rationale (Finding 4, mitigation D2):
//   The 1 MB scratchpad is a function of `prev_block_hash` only -- the
//   header bytes don't enter until the mixing loop reads from it.  So a
//   miner mining many candidate nonces against the same parent, or a
//   verifier checking sibling headers off the same parent, pays the
//   ~5 ms pad-init cost only once.
//
// Threading:
//   shared_mutex.  Reads (the common case) acquire a shared lock.  On
//   miss we upgrade to a unique lock and insert.  The cache hands out
//   `PadPtr` (shared_ptr<const Pad>) so callers can keep using a pad
//   that's since been evicted -- the heap allocation outlives the cache
//   entry that holds it.

#ifndef BITCOIN_CRYPTO_B3POW_CACHE_H
#define BITCOIN_CRYPTO_B3POW_CACHE_H

#include <crypto/b3pow_scratch.h>
#include <uint256.h>
#include <util/hasher.h>

#include <cstddef>
#include <list>
#include <shared_mutex>
#include <unordered_map>

namespace b3pow {

class Cache
{
public:
    /** Default number of pinned slots reserved for the active-tip pad
     *  and its 2 ancestors (M-6, F-5 fix). */
    static constexpr size_t kDefaultPinnedCapacity = 3;

    explicit Cache(size_t depth,
                   size_t pinned_capacity = kDefaultPinnedCapacity);
    ~Cache() = default;

    Cache(const Cache&) = delete;
    Cache& operator=(const Cache&) = delete;

    /** Return a pad for `prev_block_hash`, building one if necessary.
     *
     * Thread-safe.  Reads (hits) acquire only a shared lock; misses
     * upgrade to unique for the insert + eviction.
     */
    PadPtr GetOrBuild(const uint256& prev_block_hash);

    /** Return a pad for `prev_block_hash` only if cached, else nullptr.
     * Useful for tests and for the fuzz harness. */
    PadPtr GetIfCached(const uint256& prev_block_hash) const;

    /** b3chain M-6 (F-5 fix): pin a `prev_block_hash`'s pad so it cannot
     *  be evicted by hostile peer churn.
     *
     *  Builds the pad if not yet cached.  If the pinned tier is at
     *  capacity, the oldest pinned entry is demoted to the LRU tier.
     *  Thread-safe.  Returns the pinned pad. */
    PadPtr Pin(const uint256& prev_block_hash);

    /** b3chain M-6: explicitly unpin a `prev_block_hash`.  The entry
     *  remains in the LRU tier and may be evicted normally.  No-op if
     *  not pinned.  Thread-safe. */
    void Unpin(const uint256& prev_block_hash);

    /** Evict everything.  For tests. */
    void Clear();

    size_t size() const;
    /** Total resident capacity (pinned + LRU). */
    size_t capacity() const { return m_depth; }
    /** Number of slots reserved for pinning. */
    size_t pinned_capacity() const { return m_pinned_capacity; }
    /** Current count of pinned entries.  For audits / tests. */
    size_t pinned_count() const;

private:
    using ListIt = std::list<uint256>::iterator;
    struct Entry {
        PadPtr pad;
        ListIt lru_it;
        bool   pinned{false};
    };

    const size_t m_depth;
    const size_t m_pinned_capacity;

    mutable std::shared_mutex m_mutex;
    // LRU ordering for non-pinned entries: front = most-recently-used.
    std::list<uint256> m_lru;
    // Pinned ordering (FIFO -- oldest pinned demoted on overflow).
    std::list<uint256> m_pinned;
    std::unordered_map<uint256, Entry, SaltedUint256Hasher> m_map;

    // Helpers, callable only under m_mutex held unique.
    void EvictForInsert();
};

} // namespace b3pow

#endif // BITCOIN_CRYPTO_B3POW_CACHE_H
