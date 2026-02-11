# B3Chain Proof-of-Work Design

## Overview

B3Chain uses a **dual-hash architecture** where two different hash functions
serve distinct roles:

| Purpose | Algorithm | Function |
|---------|-----------|----------|
| **Proof-of-Work (PoW)** | Double BLAKE3-256 | `CBlockHeader::GetPoWHash()` |
| **Block identity / merkle trees** | Double SHA-256 | `CBlockHeader::GetHash()` |

This design change from Bitcoin Core's SHA-256d-for-everything approach provides:

- **ASIC resistance** at launch (no existing SHA-256d ASICs can mine B3Chain)
- **Faster PoW validation** (BLAKE3 is ~5-14x faster than SHA-256 on modern CPUs)
- **Backward compatibility** (all non-PoW hashing, including txids, merkle
  trees, and address derivation, remains SHA-256d)

## Double BLAKE3-256

The PoW hash is computed as:

```
PoW_hash = BLAKE3-256( BLAKE3-256( serialize(block_header) ) )
```

Where `serialize(block_header)` produces the standard 80-byte Bitcoin block
header encoding (version, prev_hash, merkle_root, timestamp, bits, nonce).

The "double hash" construction mirrors Bitcoin's double-SHA-256 pattern,
providing defense against length-extension attacks.

### Implementation

**C++ (src/primitives/block.cpp)**:
```cpp
uint256 CBlockHeader::GetPoWHash() const
{
    DataStream ss{};
    ss << *this;
    // First BLAKE3-256
    blake3_hasher h1;
    blake3_hasher_init(&h1);
    blake3_hasher_update(&h1, ss.data(), ss.size());
    uint8_t hash1[BLAKE3_OUT_LEN];
    blake3_hasher_finalize(&h1, hash1, BLAKE3_OUT_LEN);
    // Second BLAKE3-256
    blake3_hasher h2;
    blake3_hasher_init(&h2);
    blake3_hasher_update(&h2, hash1, BLAKE3_OUT_LEN);
    uint8_t hash2[BLAKE3_OUT_LEN];
    blake3_hasher_finalize(&h2, hash2, BLAKE3_OUT_LEN);
    uint256 result;
    memcpy(result.data(), hash2, 32);
    return result;
}
```

**Python test framework (test/functional/test_framework/messages.py)**:
```python
def pow_hash256(data: bytes) -> bytes:
    h1 = blake3(data).digest()
    return blake3(h1).digest()
```

## Where Each Hash Is Used

### GetPoWHash() (Double BLAKE3-256)

Used **only** for Proof-of-Work validation:

- `CheckProofOfWork()` in `src/pow.cpp`
- `b3chain-util grind` nonce search in `src/bitcoin-util.cpp`
- Block validation during IBD in `src/node/blockstorage.cpp`
- Mining (block template solving)

### GetHash() (Double SHA-256)

Used for **everything else** — unchanged from Bitcoin Core:

- Block identity (the hash referenced in `hashPrevBlock`)
- Transaction IDs (txid)
- Merkle tree construction
- P2P protocol (block inventory, headers)
- RPC responses (`getblock`, `getblockheader`, etc.)

## BLAKE3 SIMD Acceleration

The BLAKE3 library includes hardware-optimized implementations that are
selected automatically at runtime via CPUID:

| Instruction Set | SIMD Degree | Speedup vs Portable |
|----------------|-------------|---------------------|
| Portable (C)   | 1           | 1x (baseline)       |
| SSE2           | 4           | ~3x                 |
| SSE4.1         | 4           | ~4x                 |
| AVX2           | 8           | ~8x                 |
| AVX-512        | 16          | ~14x                |

Assembly implementations are in `src/crypto/blake3/blake3_*_x86-64_unix.S`.
The dispatch layer (`blake3_dispatch.c`) handles runtime detection.

## Network Parameters

| Parameter | Mainnet | Testnet | Regtest |
|-----------|---------|---------|---------|
| Default P2P port | 8533 | 18533 | 18544 |
| Default RPC port | 8534 | 18534 | 18543 |
| Bech32 HRP | `b3` | `tb3` | `b3rt` |
| Address prefix | `B` (0x19) | `m/n` (0x6F) | `m/n` (0x6F) |
| Config file | `b3chain.conf` | — | — |
| Data directory | `.b3chain` | — | — |

## Security Considerations

1. **No SHA-256d mining**: A block that happens to satisfy SHA-256d difficulty
   will almost certainly NOT satisfy BLAKE3 difficulty. The hash outputs are
   completely uncorrelated. This is verified by the `blake3_rejects_sha256d_nonce`
   unit test.

2. **Identity hash unchanged**: The block's "identity" (used in `hashPrevBlock`,
   chain selection, and P2P protocol) still uses SHA-256d. This means the
   existing Bitcoin P2P message format is preserved.

3. **BLAKE3 is a NIST-recognized algorithm** from the BLAKE family (finalist
   in the SHA-3 competition). It provides 256-bit security with a Merkle tree
   internal structure that enables parallelism.

## Building

BLAKE3 with SIMD is enabled automatically on x86-64 Linux. The CMake build
system detects the platform and includes the appropriate assembly files:

```cmake
# From src/crypto/CMakeLists.txt
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64|AMD64" AND NOT WIN32)
  enable_language(ASM)
  target_sources(bitcoin_crypto_blake3 PRIVATE
    blake3/blake3_sse2_x86-64_unix.S
    blake3/blake3_sse41_x86-64_unix.S
    blake3/blake3_avx2_x86-64_unix.S
    blake3/blake3_avx512_x86-64_unix.S
  )
endif()
```

On other platforms (Windows, ARM), the portable C implementation is used as
a fallback. NEON support for ARM is available but not yet enabled.

## Test Coverage

The following unit tests verify the BLAKE3 PoW implementation:

- `crypto_tests/blake3_single_hash` — BLAKE3 test vectors
- `crypto_tests/blake3_double_hash` — Double-BLAKE3 construction
- `crypto_tests/blake3_dual_hash_design` — GetHash() vs GetPoWHash() independence
- `crypto_tests/blake3_rejects_sha256d_nonce` — Cross-algorithm uncorrelation
- `crypto_tests/blake3_simd_acceleration` — SIMD degree verification
- `miner_tests` — Full block mining with BLAKE3 PoW
- `pow_tests` — Difficulty target checking with GetPoWHash()
