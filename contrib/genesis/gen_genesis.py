#!/usr/bin/env python3
"""
b3chain genesis block generator.

Constructs the coinbase transaction, computes the merkle root,
then iterates nonce values computing double-BLAKE3-256 until
hash <= target. Outputs nonce, genesis hash, merkle root, and
the coinbase hex for embedding into chainparams.cpp.

Requires: blake3  (pip install blake3)
"""

import struct
import hashlib
import time
import sys

try:
    import blake3
except ImportError:
    print("ERROR: pip install blake3  (Python blake3 package required)")
    sys.exit(1)


def double_blake3(data: bytes) -> bytes:
    """Double BLAKE3-256: BLAKE3(BLAKE3(data))"""
    h1 = blake3.blake3(data).digest()
    h2 = blake3.blake3(h1).digest()
    return h2


def uint256_from_compact(nBits: int) -> int:
    """Convert compact representation to uint256 integer."""
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
    """Create the coinbase scriptSig like Bitcoin: nBits(LE) + CScriptNum(4) + timestamp"""
    # Push nBits as 4 bytes LE
    bits_bytes = struct.pack('<I', nBits)
    # CScriptNum(4) = 0x04
    script_num = bytes([0x01, 0x04])
    # Timestamp as bytes
    ts_bytes = timestamp.encode('utf-8')
    # Build script: push(bits) + push(04) + push(timestamp)
    script = bytes([len(bits_bytes)]) + bits_bytes + script_num + bytes([len(ts_bytes)]) + ts_bytes
    return script


def create_coinbase_tx(timestamp: str, nBits: int, pubkey_hex: str, reward_satoshis: int) -> bytes:
    """Construct the raw coinbase transaction."""
    # Version
    tx = struct.pack('<I', 1)
    # Input count
    tx += ser_compact_size(1)
    # Previous output (null for coinbase)
    tx += b'\x00' * 32  # prev hash
    tx += struct.pack('<I', 0xffffffff)  # prev index
    # ScriptSig
    script_sig = create_coinbase_script(timestamp, nBits)
    tx += ser_string(script_sig)
    # Sequence
    tx += struct.pack('<I', 0xffffffff)
    # Output count
    tx += ser_compact_size(1)
    # Value
    tx += struct.pack('<Q', reward_satoshis)
    # ScriptPubKey: <pubkey> OP_CHECKSIG
    pubkey_bytes = bytes.fromhex(pubkey_hex)
    script_pubkey = bytes([len(pubkey_bytes)]) + pubkey_bytes + bytes([0xac])  # OP_CHECKSIG
    tx += ser_string(script_pubkey)
    # Locktime
    tx += struct.pack('<I', 0)
    return tx


def compute_merkle_root(tx_raw: bytes) -> bytes:
    """Merkle root of a single transaction is its double-SHA256 hash."""
    return double_sha256(tx_raw)


def serialize_block_header(nVersion: int, hashPrevBlock: bytes, hashMerkleRoot: bytes,
                           nTime: int, nBits: int, nNonce: int) -> bytes:
    """Serialize the 80-byte block header."""
    header = struct.pack('<i', nVersion)
    header += hashPrevBlock  # 32 bytes
    header += hashMerkleRoot  # 32 bytes
    header += struct.pack('<I', nTime)
    header += struct.pack('<I', nBits)
    header += struct.pack('<I', nNonce)
    return header


def mine_genesis(nVersion: int, hashPrevBlock: bytes, hashMerkleRoot: bytes,
                 nTime: int, nBits: int, target: int) -> tuple:
    """Mine the genesis block: find nNonce such that double_blake3(header) <= target."""
    nNonce = 0
    start = time.time()
    while nNonce < 2**32:
        header = serialize_block_header(nVersion, hashPrevBlock, hashMerkleRoot, nTime, nBits, nNonce)
        pow_hash = double_blake3(header)
        # Compare: pow_hash (LE in Bitcoin) vs target
        # Bitcoin stores hashes as LE uint256. We need to reverse for comparison.
        pow_hash_int = int.from_bytes(pow_hash, byteorder='little')
        if pow_hash_int <= target:
            elapsed = time.time() - start
            return nNonce, pow_hash, elapsed
        if nNonce % 1000000 == 0 and nNonce > 0:
            elapsed = time.time() - start
            rate = nNonce / elapsed
            print(f"  ... tried {nNonce:,} nonces ({rate:,.0f} H/s)", flush=True)
        nNonce += 1
    raise RuntimeError("Failed to find valid nonce in 2^32 attempts")


def main():
    # ---- b3chain Genesis Parameters ----
    timestamp = "b3chain genesis 2026 — conservative PoW in the spirit of Bitcoin"
    pubkey_hex = "04678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5f"
    nTime = 1739145600  # Feb 10, 2026 00:00:00 UTC
    nBits = 0x1e0fffff  # b3chain initial difficulty (BLAKE3 is faster, wider powLimit)
    nVersion = 1
    reward_satoshis = 50 * 100_000_000  # 50 B3C

    print("=== b3chain Genesis Block Generator ===")
    print(f"Timestamp: {timestamp}")
    print(f"nTime:     {nTime}")
    print(f"nBits:     0x{nBits:08x}")
    print()

    # Build coinbase transaction
    coinbase_tx = create_coinbase_tx(timestamp, nBits, pubkey_hex, reward_satoshis)
    print(f"Coinbase TX hex: {coinbase_tx.hex()}")
    print()

    # Compute merkle root (for single tx, it's the tx hash)
    merkle_root = compute_merkle_root(coinbase_tx)
    print(f"Merkle root (LE): {merkle_root.hex()}")
    print(f"Merkle root (BE): {merkle_root[::-1].hex()}")
    print()

    # Compute target from nBits
    target = uint256_from_compact(nBits)
    print(f"Target: {target:064x}")
    print()

    # Mine!
    hashPrevBlock = b'\x00' * 32
    print("Mining genesis block (double-BLAKE3-256)...")
    nNonce, pow_hash, elapsed = mine_genesis(nVersion, hashPrevBlock, merkle_root, nTime, nBits, target)

    # Also compute the identity hash (double-SHA256, used for block identification)
    header = serialize_block_header(nVersion, hashPrevBlock, merkle_root, nTime, nBits, nNonce)
    identity_hash = double_sha256(header)

    print()
    print("=== GENESIS BLOCK FOUND ===")
    print(f"nNonce:           {nNonce}")
    print(f"PoW hash (LE):    {pow_hash.hex()}")
    print(f"PoW hash (BE):    {pow_hash[::-1].hex()}")
    print(f"Identity hash:    {identity_hash[::-1].hex()}")
    print(f"Merkle root:      {merkle_root[::-1].hex()}")
    print(f"Time elapsed:     {elapsed:.1f}s")
    print()
    print("=== For chainparams.cpp ===")
    print(f'genesis = CreateGenesisBlock({nTime}, {nNonce}, 0x{nBits:08x}, {nVersion}, 50 * COIN);')
    print(f'// PoW hash: {pow_hash[::-1].hex()}')
    print(f'assert(consensus.hashGenesisBlock == uint256{{"{identity_hash[::-1].hex()}"}});')
    print(f'assert(genesis.hashMerkleRoot == uint256{{"{merkle_root[::-1].hex()}"}});')


if __name__ == '__main__':
    main()
