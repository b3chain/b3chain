// Copyright (c) 2011-2022 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <test/data/key_io_invalid.json.h>
#include <test/data/key_io_valid.json.h>

#include <addresstype.h>
#include <key.h>
#include <key_io.h>
#include <script/script.h>
#include <test/util/json.h>
#include <test/util/setup_common.h>
#include <univalue.h>
#include <util/chaintype.h>
#include <util/strencodings.h>

#include <boost/test/unit_test.hpp>

#include <algorithm>

BOOST_FIXTURE_TEST_SUITE(key_io_tests, BasicTestingSetup)

// Goal: check that parsed keys match test payload
BOOST_AUTO_TEST_CASE(key_io_valid_parse)
{
    UniValue tests = read_json(json_tests::key_io_valid);
    CKey privkey;
    CTxDestination destination;
    SelectParams(ChainType::MAIN);

    for (unsigned int idx = 0; idx < tests.size(); idx++) {
        const UniValue& test = tests[idx];
        std::string strTest = test.write();
        if (test.size() < 3) { // Allow for extra stuff (useful for comments)
            BOOST_ERROR("Bad test: " << strTest);
            continue;
        }
        std::string exp_base58string = test[0].get_str();
        const std::vector<std::byte> exp_payload{ParseHex<std::byte>(test[1].get_str())};
        const UniValue &metadata = test[2].get_obj();
        bool isPrivkey = metadata.find_value("isPrivkey").get_bool();
        SelectParams(ChainTypeFromString(metadata.find_value("chain").get_str()).value());
        bool try_case_flip = metadata.find_value("tryCaseFlip").isNull() ? false : metadata.find_value("tryCaseFlip").get_bool();
        if (isPrivkey) {
            bool isCompressed = metadata.find_value("isCompressed").get_bool();
            // Must be valid private key
            privkey = DecodeSecret(exp_base58string);
            BOOST_CHECK_MESSAGE(privkey.IsValid(), "!IsValid:" + strTest);
            BOOST_CHECK_MESSAGE(privkey.IsCompressed() == isCompressed, "compressed mismatch:" + strTest);
            BOOST_CHECK_MESSAGE(std::ranges::equal(privkey, exp_payload), "key mismatch:" + strTest);

            // Private key must be invalid public key
            destination = DecodeDestination(exp_base58string);
            BOOST_CHECK_MESSAGE(!IsValidDestination(destination), "IsValid privkey as pubkey:" + strTest);
        } else {
            // Must be valid public key
            destination = DecodeDestination(exp_base58string);
            CScript script = GetScriptForDestination(destination);
            BOOST_CHECK_MESSAGE(IsValidDestination(destination), "!IsValid:" + strTest);
            BOOST_CHECK_EQUAL(HexStr(script), HexStr(exp_payload));

            // Try flipped case version
            for (char& c : exp_base58string) {
                if (c >= 'a' && c <= 'z') {
                    c = (c - 'a') + 'A';
                } else if (c >= 'A' && c <= 'Z') {
                    c = (c - 'A') + 'a';
                }
            }
            destination = DecodeDestination(exp_base58string);
            BOOST_CHECK_MESSAGE(IsValidDestination(destination) == try_case_flip, "!IsValid case flipped:" + strTest);
            if (IsValidDestination(destination)) {
                script = GetScriptForDestination(destination);
                BOOST_CHECK_EQUAL(HexStr(script), HexStr(exp_payload));
            }

            // Public key must be invalid private key
            privkey = DecodeSecret(exp_base58string);
            BOOST_CHECK_MESSAGE(!privkey.IsValid(), "IsValid pubkey as privkey:" + strTest);
        }
    }
}

