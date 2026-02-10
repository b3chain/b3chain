#!/usr/bin/env python3
"""Mine genesis blocks for b3chain testnet and regtest."""

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


def uint256_from_compact(nBits: int) -> int:
    nSize = nBits >> 24
    nWord = nBits & 0x007fffff
    if nSize <= 3:
        nWord >>= 8 * (3 - nSize)
    else:
        nWord <<= 8 * (nSize - 3)
    return nWord


def ser_compact_size(nSize: int) -> bytes:
    if nSize < 253:
        return struct.pack('<B', nSize)
    elif nSize < 0x10000:
        return struct.pack('<BH', 253, nSize)
    elif nSize < 0x100000000:
        return struct.pack('<BI', 254, nSize)
    else:
        return struct.pack('<BQ', 255, nSize)


def ser_string(s: bytes) -> bytes:
    return ser_compact_size(len(s)) + s


def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def create_coinbase_script(timestamp: str, nBits: int) -> bytes:
    bits_bytes = struct.pack('<I', nBits)
    script_num = bytes([0x01, 0x04])
    ts_bytes = timestamp.encode('utf-8')
    script = bytes([len(bits_bytes)]) + bits_bytes + script_num + bytes([len(ts_bytes)]) + ts_bytes
    return script


def create_coinbase_tx(timestamp: str, nBits: int, pubkey_hex: str, reward_satoshis: int) -> bytes:
    tx = struct.pack('<I', 1)
    tx += ser_compact_size(1)
    tx += b'\x00' * 32
    tx += struct.pack('<I', 0xffffffff)
    script_sig = create_coinbase_script(timestamp, nBits)
    tx += ser_string(script_sig)
    tx += struct.pack('<I', 0xffffffff)
    tx += ser_compact_size(1)
    tx += struct.pack('<Q', reward_satoshis)
    pubkey_bytes = bytes.fromhex(pubkey_hex)
    script_pubkey = bytes([len(pubkey_bytes)]) + pubkey_bytes + bytes([0xac])
    tx += ser_string(script_pubkey)
    tx += struct.pack('<I', 0)
    return tx


def serialize_block_header(nVersion, hashPrevBlock, hashMerkleRoot, nTime, nBits, nNonce):
    header = struct.pack('<i', nVersion)
    header += hashPrevBlock
    header += hashMerkleRoot
    header += struct.pack('<I', nTime)
    header += struct.pack('<I', nBits)
    header += struct.pack('<I', nNonce)
    return header


def mine_genesis(nVersion, hashPrevBlock, hashMerkleRoot, nTime, nBits, target):
    nNonce = 0
    start = time.time()
    while nNonce < 2**32:
        header = serialize_block_header(nVersion, hashPrevBlock, hashMerkleRoot, nTime, nBits, nNonce)
        pow_hash = double_blake3(header)
        pow_hash_int = int.from_bytes(pow_hash, byteorder='little')
        if pow_hash_int <= target:
            elapsed = time.time() - start
            identity_hash = double_sha256(header)
            return nNonce, pow_hash, identity_hash, elapsed
        nNonce += 1
    raise RuntimeError("Failed")


def mine_for_params(name, timestamp, nTime, nBits, pubkey_hex):
    print(f"\n=== Mining {name} genesis ===")
    print(f"  timestamp: {timestamp!r}")
    print(f"  nTime: {nTime}, nBits: 0x{nBits:08x}")

    coinbase_tx = create_coinbase_tx(timestamp, nBits, pubkey_hex, 50 * 100_000_000)
    merkle_root = double_sha256(coinbase_tx)
    target = uint256_from_compact(nBits)

    nNonce, pow_hash, identity_hash, elapsed = mine_genesis(
        1, b'\x00' * 32, merkle_root, nTime, nBits, target)

    print(f"  nNonce: {nNonce}")
    print(f"  PoW hash: {pow_hash[::-1].hex()}")
    print(f"  Identity hash: {identity_hash[::-1].hex()}")
    print(f"  Merkle root: {merkle_root[::-1].hex()}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"  genesis = CreateGenesisBlock({nTime}, {nNonce}, 0x{nBits:08x}, 1, 50 * COIN);")
    print(f'  assert(consensus.hashGenesisBlock == uint256{{"{identity_hash[::-1].hex()}"}});')
    print(f'  assert(genesis.hashMerkleRoot == uint256{{"{merkle_root[::-1].hex()}"}});')
    return nNonce, identity_hash, merkle_root


pubkey = "04678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5f"
ts = "b3chain genesis 2026 \xe2\x80\x94 conservative PoW in the spirit of Bitcoin"

# Testnet: same timestamp, different nTime
mine_for_params("testnet", ts, 1739145601, 0x1e0fffff, pubkey)

# Regtest: much easier difficulty
mine_for_params("regtest", ts, 1739145602, 0x207fffff, pubkey)
