#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
B3Chain BLAKE3 Proof-of-Work Verification

Standalone script to verify:
  1. BLAKE3 hash algorithm correctness (test vectors)
  2. Double BLAKE3-256 construction
  3. Block header PoW hashing
  4. (Optional) Live block verification from a running node

Usage:
  python3 verify-blake3-pow.py                  # Test vectors only
  python3 verify-blake3-pow.py --rpc-port=18545 # + live block checks

Requires: pip3 install blake3
"""

import argparse
import hashlib
import json
import struct
import sys
import urllib.request

try:
    import blake3 as _blake3
except ImportError:
    print("ERROR: Install blake3 first:  pip3 install blake3")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def blake3_hash(data: bytes) -> bytes:
    """Single BLAKE3-256 hash."""
    return _blake3.blake3(data).digest()


def double_blake3(data: bytes) -> bytes:
    """Double BLAKE3-256: BLAKE3(BLAKE3(data))."""
    return blake3_hash(blake3_hash(data))


def double_sha256(data: bytes) -> bytes:
    """Double SHA-256 (Bitcoin identity hash)."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def hash_to_hex(h: bytes) -> str:
    """Convert hash bytes to big-endian display hex (like block explorers)."""
    return h[::-1].hex()


def target_from_nbits(nbits: int) -> int:
    """Decode compact nBits to a full 256-bit target."""
    exponent = nbits >> 24
    mantissa = nbits & 0x7FFFFF
    if nbits & 0x800000:
        mantissa = -mantissa
    return mantissa << (8 * (exponent - 3))


# ---------------------------------------------------------------------------
# Test vectors
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0


def check(description: str, actual: str, expected: str):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  \033[32mPASS\033[0m: {description}")
    else:
        FAIL += 1
        print(f"  \033[31mFAIL\033[0m: {description}")
        print(f"         got:      {actual}")
        print(f"         expected: {expected}")


def test_single_blake3():
    """Verify single BLAKE3 against known vectors."""
    print("\n[1/4] Single BLAKE3-256 vectors")

    h = blake3_hash(b"").hex()
    check("BLAKE3('')", h,
          "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262")

    h = blake3_hash(b"b3chain").hex()
    check("BLAKE3('b3chain')", h,
          "492530272073ef2fb434ca4d9492bcea09502b24642b7e04021892bdda2aa806")

    h = blake3_hash(b"abc").hex()
    check("BLAKE3('abc')", h,
          "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85")


def test_double_blake3():
    """Verify double BLAKE3 construction."""
    print("\n[2/4] Double BLAKE3-256 vectors")

    h = double_blake3(b"").hex()
    check("BLAKE3(BLAKE3(''))", h,
          "82878ed8a480ee41775636820e05a934ca5c747223ca64306658ee5982e6c227")

    h = double_blake3(b"b3chain").hex()
    check("BLAKE3(BLAKE3('b3chain'))", h,
          "f09be63a21ff0bc5646b5ddcadef1c43f8e0e47815793cff909cab0a345396d3")


def test_block_header_pow():
    """Verify PoW hash for known block headers."""
    print("\n[3/4] Block header PoW hash vectors")

    # 80 zero bytes
    header = b'\x00' * 80
    pow_h = hash_to_hex(double_blake3(header))
    id_h = hash_to_hex(double_sha256(header))
    check("80-zero-bytes PoW hash", pow_h,
          "fb6d63b21d8c9f215de0e4fd9f4d0e7ed53ff023c7243e76f5a7367b2a4507b6")
    check("80-zero-bytes ID hash", id_h,
          "14508459b221041eab257d2baaa7459775ba748246c8403609eb708f0e57e74b")

    # Version=1, rest zeros
    header = struct.pack('<i', 1) + b'\x00' * 76
    pow_h = hash_to_hex(double_blake3(header))
    id_h = hash_to_hex(double_sha256(header))
    check("version=1 PoW hash", pow_h,
          "a8b60a455b3576a701ed73ad8ebf838839917a0331bfb6dfa99b77641c858c61")
    check("version=1 ID hash", id_h,
          "4ddd9f0855d58a375be5a763e5f51ece853d30525fcd9a3e477c2194fedb549f")


def test_live_blocks(rpc_port: int):
    """Fetch blocks from a running node and verify their PoW hashes."""
    print(f"\n[4/4] Live block verification (RPC port {rpc_port})")

    def rpc_call(method, params=None):
        payload = json.dumps({
            "jsonrpc": "1.0", "id": "verify", "method": method,
            "params": params or []
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{rpc_port}/",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        # Try cookie auth
        import os
        cookie_paths = [
            os.path.expanduser("~/.b3chain/regtest/.cookie"),
            "/tmp/b3chain_regtest_sim/node0/regtest/.cookie",
        ]
        for cp in cookie_paths:
            if os.path.isfile(cp):
                import base64
                cred = open(cp).read().strip()
                req.add_header("Authorization",
                               "Basic " + base64.b64encode(cred.encode()).decode())
                break
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["result"]

    try:
        info = rpc_call("getblockchaininfo")
    except Exception as e:
        print(f"  \033[33mSKIP\033[0m: Cannot connect to node ({e})")
        return

    height = info["blocks"]
    chain = info["chain"]
    print(f"  Connected to {chain} chain at height {height}")

    # Verify a few blocks
    blocks_to_check = [0, 1, min(100, height), min(1000, height)]
    blocks_to_check = sorted(set(b for b in blocks_to_check if b <= height))

    for h in blocks_to_check:
        block_hash = rpc_call("getblockhash", [h])
        block = rpc_call("getblockheader", [block_hash, True])

        # Reconstruct header bytes
        header = struct.pack('<i', block["version"])
        prev = bytes.fromhex(block.get("previousblockhash",
                                        "0" * 64))[::-1]
        header += prev
        header += bytes.fromhex(block["merkleroot"])[::-1]
        header += struct.pack('<III', block["time"],
                              int(block["bits"], 16), block["nonce"])

        # Verify identity hash
        computed_id = hash_to_hex(double_sha256(header))
        check(f"Block {h} identity hash", computed_id, block_hash)

        # Verify PoW
        pow_hash = double_blake3(header)
        pow_int = int.from_bytes(pow_hash, 'little')
        target = target_from_nbits(int(block["bits"], 16))
        if pow_int <= target:
            check(f"Block {h} PoW valid", "valid", "valid")
        else:
            check(f"Block {h} PoW valid", "INVALID", "valid")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Verify B3Chain BLAKE3 PoW implementation")
    parser.add_argument("--rpc-port", type=int, default=0,
                        help="RPC port of a running b3chaind node (optional)")
    args = parser.parse_args()

    print("=" * 60)
    print(" B3Chain BLAKE3 PoW Verification")
    print("=" * 60)

    test_single_blake3()
    test_double_blake3()
    test_block_header_pow()

    if args.rpc_port:
        test_live_blocks(args.rpc_port)
    else:
        print("\n[4/4] Live block verification")
        print("  \033[33mSKIP\033[0m: No --rpc-port specified")

    print()
    print("=" * 60)
    total = PASS + FAIL
    print(f" RESULTS: {PASS}/{total} passed, {FAIL} failed")
    print("=" * 60)

    if FAIL:
        print(f" \033[31m{FAIL} test(s) failed\033[0m")
        sys.exit(1)
    else:
        print(f" \033[32mAll tests passed!\033[0m")


if __name__ == "__main__":
    main()