// Goal: check that generated keys match test vectors
BOOST_AUTO_TEST_CASE(key_io_valid_gen)
{
    UniValue tests = read_json(json_tests::key_io_valid);

    for (unsigned int idx = 0; idx < tests.size(); idx++) {
        const UniValue& test = tests[idx];
        std::string strTest = test.write();
        if (test.size() < 3) // Allow for extra stuff (useful for comments)
        {
            BOOST_ERROR("Bad test: " << strTest);
            continue;
        }
        std::string exp_base58string = test[0].get_str();
        std::vector<unsigned char> exp_payload = ParseHex(test[1].get_str());
        const UniValue &metadata = test[2].get_obj();
        bool isPrivkey = metadata.find_value("isPrivkey").get_bool();
        SelectParams(ChainTypeFromString(metadata.find_value("chain").get_str()).value());
        if (isPrivkey) {
            bool isCompressed = metadata.find_value("isCompressed").get_bool();
            CKey key;
            key.Set(exp_payload.begin(), exp_payload.end(), isCompressed);
            assert(key.IsValid());
            BOOST_CHECK_MESSAGE(EncodeSecret(key) == exp_base58string, "result mismatch: " + strTest);
        } else {
            CTxDestination dest;
            CScript exp_script(exp_payload.begin(), exp_payload.end());
            BOOST_CHECK(ExtractDestination(exp_script, dest));
            std::string address = EncodeDestination(dest);

            BOOST_CHECK_EQUAL(address, exp_base58string);
        }
    }

    SelectParams(ChainType::MAIN);
}


// Goal: check that base58 parsing code is robust against a variety of corrupted data
BOOST_AUTO_TEST_CASE(key_io_invalid)
{
    UniValue tests = read_json(json_tests::key_io_invalid); // Negative testcases
    CKey privkey;
    CTxDestination destination;

    for (unsigned int idx = 0; idx < tests.size(); idx++) {
        const UniValue& test = tests[idx];
        std::string strTest = test.write();
        if (test.size() < 1) // Allow for extra stuff (useful for comments)
        {
            BOOST_ERROR("Bad test: " << strTest);
            continue;
        }
        std::string exp_base58string = test[0].get_str();

        // must be invalid as public and as private key
        for (const auto& chain : {ChainType::MAIN, ChainType::TESTNET, ChainType::SIGNET, ChainType::REGTEST}) {
            SelectParams(chain);
            destination = DecodeDestination(exp_base58string);
            BOOST_CHECK_MESSAGE(!IsValidDestination(destination), "IsValid pubkey in mainnet:" + strTest);
            privkey = DecodeSecret(exp_base58string);
            BOOST_CHECK_MESSAGE(!privkey.IsValid(), "IsValid privkey in mainnet:" + strTest);
        }
    }
}

