// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.

#include <crypto/b3pow_cache.h>

#include <crypto/b3pow_scratch.h>
#include <util/check.h>

#include <mutex>
#include <shared_mutex>

namespace b3pow {

Cache::Cache(size_t depth, size_t pinned_capacity)
    : m_depth(depth > 0 ? depth : 1),
      m_pinned_capacity(std::min(pinned_capacity, m_depth - 1))
{
    // Invariant: m_pinned_capacity < m_depth so the LRU tier always
    // retains at least one slot.  If a caller passes a too-large
    // pinned_capacity we clamp; tests in b3pow_cache_tests.cpp verify.
}

void Cache::EvictForInsert()
{
    // Walk the LRU back-to-front, evicting the oldest non-pinned entry.
    // Pinned entries (live in m_pinned) are by construction not in m_lru.
    while (m_map.size() >= m_depth) {
        Assume(!m_lru.empty());
        const uint256 victim = m_lru.back();
        m_lru.pop_back();
        m_map.erase(victim);
    }
}

PadPtr Cache::GetOrBuild(const uint256& prev_block_hash)
{
    // Fast path: shared lock + map lookup.
    {
        std::shared_lock<std::shared_mutex> rlock(m_mutex);
        auto it = m_map.find(prev_block_hash);
        if (it != m_map.end()) {
            // Note: we hold only a shared lock here, so we can't move the
            // entry to the front of the LRU list without taking unique
            // lock.  We accept slightly-stale LRU ordering in exchange
            // for lock-free hits.  This is the same trade-off the SegWit
            // signature cache makes (see CSignatureCache).
            return it->second.pad;
        }
    }

    // Miss: build the pad outside the lock to keep the unique-lock
    // critical section as short as possible.
    PadPtr fresh = InitScratchpad(prev_block_hash);

    // Slow path: unique lock to insert/evict.
    std::unique_lock<std::shared_mutex> wlock(m_mutex);

    // Race: another thread may have built and inserted the same key
    // between our shared-lock probe and this point.  Take the existing
    // entry (semantically equivalent; the algorithm is deterministic).
    auto it = m_map.find(prev_block_hash);
    if (it != m_map.end()) {
        // Move to front of LRU iff this entry lives in the LRU tier.
        if (!it->second.pinned) {
            m_lru.splice(m_lru.begin(), m_lru, it->second.lru_it);
        }
        return it->second.pad;
    }

    EvictForInsert();

    m_lru.push_front(prev_block_hash);
    Entry entry{fresh, m_lru.begin(), /*pinned=*/false};
    m_map.emplace(prev_block_hash, entry);
    return fresh;
}

PadPtr Cache::Pin(const uint256& prev_block_hash)
{
    // Step 1: ensure a pad exists (build under shared/unique lock as
    // needed).  GetOrBuild handles its own locking and is idempotent.
    PadPtr pad = GetOrBuild(prev_block_hash);

    // Step 2: promote to pinned tier under unique lock.
    std::unique_lock<std::shared_mutex> wlock(m_mutex);

    auto it = m_map.find(prev_block_hash);
    Assume(it != m_map.end());  // we just built it

    if (it->second.pinned) {
        // Refresh pin-recency (move to front of m_pinned).
        m_pinned.splice(m_pinned.begin(), m_pinned, it->second.lru_it);
        return pad;
    }

    // Move the entry from LRU tier to pinned tier.  Erase the entry
    // from m_lru, push onto m_pinned front, update iterator.
    m_lru.erase(it->second.lru_it);
    m_pinned.push_front(prev_block_hash);
    it->second.lru_it = m_pinned.begin();
    it->second.pinned = true;

    // If the pinned tier overflows, demote the oldest pinned entry.
    while (m_pinned.size() > m_pinned_capacity) {
        const uint256 demote_key = m_pinned.back();
        m_pinned.pop_back();
        auto dit = m_map.find(demote_key);
        Assume(dit != m_map.end());
        // Move it back into the LRU tier (at front -- it WAS recently
        // pinned, so semantically it's a hot entry).
        m_lru.push_front(demote_key);
        dit->second.lru_it = m_lru.begin();
        dit->second.pinned = false;
    }

    return pad;
}

void Cache::Unpin(const uint256& prev_block_hash)
{
    std::unique_lock<std::shared_mutex> wlock(m_mutex);
    auto it = m_map.find(prev_block_hash);
    if (it == m_map.end() || !it->second.pinned) return;

    m_pinned.erase(it->second.lru_it);
    m_lru.push_front(prev_block_hash);
    it->second.lru_it = m_lru.begin();
    it->second.pinned = false;

    // Newly-unpinned + cache near capacity may need an eviction.
    EvictForInsert();
}

PadPtr Cache::GetIfCached(const uint256& prev_block_hash) const
{
    std::shared_lock<std::shared_mutex> rlock(m_mutex);
    auto it = m_map.find(prev_block_hash);
    if (it == m_map.end()) return nullptr;
    return it->second.pad;
}

void Cache::Clear()
{
    std::unique_lock<std::shared_mutex> wlock(m_mutex);
    m_map.clear();
    m_lru.clear();
    m_pinned.clear();
}

size_t Cache::size() const
{
    std::shared_lock<std::shared_mutex> rlock(m_mutex);
    return m_map.size();
}

size_t Cache::pinned_count() const
{
    std::shared_lock<std::shared_mutex> rlock(m_mutex);
    return m_pinned.size();
}

} // namespace b3pow
