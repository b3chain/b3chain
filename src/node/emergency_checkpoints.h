// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.
//
// b3chain M-9 / V-5: optional emergency checkpoint stub.
//
// The binary ships with ZERO checkpoints.  The list is loaded only
// when the operator passes `-assumevalidcheckpoints=<path>` and the
// referenced JSON file exists.  This is intended as a break-glass
// response to an in-progress 51%-attack: an exchange / SPV-provider
// coordination call publishes a (height, hash) pair, operators load
// it via this flag, and any chain proposing a different block at
// that height is rejected.
//
// Format (JSON, UTF-8):
//   {
//     "schema": 1,
//     "checkpoints": [
//       {"height": 12345,  "hash": "abcd...ef"},
//       {"height": 67890,  "hash": "1234...56"}
//     ]
//   }
//
// Semantics:
//   * In the absence of any loaded checkpoints, this module is a
//     no-op (Empty() returns true; all queries return std::nullopt).
//   * Once loaded, a block at height H whose hash does NOT match
//     the checkpointed hash at that exact height is rejected via
//     BlockValidationResult::BLOCK_CHECKPOINT, which net_processing
//     routes to Misbehaving("checkpoint-mismatch").

#ifndef BITCOIN_NODE_EMERGENCY_CHECKPOINTS_H
#define BITCOIN_NODE_EMERGENCY_CHECKPOINTS_H

#include <uint256.h>

#include <cstdint>
#include <map>
#include <optional>
#include <string>

namespace node {

class EmergencyCheckpoints
{
public:
    EmergencyCheckpoints() = default;

    /** Load the JSON file at `path`.  Returns true on success; on
     *  failure writes a human-readable diagnostic to `err` and the
     *  object remains empty.  Idempotent: a successful load
     *  overrides any previous load. */
    bool LoadFromFile(const std::string& path, std::string& err);

    /** Clear all loaded checkpoints. */
    void Clear();

    /** Is the set empty?  True when no `-assumevalidcheckpoints=`
     *  flag was supplied, or the file was empty. */
    bool Empty() const { return m_by_height.empty(); }
    size_t size() const { return m_by_height.size(); }

    /** Return the checkpoint hash for `height`, or std::nullopt if
     *  no checkpoint is registered at that height. */
    std::optional<uint256> AtHeight(int height) const;

    /** Verify a (height, hash) pair against the loaded set.
     *  Returns true on match OR no-checkpoint-at-height.  Returns
     *  false only when a checkpoint exists at `height` and `hash`
     *  differs. */
    bool Matches(int height, const uint256& hash) const;

private:
    std::map<int, uint256> m_by_height;
};

} // namespace node

#endif // BITCOIN_NODE_EMERGENCY_CHECKPOINTS_H
