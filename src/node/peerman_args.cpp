// Copyright (c) 2023-present The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit.

#include <node/peerman_args.h>

#include <common/args.h>
#include <net_processing.h>

#include <algorithm>
#include <limits>

namespace node {

void ApplyArgsManOptions(const ArgsManager& argsman, PeerManager::Options& options)
{
    if (auto value{argsman.GetBoolArg("-txreconciliation")}) options.reconcile_txs = *value;

    if (auto value{argsman.GetIntArg("-blockreconstructionextratxn")}) {
        options.max_extra_txs = uint32_t((std::clamp<int64_t>(*value, 0, std::numeric_limits<uint32_t>::max())));
    }

    if (auto value{argsman.GetBoolArg("-capturemessages")}) options.capture_messages = *value;

    if (auto value{argsman.GetBoolArg("-blocksonly")}) options.ignore_incoming_txs = *value;

    // b3chain M-8 (V-10): paranoid headers-sync mode.  OFF by default.
    if (auto value{argsman.GetBoolArg("-paranoid-headers-sync")}) {
        options.paranoid_headers_sync = *value;
    }
    if (auto value{argsman.GetIntArg("-paranoid-headers-quorum")}) {
        // Clamp to [1, 16]; 1 is "off by another name", 16 is a sanity ceiling.
        options.paranoid_headers_quorum = static_cast<uint32_t>(
            std::clamp<int64_t>(*value, 1, 16));
    }
}

} // namespace node

