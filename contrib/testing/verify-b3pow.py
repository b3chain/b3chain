#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
B3Chain B3PoW-Scratch v1.1 Proof-of-Work Verification

Standalone script to verify:
  1. The B3PoW-Scratch v1.1 reference implementation (via b3pow_ref).
  2. Every entry in the canonical consensus vector set
     (src/test/data/b3pow_consensus_vectors.json).
  3. (Optional) Live block verification from a running node:
     - getblockhash() returns SHA-256d (block identity hash).
     - GetPoWHash() (i.e. b3pow_ref.b3pow_scratch) <= target.

The Python reference at contrib/miner/b3miner-rtl/ref/b3pow_ref.py is the
single source of truth; this script imports it directly rather than
hard-coding constants, so any change to the algorithm shows up as a
parity mismatch against the C++ port test vectors.

Usage:
  python3 verify-b3pow.py                    # vectors only
  python3 verify-b3pow.py --rpc-port=18545   # + live block checks

Requires:
  pip3 install blake3
  (and the b3pow_ref module on contrib/miner/b3miner-rtl/ref/, ships with the repo)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate and import b3pow_ref + consensus vectors
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REF_DIR = REPO / "contrib" / "miner" / "b3miner-rtl" / "ref"
VECTORS_JSON = REPO / "src" / "test" / "data" / "b3pow_consensus_vectors.json"

sys.path.insert(0, str(REF_DIR))
try:
    import b3pow_ref  # type: ignore
