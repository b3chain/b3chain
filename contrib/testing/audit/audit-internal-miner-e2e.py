#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[M-1d] Internal miner end-to-end check.

Spawns a fresh regtest b3chaind, mines blocks via each of the three
internal-miner RPCs (`generatetoaddress`, `generatetodescriptor`,
`generateblock`), then for every produced block independently
re-derives the block header and verifies:

  1. SHA256d(header) reversed == block hash returned by getblock
     (proves header reconstruction is correct and `block.GetHash()` is
      still SHA-256d, per the dual-hash design)

  2. BLAKE3(BLAKE3(header)) <= target_from_nbits(block.bits)
     (proves the miner's PoW search used BLAKE3d, not SHA-256d — if the
      miner had used GetHash() the resulting nonce would only satisfy
      SHA-256d <= target, and BLAKE3d would NOT generally be <= target)

  3. BLAKE3d(header) != SHA256d(header)
     (proves GetPoWHash and GetHash are actually distinct algorithms,
      not aliased)

This script is invoked by `audit-internal-miner.sh` with BINDIR set so
that `audit_common.find_binaries()` finds b3chaind.

Final line of stdout is `SUMMARY: <N> blocks across 3 RPCs, all PASS`
on success; the bash wrapper greps for it to populate the checklist.
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

# Make audit_common importable
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

from audit_common import (  # type: ignore
    AuditResult,
    RegtestNode,
    ensure_wallet,
)

try:
    import blake3 as _blake3
except ImportError:
    print("ERROR: python blake3 module missing. Install with: pip3 install blake3")
    sys.exit(2)


# ---------------------------------------------------------------------------
# Hashing primitives (copied here so this script has no other dependency
# besides audit_common + blake3; mirror contrib/testing/verify-blake3-pow.py)
# ---------------------------------------------------------------------------

def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def double_blake3(data: bytes) -> bytes:
    return _blake3.blake3(_blake3.blake3(data).digest()).digest()


def target_from_nbits(nbits: int) -> int:
    exponent = nbits >> 24
    mantissa = nbits & 0x7FFFFF
    if nbits & 0x800000:
        mantissa = -mantissa
    return mantissa << (8 * (exponent - 3))


def serialize_header(h: dict) -> bytes:
    """Reconstruct an 80-byte block header from a getblock(verbosity=1) dict."""
    version = int(h["version"])
    prev = bytes.fromhex(h.get("previousblockhash", "0" * 64))[::-1]
    merkle = bytes.fromhex(h["merkleroot"])[::-1]
    time_ = int(h["time"])
    bits = int(h["bits"], 16)
    nonce = int(h["nonce"])
    return (
        struct.pack("<I", version)
        + prev
        + merkle
        + struct.pack("<III", time_, bits, nonce)
    )


# ---------------------------------------------------------------------------
# Per-block verification
# ---------------------------------------------------------------------------

def verify_block(r: AuditResult, rpc, block_hash_hex: str, source_rpc: str) -> bool:
    """Verify one mined block. Returns True iff all three per-block checks hold."""
    block = rpc.getblock(block_hash_hex, 1)
    header_bytes = serialize_header(block)
    target = target_from_nbits(int(block["bits"], 16))

    sha256d = double_sha256(header_bytes)
    sha256d_be = sha256d[::-1].hex()

    blake3d = double_blake3(header_bytes)
    blake3d_be = blake3d[::-1].hex()
    blake3d_int = int.from_bytes(blake3d, "little")

    short = block_hash_hex[:16] + "..."
    label_prefix = f"[M-1d/{source_rpc}] block {short}"

    ok1 = r.expect_eq(
        sha256d_be, block_hash_hex,
        f"{label_prefix}: SHA256d(header) == block.GetHash() (dual-hash ID stays SHA-256d)",
    )
    ok2 = r.expect(
        blake3d_int <= target,
        f"{label_prefix}: BLAKE3(BLAKE3(header)) <= target (miner used BLAKE3d PoW)",
        f"blake3d_int={blake3d_int}, target={target}" if not (blake3d_int <= target) else "",
    )
    ok3 = r.expect(
        blake3d_be != sha256d_be,
        f"{label_prefix}: BLAKE3d != SHA256d (dual-hash methods are independent)",
    )
    return ok1 and ok2 and ok3


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    r = AuditResult("M-1d", "Internal miner end-to-end (BLAKE3 PoW)")
    node = RegtestNode("internal_miner")
    blocks: list[tuple[str, str]] = []  # (source_rpc, block_hash)
    try:
        node.start()
        wallet = ensure_wallet(node, "audit")
        addr = wallet.getnewaddress()

        print()
        print(f"  Mining 5 blocks via generatetoaddress to {addr}...")
        h1 = wallet.generatetoaddress(5, addr)
        for h in h1:
            blocks.append(("generatetoaddress", h))

        print(f"  Mining 5 blocks via generatetodescriptor addr({addr})...")
        h2 = node.rpc.generatetodescriptor(5, f"addr({addr})")
        for h in h2:
            blocks.append(("generatetodescriptor", h))

        print(f"  Mining 5 blocks via generateblock to {addr}...")
        for _ in range(5):
            res = node.rpc.generateblock(addr, [])
            blocks.append(("generateblock", res["hash"]))

        print()
        print(f"  Verifying BLAKE3d PoW + dual-hash design for {len(blocks)} blocks...")
        all_ok = True
        for source_rpc, h in blocks:
            if not verify_block(r, node.rpc, h, source_rpc):
                all_ok = False

        # Aggregate sanity assertions
        r.expect(
            len(blocks) == 15,
            f"[M-1d] mined exactly 15 blocks across 3 RPCs (got {len(blocks)})",
        )
        per_rpc = {src: sum(1 for s, _ in blocks if s == src)
                   for src in ("generatetoaddress", "generatetodescriptor", "generateblock")}
        r.expect(
            all(v == 5 for v in per_rpc.values()),
            f"[M-1d] each RPC produced 5 blocks ({per_rpc})",
        )

        # Best-block agrees with the last hash we received
        tip = node.rpc.getbestblockhash()
        r.expect(
            tip == blocks[-1][1],
            f"[M-1d] node tip equals last mined hash ({tip[:16]}...)",
        )

    finally:
        node.cleanup()

    code = r.finish()
    if code == 0:
        print(
            f"SUMMARY: {len(blocks)} blocks across 3 RPCs (5 each), "
            f"all per-block + aggregate checks PASS"
        )
    else:
        print(
            f"SUMMARY: {r.failed} check(s) FAILED across {len(blocks)} blocks "
            f"(see PASS/FAIL log above)"
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
