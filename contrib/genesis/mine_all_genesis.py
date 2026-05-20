#!/usr/bin/env python3
"""
Re-mine ALL b3chain genesis blocks with correct parameters matching C++ code.

The C++ CreateGenesisBlock function:
  - Encodes nBits in the coinbase scriptSig (not hardcoded 486604799)
  - Uses timestamp bytes from C string literal with \xe2\x80\x94 (UTF-8 em-dash)
"""

import struct
import hashlib
import time
import sys

try:
    import blake3
except ImportError:
    print("ERROR: pip install blake3")
    sys.exit(1)


def double_blake3(data: bytes) -> bytes:
    h1 = blake3.blake3(data).digest()
    h2 = blake3.blake3(h1).digest()
    return h2


def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def uint256_from_compact(nBits: int) -> int:
    nSize = nBits >> 24
    nWord = nBits & 0x007fffff
    if nSize <= 3:
        nWord >>= 8 * (3 - nSize)
    else:
        nWord <<= 8 * (nSize - 3)
    return nWord


def ser_compact_size(n: int) -> bytes:
    if n < 253:
        return struct.pack('<B', n)
    elif n < 0x10000:
        return struct.pack('<BH', 253, n)
    elif n < 0x100000000:
        return struct.pack('<BI', 254, n)
    else:
        return struct.pack('<BQ', 255, n)


def ser_string(s: bytes) -> bytes:
    return ser_compact_size(len(s)) + s


def encode_scriptnum(n: int) -> bytes:
    """Encode an integer as CScriptNum (variable-length signed LE)."""
    if n == 0:
        return b''
    negative = n < 0
    absval = abs(n)
    result = []
    while absval > 0:
        result.append(absval & 0xff)
        absval >>= 8
    # If the top bit is set, add a sign byte
    if result[-1] & 0x80:
        result.append(0x80 if negative else 0x00)
    elif negative:
        result[-1] |= 0x80
    return bytes(result)


def create_coinbase_script(timestamp_bytes: bytes, nBits: int) -> bytes:
    """
    Replicate C++ CScript() << (int64_t)nBits << CScriptNum(4) << timestamp_bytes

    In CScript, << int64_t pushes encode_scriptnum(nBits),
    << CScriptNum(4) pushes encode_scriptnum(4),
    << vector<uchar> pushes the raw bytes.
    """
    # Push nBits as CScriptNum
    bits_enc = encode_scriptnum(nBits)
    # Push 4 as CScriptNum
    four_enc = encode_scriptnum(4)
    # Build script: push(bits_enc) + push(four_enc) + push(timestamp)
    script = bytes([len(bits_enc)]) + bits_enc
    script += bytes([len(four_enc)]) + four_enc
    script += bytes([len(timestamp_bytes)]) + timestamp_bytes
    return script


def create_coinbase_tx(timestamp_bytes: bytes, nBits: int, pubkey_hex: str, reward_satoshis: int) -> bytes:
    tx = struct.pack('<I', 1)          # version
    tx += ser_compact_size(1)           # vin count
    tx += b'\x00' * 32                  # prev hash (null)
    tx += struct.pack('<I', 0xffffffff) # prev index
    script_sig = create_coinbase_script(timestamp_bytes, nBits)
    tx += ser_string(script_sig)
    tx += struct.pack('<I', 0xffffffff) # sequence
    tx += ser_compact_size(1)           # vout count
    tx += struct.pack('<Q', reward_satoshis)  # value
    pubkey_bytes = bytes.fromhex(pubkey_hex)
    script_pubkey = bytes([len(pubkey_bytes)]) + pubkey_bytes + bytes([0xac])
    tx += ser_string(script_pubkey)
    tx += struct.pack('<I', 0)          # locktime
    return tx


def serialize_header(nVersion, hashPrevBlock, hashMerkleRoot, nTime, nBits, nNonce):
    header = struct.pack('<i', nVersion)
    header += hashPrevBlock
    header += hashMerkleRoot
    header += struct.pack('<I', nTime)
    header += struct.pack('<I', nBits)
    header += struct.pack('<I', nNonce)
    return header


def mine_genesis(merkle_root, nTime, nBits, target):
    nNonce = 0
    start = time.time()
    prev = b'\x00' * 32
    while nNonce < 2**32:
        header = serialize_header(1, prev, merkle_root, nTime, nBits, nNonce)
        pow_hash = double_blake3(header)
        pow_int = int.from_bytes(pow_hash, byteorder='little')
        if pow_int <= target:
            identity_hash = double_sha256(header)
            elapsed = time.time() - start
            return nNonce, pow_hash, identity_hash, elapsed
        if nNonce % 500000 == 0 and nNonce > 0:
            elapsed = time.time() - start
            print(f"    ... {nNonce:,} nonces ({nNonce/elapsed:,.0f} H/s)", flush=True)
        nNonce += 1
    raise RuntimeError("No valid nonce found")


def main():
    # === Parameters matching C++ exactly ===
    # The C++ string literal: "b3chain genesis 2026 \xe2\x80\x94 conservative PoW in the spirit of Bitcoin"
    # \xe2\x80\x94 are raw byte values = UTF-8 em-dash
    timestamp_bytes = b"b3chain genesis 2026 \xe2\x80\x94 conservative PoW in the spirit of Bitcoin"

    pubkey_hex = "04678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5f"

    # b3chain F-6 fix (M-13): production chains use the tightened
    # powLimit = 0x1d7fffff (4x stricter).  Regtest unchanged.
    networks = [
        ("mainnet",  1739145600, 0x1d7fffff),
        ("testnet",  1739145601, 0x1d7fffff),
        ("regtest",  1739145602, 0x207fffff),
        ("testnet4", 1739145603, 0x1d7fffff),
        ("signet",   1739145604, 0x1d7fffff),
    ]

    for name, nTime, nBits in networks:
        print(f"\n{'='*50}")
        print(f"Mining {name} genesis (nTime={nTime}, nBits=0x{nBits:08x})")
        print(f"{'='*50}")

        coinbase_tx = create_coinbase_tx(timestamp_bytes, nBits, pubkey_hex, 50 * 100_000_000)
        merkle_root = double_sha256(coinbase_tx)
        target = uint256_from_compact(nBits)

        print(f"  Merkle root: {merkle_root[::-1].hex()}")
        print("  Mining...")

        nNonce, pow_hash, identity_hash, elapsed = mine_genesis(merkle_root, nTime, nBits, target)

        print(f"  Found! nNonce={nNonce}, time={elapsed:.1f}s")
        print(f"  PoW hash:      {pow_hash[::-1].hex()}")
        print(f"  Identity hash: {identity_hash[::-1].hex()}")
        print()
        print(f"  // {name}")
        print(f"  genesis = CreateGenesisBlock({nTime}, {nNonce}, 0x{nBits:08x}, 1, 50 * COIN);")
        print(f'  assert(consensus.hashGenesisBlock == uint256{{"{identity_hash[::-1].hex()}"}});')
        print(f'  assert(genesis.hashMerkleRoot == uint256{{"{merkle_root[::-1].hex()}"}});')


if __name__ == '__main__':
    main()
