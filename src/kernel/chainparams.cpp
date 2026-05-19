// Copyright (c) 2010 Satoshi Nakamoto
// Copyright (c) 2009-present The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <kernel/chainparams.h>

#include <chainparamsseeds.h>
#include <consensus/amount.h>
#include <consensus/merkle.h>
#include <consensus/params.h>
#include <hash.h>
#include <kernel/messagestartchars.h>
#include <logging.h>
#include <primitives/block.h>
#include <primitives/transaction.h>
#include <script/interpreter.h>
#include <script/script.h>
#include <uint256.h>
#include <util/chaintype.h>
#include <util/strencodings.h>

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <type_traits>

using namespace util::hex_literals;

// Workaround MSVC bug triggering C7595 when calling consteval constructors in
// initializer lists.
// https://developercommunity.visualstudio.com/t/Bogus-C7595-error-on-valid-C20-code/10906093
#if defined(_MSC_VER)
auto consteval_ctor(auto&& input) { return input; }
#else
#define consteval_ctor(input) (input)
#endif

static CBlock CreateGenesisBlock(const char* pszTimestamp, const CScript& genesisOutputScript, uint32_t nTime, uint32_t nNonce, uint32_t nBits, int32_t nVersion, const CAmount& genesisReward)
{
    CMutableTransaction txNew;
    txNew.version = 1;
    txNew.vin.resize(1);
    txNew.vout.resize(1);
    txNew.vin[0].scriptSig = CScript() << (int64_t)nBits << CScriptNum(4) << std::vector<unsigned char>((const unsigned char*)pszTimestamp, (const unsigned char*)pszTimestamp + strlen(pszTimestamp));
    txNew.vout[0].nValue = genesisReward;
    txNew.vout[0].scriptPubKey = genesisOutputScript;

    CBlock genesis;
    genesis.nTime    = nTime;
    genesis.nBits    = nBits;
    genesis.nNonce   = nNonce;
    genesis.nVersion = nVersion;
    genesis.vtx.push_back(MakeTransactionRef(std::move(txNew)));
    genesis.hashPrevBlock.SetNull();
    genesis.hashMerkleRoot = BlockMerkleRoot(genesis);
    return genesis;
}

/**
 * Build the genesis block. Note that the output of its generation
 * transaction cannot be spent since it did not originally exist in the
 * database.
 *
 * CBlock(hash=000000000019d6, ver=1, hashPrevBlock=00000000000000, hashMerkleRoot=4a5e1e, nTime=1231006505, nBits=1d00ffff, nNonce=2083236893, vtx=1)
 *   CTransaction(hash=4a5e1e, ver=1, vin.size=1, vout.size=1, nLockTime=0)
 *     CTxIn(COutPoint(000000, -1), coinbase 04ffff001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e206272696e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73)
 *     CTxOut(nValue=50.00000000, scriptPubKey=0x5F1DF16B2B704C8A578D0B)
 *   vMerkleTree: 4a5e1e
 */
static CBlock CreateGenesisBlock(uint32_t nTime, uint32_t nNonce, uint32_t nBits, int32_t nVersion, const CAmount& genesisReward)
{
    const char* pszTimestamp = "b3chain genesis 2026 \xe2\x80\x94 conservative PoW in the spirit of Bitcoin";
    const CScript genesisOutputScript = CScript() << "04678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5f"_hex << OP_CHECKSIG;
    return CreateGenesisBlock(pszTimestamp, genesisOutputScript, nTime, nNonce, nBits, nVersion, genesisReward);
}

/**
 * Main network on which people trade goods and services.
 */
