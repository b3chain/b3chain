// Pristine B3PoW-Scratch v1.1 scratchpad cache, keyed on the 32-byte
// little-endian parent block hash (the same bytes that appear inside
// the header at offset 4..36).
//
// `b3powScratch()` mutates the pad it's handed, so the cache stores
// the freshly-initialised "template" pad and `getFresh()` returns a
// brand-new copy on every call. The expensive part of init is the
// 16 384 BLAKE3-XOF rounds (~10 ms on a modern CPU); the 1 MiB
// `Uint8Array` copy is ~100 us and runs once per share. For the pool,
// where shares trickle in at a few per second per worker, the cache
// turns the per-share cost from "init + mix" into "copy + mix".

import { initScratchpad, SCRATCH_BYTES } from "./b3pow-scratch";

interface Entry {
    pad: Uint8Array; // pristine init, treated as read-only
    lastUsedMs: number;
}

export interface PadCacheStats {
    size: number;
    hits: number;
    misses: number;
    evictions: number;
}

export class PadCache {
    private readonly capacity: number;
    private readonly map: Map<string, Entry> = new Map();
    private hits = 0;
    private misses = 0;
    private evictions = 0;

    constructor(capacity: number = 8) {
        if (capacity < 1) throw new Error("capacity must be >= 1");
        this.capacity = capacity;
    }

    /** Return a fresh, mutable scratchpad for `prevBlockHashLE`. */
    getFresh(prevBlockHashLE: Uint8Array): Uint8Array {
        if (prevBlockHashLE.length !== 32) {
            throw new Error("prevBlockHashLE must be 32 bytes");
        }
        const key = bytesKey(prevBlockHashLE);
        const now = Date.now();
        let entry = this.map.get(key);
        if (entry === undefined) {
            this.misses += 1;
            const pad = initScratchpad(prevBlockHashLE);
            entry = { pad, lastUsedMs: now };
            this.map.set(key, entry);
            this.evictOldest();
        } else {
            this.hits += 1;
            entry.lastUsedMs = now;
            // Move-to-end for LRU recency.
            this.map.delete(key);
            this.map.set(key, entry);
        }
        // Return a copy; b3powScratch mutates.
        const copy = new Uint8Array(SCRATCH_BYTES);
        copy.set(entry.pad, 0);
        return copy;
    }

    private evictOldest(): void {
        while (this.map.size > this.capacity) {
            const oldestKey = this.map.keys().next().value as string | undefined;
            if (oldestKey === undefined) return;
            this.map.delete(oldestKey);
            this.evictions += 1;
        }
    }

    /** Drop all cached pads (e.g. on reorg). */
    clear(): void {
        this.map.clear();
    }

    stats(): PadCacheStats {
        return {
            size: this.map.size,
            hits: this.hits,
            misses: this.misses,
            evictions: this.evictions,
        };
    }
}

function bytesKey(b: Uint8Array): string {
    // Hex is the cheapest stable, hash-comparable key form for a
    // 32-byte buffer in JS. Map<Uint8Array,...> uses identity equality,
    // not value equality, so a string key is mandatory here.
    let s = "";
    for (let i = 0; i < b.length; i++) {
        const v = b[i];
        s += (v < 16 ? "0" : "") + v.toString(16);
    }
    return s;
}
