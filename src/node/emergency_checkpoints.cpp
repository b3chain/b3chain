// Copyright (c) 2026 The b3chain developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.

#include <node/emergency_checkpoints.h>

#include <logging.h>
#include <uint256.h>
#include <univalue.h>
#include <util/fs.h>
#include <util/strencodings.h>

#include <fstream>
#include <sstream>

namespace node {

bool EmergencyCheckpoints::LoadFromFile(const std::string& path, std::string& err)
{
    err.clear();
    m_by_height.clear();

    std::ifstream in(path);
    if (!in) {
        err = "cannot open file";
        return false;
    }
    std::stringstream ss;
    ss << in.rdbuf();
    const std::string body = ss.str();

    UniValue root;
    if (!root.read(body)) {
        err = "JSON parse failure";
        return false;
    }
    if (!root.isObject()) {
        err = "top-level JSON must be an object";
        return false;
    }

    // schema is informational; we accept anything that parses.
    const UniValue& list = root["checkpoints"];
    if (!list.isArray()) {
        err = "missing \"checkpoints\" array";
        return false;
    }

    for (size_t i = 0; i < list.size(); ++i) {
        const UniValue& entry = list[i];
        if (!entry.isObject()) {
            err = "checkpoint entry " + std::to_string(i) + " is not an object";
            m_by_height.clear();
            return false;
        }
        const UniValue& h_v = entry["height"];
        const UniValue& k_v = entry["hash"];
        if (!h_v.isNum() || !k_v.isStr()) {
            err = "checkpoint entry " + std::to_string(i) +
                  " missing integer \"height\" or string \"hash\"";
            m_by_height.clear();
            return false;
        }
        const int height = h_v.getInt<int>();
        if (height < 0) {
            err = "checkpoint entry " + std::to_string(i) + " has negative height";
            m_by_height.clear();
            return false;
        }
        const std::string hash_hex = k_v.get_str();
        if (hash_hex.size() != 64 || !IsHex(hash_hex)) {
            err = "checkpoint entry " + std::to_string(i) +
                  " hash is not a 64-char lowercase hex string";
            m_by_height.clear();
            return false;
        }
        const auto parsed = uint256::FromHex(hash_hex);
        if (!parsed) {
            err = "checkpoint entry " + std::to_string(i) +
                  " hash is not a valid 64-char hex uint256";
            m_by_height.clear();
            return false;
        }
        auto [it, inserted] = m_by_height.emplace(height, *parsed);
        if (!inserted && it->second != *parsed) {
            err = "duplicate height " + std::to_string(height) +
                  " with conflicting hash";
            m_by_height.clear();
            return false;
        }
    }

    LogInfo("EmergencyCheckpoints: loaded %u entries from %s\n",
            static_cast<unsigned>(m_by_height.size()), path);
    return true;
}

void EmergencyCheckpoints::Clear()
{
    m_by_height.clear();
}

std::optional<uint256> EmergencyCheckpoints::AtHeight(int height) const
{
    auto it = m_by_height.find(height);
    if (it == m_by_height.end()) return std::nullopt;
    return it->second;
}

bool EmergencyCheckpoints::Matches(int height, const uint256& hash) const
{
    auto it = m_by_height.find(height);
    if (it == m_by_height.end()) return true;
    return it->second == hash;
}

} // namespace node