class CMainParams : public CChainParams {
public:
    CMainParams() {
        m_chain_type = ChainType::MAIN;
        consensus.signet_blocks = false;
        consensus.signet_challenge.clear();
        consensus.nSubsidyHalvingInterval = 210000;
        // b3chain: all soft forks active from genesis, no exceptions
        consensus.BIP34Height = 0;
        consensus.BIP34Hash = uint256{};
        consensus.BIP65Height = 0;
        consensus.BIP66Height = 0;
        consensus.CSVHeight = 0;
        consensus.SegwitHeight = 0;
        consensus.MinBIP9WarningHeight = 0;
        // b3chain F-6 fix (M-13): consensus floor tightened 4x from the
        // original 0x1e01ffff to 0x1d7fffff.  The prior comment claimed
        // "BLAKE3 is ~10x faster than SHA-256d, so we use a wider
        // powLimit" -- that was incorrect: B3PoW-Scratch is memory-hard
        // (1 MB scratchpad, ~49 us/hash on KU5P), so per-hash cost is
        // actually HIGHER than SHA-256d, and the wider powLimit was
        // unjustified.  At the new floor, 1 KU5P FPGA (20.4 KH/s) solves
        // a minimum-difficulty block in ~27 min, closing the F-6
        // "tens-of-seconds" exploit window without breaking realistic
        // launch-hashrate bootstrap (5 boards = ~5.5 min/block at floor).
        // See doc/security/B3POW-51-ATTACK-ANALYSIS.md F-6.
        consensus.powLimit = uint256{"0000007fffffffffffffffffffffffffffffffffffffffffffffffffffffffff"};
        consensus.nPowTargetTimespan = 14 * 24 * 60 * 60; // two weeks
        consensus.nPowTargetSpacing = 10 * 60;
        consensus.fPowAllowMinDifficultyBlocks = false;
        // b3chain F-2 fix (M-2): BIP94 timewarp mitigation is enabled
        // pre-genesis on mainnet.  See doc/security/B3POW-51-ATTACK-ANALYSIS.md V-3.
        consensus.enforce_BIP94 = true;
        consensus.fPowNoRetargeting = false;
        consensus.nEarlyDifficultyGuardHeight = 10000; // b3chain: bootstrap difficulty guard
        // b3chain: B3PoW-Scratch v1.1 verifier (Finding 4 / mitigations D1+D2).
        consensus.b3pow_verify_budget_ms = 50;
        // b3chain M-6 (F-5 fix): 8-entry total capacity (5 LRU + 3 pinned).
        // 8 MB resident.  See src/crypto/b3pow_cache.h and V-7 in
        // doc/security/B3POW-51-ATTACK-ANALYSIS.md.
        consensus.b3pow_cache_depth = 8;
        // b3chain M-3 (V-4): LWMA-3 difficulty adjustment.  See src/pow/lwma3.h.
        consensus.use_lwma3 = true;
        // b3chain F-6 fix (M-13): post-bootstrap DAA operating floor,
        // 2x stricter than powLimit (= 8x stricter than the original
        // 0x1e01ffff).  LWMA-3 will not emit a target wider than this
        // once height > nEarlyDifficultyGuardHeight.  See
        // src/pow/lwma3.cpp step 5.
        consensus.operating_pow_floor_bits = 0x1d3fffff;
        // b3chain M-4 (F-3): cap reorg depth to bound the blast radius
        // of any 51% attack.  200 blocks ~ 33 hours at 600s spacing.
        consensus.max_reorg_depth = 200;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = Consensus::BIP9Deployment::NEVER_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].min_activation_height = 0; // No activation delay
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].threshold = 1815; // 90%
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].period = 2016;

        // Deployment of Taproot (BIPs 340-342) — active from genesis for b3chain
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].bit = 2;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nStartTime = Consensus::BIP9Deployment::ALWAYS_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].min_activation_height = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].threshold = 1815; // 90%
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].period = 2016;

        consensus.nMinimumChainWork = uint256{};
        consensus.defaultAssumeValid = uint256{};

        /**
         * b3chain: unique message start bytes to isolate from Bitcoin network.
         */
        pchMessageStart[0] = 0xb3;
        pchMessageStart[1] = 0xc0;
        pchMessageStart[2] = 0x01;
        pchMessageStart[3] = 0x0d;
        nDefaultPort = 8533;
        nPruneAfterHeight = 100000;
        m_assumed_blockchain_size = 0;
        m_assumed_chain_state_size = 0;

        // b3chain F-6 fix (M-13): genesis re-mined at the tightened
        // powLimit = 0x1d7fffff (4x stricter than the original 0x1e01ffff).
        // See contrib/genesis/mine_all_genesis.py.
        genesis = CreateGenesisBlock(1739145600, 89222440, 0x1d7fffff, 1, 50 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256{"b6cdeba06d5b4c98df9db07c58d0d7ca50866b855ab3ca470382a7d19b52a9e6"});
        assert(genesis.hashMerkleRoot == uint256{"a3e989c3afe53b750b3a668b7eef73109961252ace3470a0b50065195adc1e4f"});

        // b3chain: no DNS seeds yet (will be added when seed nodes are live)
        vFixedSeeds.clear();
        vSeeds.clear();

        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,0x19); // "B" prefix
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,0x55); // "b" prefix
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,128);  // keep same as Bitcoin for WIF compat
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x88, 0xB2, 0x1E};
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x88, 0xAD, 0xE4};

        bech32_hrp = "b3";
        // Note: vFixedSeeds already cleared above (line with vSeeds.clear)

        fDefaultConsistencyChecks = false;
        m_is_mockable_chain = false;

        // b3chain: no assumeutxo data yet (new chain)
        m_assumeutxo_data = {};

        chainTxData = ChainTxData{
            .nTime    = 0,
            .tx_count = 0,
            .dTxRate  = 0,
        };
    }
};

