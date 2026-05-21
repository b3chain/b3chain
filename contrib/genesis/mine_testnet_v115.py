#!/usr/bin/env python3
"""Mine testnet genesis only (v1.1.5 powLimit 0x1f00ffff)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mine_all_genesis import (  # noqa: E402
    create_coinbase_tx,
    double_sha256,
    mine_genesis,
    uint256_from_compact,
)

timestamp_bytes = (
    b"b3chain genesis 2026 \xe2\x80\x94 conservative PoW in the spirit of Bitcoin"
)
pubkey_hex = (
    "04678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4"
    "cef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5f"
)

nTime, nBits = 1739145601, 0x1F00FFFF
coinbase_tx = create_coinbase_tx(timestamp_bytes, nBits, pubkey_hex, 50 * 100_000_000)
merkle_root = double_sha256(coinbase_tx)
target = uint256_from_compact(nBits)

print(f"Merkle root: {merkle_root[::-1].hex()}")
print(f"Mining testnet at 0x{nBits:08x}...")
nNonce, pow_hash, identity_hash, elapsed = mine_genesis(merkle_root, nTime, nBits, target)
print(f"Found! nNonce={nNonce}, time={elapsed:.1f}s")
print(f"PoW hash:      {pow_hash[::-1].hex()}")
print(f"Identity hash: {identity_hash[::-1].hex()}")
print()
print(f"  genesis = CreateGenesisBlock({nTime}, {nNonce}, 0x{nBits:08x}, 1, 50 * COIN);")
print(f'  assert(consensus.hashGenesisBlock == uint256{{"{identity_hash[::-1].hex()}"}});')
print(f'  assert(genesis.hashMerkleRoot == uint256{{"{merkle_root[::-1].hex()}"}});')
