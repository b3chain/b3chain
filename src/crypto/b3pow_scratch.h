// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.
//
// B3PoW-Scratch v1.1 -- memory-hard BLAKE3 variant.
//
// The authoritative spec for this algorithm lives at
//   contrib/miner/b3miner-rtl/SPEC.md
// and the byte-for-byte Python reference at
//   contrib/miner/b3miner-rtl/ref/b3pow_ref.py
//
// This file is the C++ port; consensus integrity requires that every
// input header byte-for-byte maps to the same 32-byte pow_hash that
// b3pow_ref.py emits.  The CI gate is contrib/miner/b3miner-rtl/ref/
// vectors/consensus_vectors.json (regenerated from gen_vectors.py)
// consumed by src/test/b3pow_scratch_tests.cpp.

#ifndef BITCOIN_CRYPTO_B3POW_SCRATCH_H
#define BITCOIN_CRYPTO_B3POW_SCRATCH_H

#include <uint256.h>

#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>

namespace b3pow {

// ----------------------------------------------------------------------------
// Locked constants (mirror of ref/b3pow_ref.py and rtl/params_pkg.sv).
// Any change here is a consensus break.
// ----------------------------------------------------------------------------
inline constexpr uint32_t SPEC_VERSION = 0x00010101; // 1.1.1 (F-1: ITER_MUL[7] distinct)

inline constexpr size_t HEADER_BYTES = 80;
inline constexpr size_t SCRATCH_BYTES = 1048576;     // 1 MB
inline constexpr size_t LANES = 8;
inline constexpr size_t LANE_BYTES = SCRATCH_BYTES / LANES;
inline constexpr size_t BLOCK_BYTES = 64;
inline constexpr size_t LANE_BLOCKS = LANE_BYTES / BLOCK_BYTES;
inline constexpr size_t SCRATCH_BLOCKS = SCRATCH_BYTES / BLOCK_BYTES;
inline constexpr unsigned ITERATIONS = 2048;
inline constexpr unsigned INNER_ROUNDS = 2;
inline constexpr unsigned ADDR_MASK = LANE_BLOCKS - 1; // 2047

// ----------------------------------------------------------------------------
// Public types
// ----------------------------------------------------------------------------

/** 1 MB scratchpad keyed by `prev_block_hash`.
 *
 * Heap-allocated (1 MB) and shared by `shared_ptr` so the B3PoWCache can
 * hand out lock-free read-only references that outlive the cache itself
 * (the cache only owns the strong reference; ongoing verifications hold
 * weak observers).
 */
struct Pad {
    std::array<uint8_t, SCRATCH_BYTES> bytes;
};
using PadPtr = std::shared_ptr<const Pad>;

// ----------------------------------------------------------------------------
// Core API
// ----------------------------------------------------------------------------

/** Build a fresh scratchpad from `prev_block_hash`.
 *
 * Cost is ~5 ms on a modern x86_64 core (16384 BLAKE3-XOF(48B->64B)
 * calls).  The result is immutable after construction; the cache holds
 * it `const`.
 */
PadPtr InitScratchpad(const uint256& prev_block_hash);

/** Run B3PoW-Scratch v1.1 over `header` (80 bytes, little-endian on the
 * wire) using `prev_block_hash` to derive the scratchpad.
 *
 * Args:
 *   header_bytes  -- exactly HEADER_BYTES (80) of header data.
 *   prev_block_hash -- 32-byte SHA-256d block hash of the parent.
 *   pad           -- pre-initialised pad (must have been built from
 *                    `prev_block_hash`).  Caller is responsible for the
 *                    binding; we do NOT re-verify it.  Use
 *                    `InitScratchpad(prev_block_hash)` if you don't
 *                    have a cached one.
 *   budget        -- wall-clock budget.  If 0, no enforcement.
 *   out_budget_exceeded -- written to `true` iff we aborted because of
 *                          `budget`; otherwise `false`.  Always written.
 *
 * Returns the 32-byte pow_hash on success, or std::nullopt if we aborted
 * due to budget.  All other failures (size, alignment) are CHECK-able
 * preconditions and crash the node -- that's intentional, those inputs
 * cannot originate from the network.
 */
std::optional<uint256> Hash(std::span<const uint8_t> header_bytes,
                            const uint256& prev_block_hash,
                            const PadPtr& pad,
                            std::chrono::milliseconds budget,
                            bool& out_budget_exceeded);

/** Convenience wrapper for callers that don't have a pad cached.
 * Allocates and discards a fresh pad; for repeated calls against the
 * same `prev_block_hash`, build the pad once and reuse it. */
std::optional<uint256> Hash(std::span<const uint8_t> header_bytes,
                            const uint256& prev_block_hash,
                            std::chrono::milliseconds budget,
                            bool& out_budget_exceeded);

} // namespace b3pow

#endif // BITCOIN_CRYPTO_B3POW_SCRATCH_H