/**
 * Testnet (v3): public test network which is reset from time to time.
 */
class CTestNetParams : public CChainParams {
public:
    CTestNetParams() {
        m_chain_type = ChainType::TESTNET;
        consensus.signet_blocks = false;
        consensus.signet_challenge.clear();
        consensus.nSubsidyHalvingInterval = 210000;
        // b3chain testnet: all soft forks active from genesis
        consensus.BIP34Height = 0;
        consensus.BIP34Hash = uint256{};
        consensus.BIP65Height = 0;
        consensus.BIP66Height = 0;
        consensus.CSVHeight = 0;
        consensus.SegwitHeight = 0;
        consensus.MinBIP9WarningHeight = 0;
        // b3chain F-6 fix (M-13): consensus floor tightened 4x.  See
        // mainnet rationale and doc/security/B3POW-51-ATTACK-ANALYSIS.md F-6.
        consensus.powLimit = uint256{"0000007fffffffffffffffffffffffffffffffffffffffffffffffffffffffff"};
        consensus.nPowTargetTimespan = 14 * 24 * 60 * 60; // two weeks
        consensus.nPowTargetSpacing = 10 * 60;
        consensus.fPowAllowMinDifficultyBlocks = true;
        // b3chain F-2 fix (M-2): BIP94 timewarp mitigation enabled on testnet.
        consensus.enforce_BIP94 = true;
        consensus.fPowNoRetargeting = false;
        consensus.nEarlyDifficultyGuardHeight = 10000; // b3chain: bootstrap difficulty guard
        // b3chain: B3PoW-Scratch v1.1 verifier (Finding 4 / mitigations D1+D2).
        consensus.b3pow_verify_budget_ms = 50;
        // b3chain M-6 (F-5 fix): 8-entry total (5 LRU + 3 pinned).
        consensus.b3pow_cache_depth = 8;
        // b3chain M-3, M-4: LWMA-3 + reorg-depth cap (see mainnet rationale).
        consensus.use_lwma3 = true;
        consensus.max_reorg_depth = 200;
        // b3chain F-6 fix (M-13): post-bootstrap DAA operating floor.  See
        // mainnet rationale and src/pow/lwma3.cpp step 5.
        consensus.operating_pow_floor_bits = 0x1d3fffff;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = Consensus::BIP9Deployment::NEVER_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].min_activation_height = 0; // No activation delay
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].threshold = 1512; // 75%
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].period = 2016;

        // Deployment of Taproot (BIPs 340-342) — active from genesis for b3chain
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].bit = 2;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nStartTime = Consensus::BIP9Deployment::ALWAYS_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].min_activation_height = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].threshold = 1512; // 75%
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].period = 2016;

        consensus.nMinimumChainWork = uint256{};
        consensus.defaultAssumeValid = uint256{};

        pchMessageStart[0] = 0xb3;
        pchMessageStart[1] = 0xc1;
        pchMessageStart[2] = 0x02;
        pchMessageStart[3] = 0x0e;
        nDefaultPort = 18533;
        nPruneAfterHeight = 1000;
        m_assumed_blockchain_size = 0;
        m_assumed_chain_state_size = 0;

        // b3chain F-6 fix (M-13): testnet genesis re-mined at new powLimit.
        genesis = CreateGenesisBlock(1739145601, 22405111, 0x1d7fffff, 1, 50 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256{"4b3f758b306086eca0a95c68020ab74cb87c652b1788780fa3235306bb3d4006"});
        assert(genesis.hashMerkleRoot == uint256{"a3e989c3afe53b750b3a668b7eef73109961252ace3470a0b50065195adc1e4f"});

        // Phase 8a testnet bootstrap: DNS seed (round-robin A record
        // returning the operator-run seed nodes) plus the BIP155-encoded
        // fixed seed list compiled in from contrib/seeds/nodes_test.txt
        // for clients that cannot reach DNS.
        vSeeds.clear();
        vSeeds.emplace_back("testnet-seed.b3chain.org.");
        vFixedSeeds = std::vector<uint8_t>(std::begin(chainparams_seed_test), std::end(chainparams_seed_test));

        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,111);
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,196);
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,239);
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x35, 0x87, 0xCF};
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x35, 0x83, 0x94};

        bech32_hrp = "tb3";

        fDefaultConsistencyChecks = false;
        m_is_mockable_chain = false;

        m_assumeutxo_data = {};

        chainTxData = ChainTxData{
            .nTime    = 0,
            .tx_count = 0,
            .dTxRate  = 0,
        };
    }
};