// b3chain: Verify address prefixes match expected values for all chain types
// and that cross-chain (Bitcoin) addresses are properly rejected.
BOOST_AUTO_TEST_CASE(b3chain_address_prefix_validation)
{
    // --- Mainnet ---
    SelectParams(ChainType::MAIN);
    {
        // Generate a known P2PKH destination and verify prefix
        CKey key;
        key.MakeNewKey(/*fCompressed=*/true);
        CPubKey pubkey = key.GetPubKey();
        CKeyID keyid = pubkey.GetID();
        CTxDestination dest_pkh = PKHash(keyid);
        std::string addr_pkh = EncodeDestination(dest_pkh);
        BOOST_CHECK_MESSAGE(addr_pkh[0] == 'B', "Mainnet P2PKH should start with 'B', got: " + addr_pkh);

        // Round-trip: encode -> decode -> re-encode must match
        CTxDestination decoded = DecodeDestination(addr_pkh);
        BOOST_CHECK(IsValidDestination(decoded));
        BOOST_CHECK_EQUAL(EncodeDestination(decoded), addr_pkh);

        // P2SH address prefix
        CScript redeemScript = GetScriptForDestination(dest_pkh);
        CTxDestination dest_sh = ScriptHash(redeemScript);
        std::string addr_sh = EncodeDestination(dest_sh);
        BOOST_CHECK_MESSAGE(addr_sh[0] == 'b', "Mainnet P2SH should start with 'b', got: " + addr_sh);

        // P2SH round-trip
        decoded = DecodeDestination(addr_sh);
        BOOST_CHECK(IsValidDestination(decoded));
        BOOST_CHECK_EQUAL(EncodeDestination(decoded), addr_sh);

        // Bech32 P2WPKH address prefix (b31q...)
        CTxDestination dest_wpkh = WitnessV0KeyHash(keyid);
        std::string addr_wpkh = EncodeDestination(dest_wpkh);
        BOOST_CHECK_MESSAGE(addr_wpkh.substr(0, 3) == "b31", "Mainnet P2WPKH should start with 'b31', got: " + addr_wpkh);
        BOOST_CHECK_MESSAGE(addr_wpkh[3] == 'q', "Mainnet P2WPKH should have 'q' separator, got: " + addr_wpkh);

        // Bech32 round-trip
        decoded = DecodeDestination(addr_wpkh);
        BOOST_CHECK(IsValidDestination(decoded));
        BOOST_CHECK_EQUAL(EncodeDestination(decoded), addr_wpkh);
    }

    // --- Testnet ---
    SelectParams(ChainType::TESTNET);
    {
        CKey key;
        key.MakeNewKey(/*fCompressed=*/true);
        CPubKey pubkey = key.GetPubKey();
        CKeyID keyid = pubkey.GetID();

        // Testnet Bech32 P2WPKH should start with "tb31q"
        CTxDestination dest_wpkh = WitnessV0KeyHash(keyid);
        std::string addr_wpkh = EncodeDestination(dest_wpkh);
        BOOST_CHECK_MESSAGE(addr_wpkh.substr(0, 4) == "tb31", "Testnet P2WPKH should start with 'tb31', got: " + addr_wpkh);
    }

    // --- Regtest ---
    SelectParams(ChainType::REGTEST);
    {
        CKey key;
        key.MakeNewKey(/*fCompressed=*/true);
        CPubKey pubkey = key.GetPubKey();
        CKeyID keyid = pubkey.GetID();

        // Regtest Bech32 P2WPKH should start with "b3rt1q"
        CTxDestination dest_wpkh = WitnessV0KeyHash(keyid);
        std::string addr_wpkh = EncodeDestination(dest_wpkh);
        BOOST_CHECK_MESSAGE(addr_wpkh.substr(0, 5) == "b3rt1", "Regtest P2WPKH should start with 'b3rt1', got: " + addr_wpkh);
    }

    // Restore default
    SelectParams(ChainType::MAIN);
}

// b3chain: Cross-chain rejection — Bitcoin addresses must be invalid on b3chain
BOOST_AUTO_TEST_CASE(b3chain_rejects_bitcoin_addresses)
{
    SelectParams(ChainType::MAIN);

    // Bitcoin mainnet P2PKH (starts with '1')
    CTxDestination dest = DecodeDestination("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa");
    BOOST_CHECK_MESSAGE(!IsValidDestination(dest), "Bitcoin P2PKH must be rejected on b3chain mainnet");

    // Bitcoin mainnet P2SH (starts with '3')
    dest = DecodeDestination("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy");
    BOOST_CHECK_MESSAGE(!IsValidDestination(dest), "Bitcoin P2SH must be rejected on b3chain mainnet");

    // Bitcoin mainnet Bech32 P2WPKH (starts with 'bc1q')
    dest = DecodeDestination("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq");
    BOOST_CHECK_MESSAGE(!IsValidDestination(dest), "Bitcoin Bech32 must be rejected on b3chain mainnet");

    // Bitcoin mainnet Bech32m P2TR (starts with 'bc1p')
    dest = DecodeDestination("bc1pmfr3p9j00pfxjh0zmgp99y8zftmd3s5pmedqhyptwy6lm87hf5sspknck9");
    BOOST_CHECK_MESSAGE(!IsValidDestination(dest), "Bitcoin Bech32m must be rejected on b3chain mainnet");

    // Litecoin mainnet P2PKH (starts with 'L')
    dest = DecodeDestination("LM2WMpR1Rp6j3Sa59cMXMs1SPzj9eXpGc1");
    BOOST_CHECK_MESSAGE(!IsValidDestination(dest), "Litecoin P2PKH must be rejected on b3chain mainnet");

    SelectParams(ChainType::MAIN);
}

BOOST_AUTO_TEST_SUITE_END()