except ImportError as e:
    print(f"ERROR: cannot import b3pow_ref from {REF_DIR}: {e}", file=sys.stderr)
    print(
        "Hint: this script must be run from a b3chain checkout that includes "
        "contrib/miner/b3miner-rtl/ref/b3pow_ref.py.",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    import blake3 as _blake3  # noqa: F401  (used transitively by b3pow_ref)
except ImportError:
    print("ERROR: install blake3 first:  pip3 install blake3", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def double_sha256(data: bytes) -> bytes:
    """Double SHA-256, used by B3Chain for block identity hashes only."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def hash_to_hex(h: bytes) -> str:
    """Convert raw-LE hash bytes to big-endian display hex (block-explorer style)."""
    return h[::-1].hex()


def target_from_nbits(nbits: int) -> int:
    """Decode compact nBits into a full 256-bit target."""
    exponent = nbits >> 24
    mantissa = nbits & 0x7FFFFF
    if nbits & 0x800000:
        mantissa = -mantissa
    return mantissa << (8 * (exponent - 3)) if exponent > 3 else mantissa >> (8 * (3 - exponent))


PASS = 0
FAIL = 0


def check(description: str, actual: str, expected: str) -> None:
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  \033[32mPASS\033[0m: {description}")
    else:
        FAIL += 1
        print(f"  \033[31mFAIL\033[0m: {description}")
        print(f"         got:      {actual}")
        print(f"         expected: {expected}")


def check_bool(description: str, actual: bool, expected: bool) -> None:
    """Boolean check (e.g. expected_check_pow)."""
    check(description, str(actual).lower(), str(expected).lower())


# ---------------------------------------------------------------------------
# Vector-driven tests
# ---------------------------------------------------------------------------

def load_vectors() -> dict:
    """Load and minimally validate consensus_vectors.json."""
    if not VECTORS_JSON.exists():
        print(f"ERROR: consensus vectors not found at {VECTORS_JSON}", file=sys.stderr)
        print("Hint: run `python3 contrib/miner/b3miner-rtl/ref/gen_vectors.py` first.",
              file=sys.stderr)
        sys.exit(2)
    with open(VECTORS_JSON, "r", encoding="utf-8") as f:
        v = json.load(f)
    assert "schema_version" in v and "entries" in v, "consensus_vectors.json missing schema_version/entries"
    return v


def test_reference_self_check() -> None:
    """Quick smoke that b3pow_ref is importable and produces stable output."""
    print("\n[1/3] b3pow_ref self-check")

    spec = f"0x{b3pow_ref.SPEC_VERSION:08x}"
    check("SPEC_VERSION", spec, "0x00010101")

    # Hash the zero header twice with the zero prev hash and confirm
    # determinism. We do not pin the absolute hex here; the
    # authoritative pinning lives in consensus_vectors.json.
    header = b"\x00" * 80
    prev = b"\x00" * 32
    a = b3pow_ref.b3pow_scratch(header, prev).pow_hash
    b = b3pow_ref.b3pow_scratch(header, prev).pow_hash
    check("b3pow_ref deterministic (zero-header)", a.hex(), b.hex())


def test_consensus_vectors(vectors: dict) -> None:
    """Recompute every consensus_vectors.json entry and confirm parity."""
    print("\n[2/3] B3PoW-Scratch consensus vectors")
    schema = vectors["schema_version"]
    spec_in_json = vectors["spec_version"]
    print(f"  Loaded schema_version={schema}, spec_version={spec_in_json}")
    spec_expected = f"0x{b3pow_ref.SPEC_VERSION:08x}"
    check("spec_version matches b3pow_ref", spec_in_json, spec_expected)

    for entry in vectors["entries"]:
        name = entry["name"]
        header = bytes.fromhex(entry["header_hex"])
        prev = bytes.fromhex(entry["prev_block_hash_hex"])
        expected_pow_hex = entry["expected_pow_hash_hex"]
        nbits = int(entry["nbits_hex"], 16)
        expected_check_pow = bool(entry["expected_check_pow"])

        assert len(header) == 80, f"{name}: header_hex must be 80 bytes"
        assert len(prev) == 32, f"{name}: prev_block_hash_hex must be 32 bytes"

        # 1. Recompute the pow_hash; must equal the stored expected hex.
        result = b3pow_ref.b3pow_scratch(header, prev)
        actual_pow_hex = result.pow_hash.hex()
        check(f"{name}: b3pow_scratch hash", actual_pow_hex, expected_pow_hex)

        # 2. Boolean: does the computed hash satisfy nBits?
        pow_int = int.from_bytes(result.pow_hash, "little")
        target = target_from_nbits(nbits)
        check_bool(f"{name}: pow_hash <= target", pow_int <= target, expected_check_pow)


def test_live_blocks(rpc_port: int) -> None:
    """Verify the live node's block IDs and PoW match the algorithm."""
    print(f"\n[3/3] Live block verification (RPC port {rpc_port})")

    def rpc_call(method: str, params=None):
        payload = json.dumps({
            "jsonrpc": "1.0", "id": "verify", "method": method,
            "params": params or []
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{rpc_port}/",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        cookie_paths = [
            os.path.expanduser("~/.b3chain/regtest/.cookie"),
            "/tmp/b3chain_regtest_sim/node0/regtest/.cookie",
        ]
        for cp in cookie_paths:
            if os.path.isfile(cp):
                cred = open(cp).read().strip()
                req.add_header(
                    "Authorization",
                    "Basic " + base64.b64encode(cred.encode()).decode(),
                )
                break
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["result"]

    try:
        info = rpc_call("getblockchaininfo")
    except Exception as e:
        print(f"  \033[33mSKIP\033[0m: cannot connect to node ({e})")
        return

    height = info["blocks"]
    chain = info["chain"]
    print(f"  Connected to {chain} chain at height {height}")

    # Verify a few representative heights.
    blocks_to_check = [0, 1, min(5, height), min(50, height)]
    blocks_to_check = sorted({b for b in blocks_to_check if b <= height})

    # Pristine pad cache so siblings of the same parent skip the 1 MB
    # BLAKE3-XOF init. The reference b3pow_scratch() mutates the pad
    # in-place per the spec's RMW step, so we must hand out a fresh
    # copy of the pristine init for every hash.
    pad_cache: dict[bytes, bytes] = {}

    def get_fresh_pad(prev: bytes) -> bytearray:
        p = pad_cache.get(prev)
        if p is None:
            p = bytes(b3pow_ref.init_scratchpad(prev))
            pad_cache[prev] = p
        return bytearray(p)

    for h in blocks_to_check:
        block_hash_hex = rpc_call("getblockhash", [h])
        block = rpc_call("getblockheader", [block_hash_hex, True])

        # Reconstruct the 80-byte wire header.
        header = struct.pack("<i", block["version"])
        prev = bytes.fromhex(block.get("previousblockhash", "0" * 64))[::-1]
        header += prev
        header += bytes.fromhex(block["merkleroot"])[::-1]
        header += struct.pack(
            "<III", block["time"], int(block["bits"], 16), block["nonce"],
        )

        # Identity hash = SHA-256d.
        computed_id = hash_to_hex(double_sha256(header))
        check(f"block {h}: getblockhash == SHA256d(header)", computed_id, block_hash_hex)

        # PoW hash = B3PoW-Scratch(header, prev). Reuse the pristine
        # init per parent, but pass a fresh copy each call.
        pad = get_fresh_pad(prev)
        pow_hash = b3pow_ref.b3pow_scratch(header, prev, pad=pad).pow_hash
        pow_int = int.from_bytes(pow_hash, "little")
        target = target_from_nbits(int(block["bits"], 16))
        check_bool(f"block {h}: pow_hash <= target", pow_int <= target, True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify B3Chain B3PoW-Scratch v1.1 implementation",
    )
    parser.add_argument(
        "--rpc-port", type=int, default=0,
        help="RPC port of a running b3chaind node (optional, enables live checks)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(" B3Chain B3PoW-Scratch v1.1 Verification")
    print("=" * 60)

    vectors = load_vectors()
    test_reference_self_check()
    test_consensus_vectors(vectors)

    if args.rpc_port:
        test_live_blocks(args.rpc_port)
    else:
        print("\n[3/3] Live block verification")
        print("  \033[33mSKIP\033[0m: no --rpc-port specified")

    print()
    print("=" * 60)
    total = PASS + FAIL
    print(f" RESULTS: {PASS}/{total} passed, {FAIL} failed")
    print("=" * 60)

    if FAIL:
        print(f" \033[31m{FAIL} test(s) failed\033[0m")
        sys.exit(1)
    print(f" \033[32mAll tests passed!\033[0m")


if __name__ == "__main__":
    main()