/**
 * Testnet (v4): public test network which is reset from time to time.
 */
class CTestNet4Params : public CChainParams {
public:
    CTestNet4Params() {
        m_chain_type = ChainType::TESTNET4;
        consensus.signet_blocks = false;
        consensus.signet_challenge.clear();
        consensus.nSubsidyHalvingInterval = 210000;
        consensus.BIP34Height = 0;
        consensus.BIP34Hash = uint256{};
        consensus.BIP65Height = 0;
        consensus.BIP66Height = 0;
        consensus.CSVHeight = 0;
        consensus.SegwitHeight = 0;
        consensus.MinBIP9WarningHeight = 0;
        // b3chain F-6 fix (M-13): consensus floor tightened 4x.  See
        // mainnet rationale and doc/security/B3POW-51-ATTACK-ANALYSIS.md F-6.
        consensus.powLimit = uint256{"0000007fffffffffffffffffffffffffffffffffffffffffffffffffffffffff"};
        consensus.nPowTargetTimespan = 14 * 24 * 60 * 60; // two weeks
        consensus.nPowTargetSpacing = 10 * 60;
        consensus.fPowAllowMinDifficultyBlocks = true;
        // Testnet4 already enables BIP94 in upstream Bitcoin (block-storm rule).
        consensus.enforce_BIP94 = true;
        consensus.fPowNoRetargeting = false;
        consensus.nEarlyDifficultyGuardHeight = 10000; // b3chain: bootstrap difficulty guard
        // b3chain: B3PoW-Scratch v1.1 verifier (Finding 4 / mitigations D1+D2).
        consensus.b3pow_verify_budget_ms = 50;
        // b3chain M-6 (F-5 fix): 8-entry total (5 LRU + 3 pinned).
        consensus.b3pow_cache_depth = 8;
        // b3chain M-3, M-4: LWMA-3 + reorg-depth cap (see mainnet rationale).
        consensus.use_lwma3 = true;
        consensus.max_reorg_depth = 200;
        // b3chain F-6 fix (M-13): post-bootstrap DAA operating floor.  See
        // mainnet rationale and src/pow/lwma3.cpp step 5.
        consensus.operating_pow_floor_bits = 0x1d3fffff;

        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = Consensus::BIP9Deployment::NEVER_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].min_activation_height = 0; // No activation delay
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].threshold = 1512; // 75%
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].period = 2016;

        // Deployment of Taproot (BIPs 340-342)
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].bit = 2;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nStartTime = Consensus::BIP9Deployment::ALWAYS_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].min_activation_height = 0; // No activation delay
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].threshold = 1512; // 75%
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].period = 2016;

        consensus.nMinimumChainWork = uint256{"00000000000000000000000000000000000000000000034a4690fe592dc49c7c"};
        consensus.defaultAssumeValid = uint256{"000000000000000180a58e7fa3b0db84b5ea76377524894f53660d93ac839d9b"}; // 91000

        pchMessageStart[0] = 0x1c;
        pchMessageStart[1] = 0x16;
        pchMessageStart[2] = 0x3f;
        pchMessageStart[3] = 0x28;
        nDefaultPort = 48333;
        nPruneAfterHeight = 1000;
        m_assumed_blockchain_size = 22;
        m_assumed_chain_state_size = 2;

        // b3chain F-6 fix (M-13): testnet4 genesis re-mined at new powLimit.
        genesis = CreateGenesisBlock(1739145603, 23025286, 0x1d7fffff, 1, 50 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256{"eb3fd63c95062962d2fb42ac3dcbc2056eefb8b3209858a1d400cf2b565ea1a0"});
        assert(genesis.hashMerkleRoot == uint256{"a3e989c3afe53b750b3a668b7eef73109961252ace3470a0b50065195adc1e4f"});

        vFixedSeeds.clear();
        vSeeds.clear();

        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,111);
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,196);
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,239);
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x35, 0x87, 0xCF};
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x35, 0x83, 0x94};

        bech32_hrp = "tb3";

        fDefaultConsistencyChecks = false;
        m_is_mockable_chain = false;

        m_assumeutxo_data = {};

        chainTxData = ChainTxData{
            .nTime    = 0,
            .tx_count = 0,
            .dTxRate  = 0,
        };
    }
};

/**
 * Signet: test network with an additional consensus parameter (see BIP325).
 */
class SigNetParams : public CChainParams {
public:
    explicit SigNetParams(const SigNetOptions& options)
    {
        std::vector<uint8_t> bin;
        vFixedSeeds.clear();
        vSeeds.clear();

        if (!options.challenge) {
            bin = "512103ad5e0edad18cb1f0fc0d28a3d4f1f3e445640337489abb10404f2d1e086be430210359ef5021964fe22d6f8e05b2463c9540ce96883fe3b278760f048f5189f2e6c452ae"_hex_v_u8;
            // b3chain: no signet seeds yet
            consensus.nMinimumChainWork = uint256{};
            consensus.defaultAssumeValid = uint256{};
            m_assumed_blockchain_size = 0;
            m_assumed_chain_state_size = 0;
            chainTxData = ChainTxData{
                .nTime    = 0,
                .tx_count = 0,
                .dTxRate  = 0,
            };
        } else {
            bin = *options.challenge;
            consensus.nMinimumChainWork = uint256{};
            consensus.defaultAssumeValid = uint256{};
            m_assumed_blockchain_size = 0;
            m_assumed_chain_state_size = 0;
            chainTxData = ChainTxData{
                0,
                0,
                0,
            };
            LogInfo("Signet with challenge %s", HexStr(bin));
        }

        if (options.seeds) {
            vSeeds = *options.seeds;
        }

        m_chain_type = ChainType::SIGNET;
        consensus.signet_blocks = true;
        consensus.signet_challenge.assign(bin.begin(), bin.end());
        consensus.nSubsidyHalvingInterval = 210000;
        consensus.BIP34Height = 0;
        consensus.BIP34Hash = uint256{};
        consensus.BIP65Height = 0;
        consensus.BIP66Height = 0;
        consensus.CSVHeight = 0;
        consensus.SegwitHeight = 0;
        consensus.nPowTargetTimespan = 14 * 24 * 60 * 60; // two weeks
        consensus.nPowTargetSpacing = 10 * 60;
        consensus.fPowAllowMinDifficultyBlocks = false;
        // b3chain F-2 fix (M-2): BIP94 timewarp mitigation enabled on signet.
        consensus.enforce_BIP94 = true;
        consensus.fPowNoRetargeting = false;
        consensus.MinBIP9WarningHeight = 0;
        // b3chain F-6 fix (M-13): consensus floor tightened 4x.  See
        // mainnet rationale and doc/security/B3POW-51-ATTACK-ANALYSIS.md F-6.
        consensus.powLimit = uint256{"0000007fffffffffffffffffffffffffffffffffffffffffffffffffffffffff"};
        // b3chain: B3PoW-Scratch v1.1 verifier (Finding 4 / mitigations D1+D2).
        consensus.b3pow_verify_budget_ms = 50;
        // b3chain M-6 (F-5 fix): 8-entry total (5 LRU + 3 pinned).
        consensus.b3pow_cache_depth = 8;
        // b3chain M-3, M-4: LWMA-3 + reorg-depth cap (see mainnet rationale).
        consensus.use_lwma3 = true;
        consensus.max_reorg_depth = 200;
        // b3chain F-6 fix (M-13): post-bootstrap DAA operating floor.  See
        // mainnet rationale and src/pow/lwma3.cpp step 5.
        consensus.operating_pow_floor_bits = 0x1d3fffff;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = Consensus::BIP9Deployment::NEVER_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].min_activation_height = 0; // No activation delay
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].threshold = 1815; // 90%
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].period = 2016;

        // Activation of Taproot (BIPs 340-342)
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].bit = 2;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nStartTime = Consensus::BIP9Deployment::ALWAYS_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].min_activation_height = 0; // No activation delay
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].threshold = 1815; // 90%
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].period = 2016;

        // message start is defined as the first 4 bytes of the sha256d of the block script
        HashWriter h{};
        h << consensus.signet_challenge;
        uint256 hash = h.GetHash();
        std::copy_n(hash.begin(), 4, pchMessageStart.begin());

        nDefaultPort = 38333;
        nPruneAfterHeight = 1000;

        // b3chain F-6 fix (M-13): signet genesis re-mined at new powLimit.
        genesis = CreateGenesisBlock(1739145604, 24911779, 0x1d7fffff, 1, 50 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256{"d30df57fdaebdb8090ff90f18357d2497a5ba4b083aa748a458c087254075ed7"});
        assert(genesis.hashMerkleRoot == uint256{"a3e989c3afe53b750b3a668b7eef73109961252ace3470a0b50065195adc1e4f"});

        m_assumeutxo_data = {};

        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,111);
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,196);
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,239);
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x35, 0x87, 0xCF};
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x35, 0x83, 0x94};

        bech32_hrp = "tb3";

        fDefaultConsistencyChecks = false;
        m_is_mockable_chain = false;
    }
};

/**
 * Regression test: intended for private networks only. Has minimal difficulty to ensure that
 * blocks can be found instantly.
 */
class CRegTestParams : public CChainParams
{
public:
    explicit CRegTestParams(const RegTestOptions& opts)
    {
        m_chain_type = ChainType::REGTEST;
        consensus.signet_blocks = false;
        consensus.signet_challenge.clear();
        consensus.nSubsidyHalvingInterval = 150;
        consensus.BIP34Height = 1; // Always active unless overridden
        consensus.BIP34Hash = uint256();
        consensus.BIP65Height = 1;  // Always active unless overridden
        consensus.BIP66Height = 1;  // Always active unless overridden
        consensus.CSVHeight = 1;    // Always active unless overridden
        consensus.SegwitHeight = 0; // Always active unless overridden
        consensus.MinBIP9WarningHeight = 0;
        consensus.powLimit = uint256{"7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"};
        consensus.nPowTargetTimespan = 24 * 60 * 60; // one day
        consensus.nPowTargetSpacing = 10 * 60;
        consensus.fPowAllowMinDifficultyBlocks = true;
        consensus.enforce_BIP94 = opts.enforce_bip94;
        consensus.fPowNoRetargeting = true;
        // b3chain: B3PoW-Scratch v1.1 verifier (Finding 4 / mitigations D1+D2).
        // Regtest gets a generous budget and a tiny cache so functional
        // tests aren't sensitive to CI-runner CPU jitter.
        consensus.b3pow_verify_budget_ms = 1000;
        consensus.b3pow_cache_depth = 1;

        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].bit = 28;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nStartTime = 0;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].min_activation_height = 0; // No activation delay
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].threshold = 108; // 75%
        consensus.vDeployments[Consensus::DEPLOYMENT_TESTDUMMY].period = 144; // Faster than normal for regtest (144 instead of 2016)

        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].bit = 2;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nStartTime = Consensus::BIP9Deployment::ALWAYS_ACTIVE;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].nTimeout = Consensus::BIP9Deployment::NO_TIMEOUT;
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].min_activation_height = 0; // No activation delay
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].threshold = 108; // 75%
        consensus.vDeployments[Consensus::DEPLOYMENT_TAPROOT].period = 144;

        consensus.nMinimumChainWork = uint256{};
        consensus.defaultAssumeValid = uint256{};

        pchMessageStart[0] = 0xb3;
        pchMessageStart[1] = 0xc2;
        pchMessageStart[2] = 0x03;
        pchMessageStart[3] = 0x0f;
        nDefaultPort = 18544;
        nPruneAfterHeight = opts.fastprune ? 100 : 1000;
        m_assumed_blockchain_size = 0;
        m_assumed_chain_state_size = 0;

        for (const auto& [dep, height] : opts.activation_heights) {
            switch (dep) {
            case Consensus::BuriedDeployment::DEPLOYMENT_SEGWIT:
                consensus.SegwitHeight = int{height};
                break;
            case Consensus::BuriedDeployment::DEPLOYMENT_HEIGHTINCB:
                consensus.BIP34Height = int{height};
                break;
            case Consensus::BuriedDeployment::DEPLOYMENT_DERSIG:
                consensus.BIP66Height = int{height};
                break;
            case Consensus::BuriedDeployment::DEPLOYMENT_CLTV:
                consensus.BIP65Height = int{height};
                break;
            case Consensus::BuriedDeployment::DEPLOYMENT_CSV:
                consensus.CSVHeight = int{height};
                break;
            }
        }

        for (const auto& [deployment_pos, version_bits_params] : opts.version_bits_parameters) {
            consensus.vDeployments[deployment_pos].nStartTime = version_bits_params.start_time;
            consensus.vDeployments[deployment_pos].nTimeout = version_bits_params.timeout;
            consensus.vDeployments[deployment_pos].min_activation_height = version_bits_params.min_activation_height;
        }

        genesis = CreateGenesisBlock(1739145602, 0, 0x207fffff, 1, 50 * COIN);
        consensus.hashGenesisBlock = genesis.GetHash();
        assert(consensus.hashGenesisBlock == uint256{"8c19b11553c449cfe6f8b00c830b8e34249529fd9521cb4825541df9b0372de4"});
        assert(genesis.hashMerkleRoot == uint256{"bfa2ede04da8002d67d9cdedf1d8c64e0dcc290b478ae89c43a76985dbfa83ba"});

        vFixedSeeds.clear(); //!< Regtest mode doesn't have any fixed seeds.
        vSeeds.clear();
        vSeeds.emplace_back("dummySeed.invalid.");

        fDefaultConsistencyChecks = true;
        m_is_mockable_chain = true;

        // b3chain: regtest assumeutxo data (generated from TestChain100Setup).
        // The UTXO set hash (HASH_SERIALIZED) is identical to Bitcoin Core because the
        // coinbase transactions use the same deterministic test key and subsidy schedule.
        // Only the block hashes differ (due to BLAKE3 PoW).
        m_assumeutxo_data = {
            {
                .height = 110,
                .hash_serialized = AssumeutxoHash{uint256{"b952555c8ab81fec46f3d4253b7af256d766ceb39fb7752b9d18cdf4a0141327"}},
                .m_chain_tx_count = 111,
                .blockhash = uint256{"ab1df7084867e289443de7efa50ea47b4c59670454bfb9d2e1b6822f014627a6"},
            },
            {
                .height = 200,
                .hash_serialized = AssumeutxoHash{uint256{"8f8e02e0ebf79da1710b440290ea1bef28297882548bd41a2037d2461f48ec0e"}},
                .m_chain_tx_count = 201,
                .blockhash = uint256{"be3fdf916a5cfe13b52e77d406b5ed56343a75b4c294b60a0efa9b7c8c742bf6"},
            },
        };

        chainTxData = ChainTxData{
            .nTime = 0,
            .tx_count = 0,
            .dTxRate = 0.001, // Set a non-zero rate to make it testable
        };

        base58Prefixes[PUBKEY_ADDRESS] = std::vector<unsigned char>(1,111);
        base58Prefixes[SCRIPT_ADDRESS] = std::vector<unsigned char>(1,196);
        base58Prefixes[SECRET_KEY] =     std::vector<unsigned char>(1,239);
        base58Prefixes[EXT_PUBLIC_KEY] = {0x04, 0x35, 0x87, 0xCF};
        base58Prefixes[EXT_SECRET_KEY] = {0x04, 0x35, 0x83, 0x94};

        bech32_hrp = "b3rt";
    }
};

std::unique_ptr<const CChainParams> CChainParams::SigNet(const SigNetOptions& options)
{
    return std::make_unique<const SigNetParams>(options);
}

std::unique_ptr<const CChainParams> CChainParams::RegTest(const RegTestOptions& options)
{
    return std::make_unique<const CRegTestParams>(options);
}

std::unique_ptr<const CChainParams> CChainParams::Main()
{
    return std::make_unique<const CMainParams>();
}

std::unique_ptr<const CChainParams> CChainParams::TestNet()
{
    return std::make_unique<const CTestNetParams>();
}

std::unique_ptr<const CChainParams> CChainParams::TestNet4()
{
    return std::make_unique<const CTestNet4Params>();
}

std::vector<int> CChainParams::GetAvailableSnapshotHeights() const
{
    std::vector<int> heights;
    heights.reserve(m_assumeutxo_data.size());

    for (const auto& data : m_assumeutxo_data) {
        heights.emplace_back(data.height);
    }
    return heights;
}

std::optional<ChainType> GetNetworkForMagic(const MessageStartChars& message)
{
    const auto mainnet_msg = CChainParams::Main()->MessageStart();
    const auto testnet_msg = CChainParams::TestNet()->MessageStart();
    const auto testnet4_msg = CChainParams::TestNet4()->MessageStart();
    const auto regtest_msg = CChainParams::RegTest({})->MessageStart();
    const auto signet_msg = CChainParams::SigNet({})->MessageStart();

    if (std::ranges::equal(message, mainnet_msg)) {
        return ChainType::MAIN;
    } else if (std::ranges::equal(message, testnet_msg)) {
        return ChainType::TESTNET;
    } else if (std::ranges::equal(message, testnet4_msg)) {
        return ChainType::TESTNET4;
    } else if (std::ranges::equal(message, regtest_msg)) {
        return ChainType::REGTEST;
    } else if (std::ranges::equal(message, signet_msg)) {
        return ChainType::SIGNET;
    }
    return std::nullopt;
}
