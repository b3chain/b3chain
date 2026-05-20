#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[M-1d] Internal miner end-to-end check (B3PoW-Scratch v1.1).

Spawns a fresh regtest b3chaind, mines blocks via each of the three
internal-miner RPCs (`generatetoaddress`, `generatetodescriptor`,
`generateblock`), then for every produced block independently
re-derives the block header and verifies:

  1. SHA256d(header) reversed == block hash returned by getblock
     (proves header reconstruction is correct and block.GetHash() is
      still SHA-256d, per the dual-hash design).

  2. b3pow_ref.b3pow_scratch(header, prev_block_hash).pow_hash <= target
     (proves the miner's PoW search used B3PoW-Scratch v1.1 - if the
      miner had used GetHash() or the old double-BLAKE3 the resulting
      nonce would only satisfy that algorithm and B3PoW would NOT
      generally be <= target).

  3. b3pow_hash != SHA256d(header)
     (proves GetPoWHash and GetHash are actually distinct algorithms,
      not aliased).

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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

from audit_common import (  # type: ignore
    AuditResult,
    RegtestNode,
    ensure_wallet,
    repo_root,
)

# b3pow_ref is the byte-for-byte reference implementation; import it
# from the in-tree miner subtree.
REF_DIR = repo_root() / "contrib" / "miner" / "b3miner-rtl" / "ref"
sys.path.insert(0, str(REF_DIR))
try:
    import b3pow_ref  # type: ignore
except ImportError as e:
    print(
        f"ERROR: cannot import b3pow_ref from {REF_DIR}: {e}\n"
        "Install blake3 (`pip3 install blake3`) and confirm the ref/ "
        "directory ships in your checkout.",
        file=sys.stderr,
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Hashing primitives
# ---------------------------------------------------------------------------

def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def target_from_nbits(nbits: int) -> int:
    exp = nbits >> 24
    mant = nbits & 0x7FFFFF
    if nbits & 0x800000:
        mant = -mant
    return mant << (8 * (exp - 3)) if exp > 3 else mant >> (8 * (3 - exp))


def serialize_header(h: dict) -> bytes:
    """Reconstruct an 80-byte header from a getblock(verbosity=1) dict."""
    return (
        struct.pack("<I", int(h["version"]))
        + bytes.fromhex(h.get("previousblockhash", "0" * 64))[::-1]
        + bytes.fromhex(h["merkleroot"])[::-1]
        + struct.pack(
            "<III", int(h["time"]), int(h["bits"], 16), int(h["nonce"]),
        )
    )


# Per-process pad cache: b3pow scratchpad init is ~5 ms in pure Python,
# but blocks share parents in batches, so we cache by prev_block_hash.
PAD_CACHE: dict[bytes, bytes] = {}


def b3pow_hash(header_bytes: bytes, prev_block_hash: bytes) -> bytes:
    pad = PAD_CACHE.get(prev_block_hash)
    if pad is None:
        pad = b3pow_ref.init_scratchpad(prev_block_hash)
        PAD_CACHE[prev_block_hash] = pad
    return b3pow_ref.b3pow_scratch(header_bytes, prev_block_hash, pad=pad).pow_hash


# ---------------------------------------------------------------------------
# Per-block verification
# ---------------------------------------------------------------------------

def verify_block(r: AuditResult, rpc, block_hash_hex: str, source_rpc: str) -> bool:
    block = rpc.getblock(block_hash_hex, 1)
    header_bytes = serialize_header(block)
    target = target_from_nbits(int(block["bits"], 16))
    prev = bytes.fromhex(block.get("previousblockhash", "0" * 64))[::-1]

    sha256d = double_sha256(header_bytes)
    sha256d_be = sha256d[::-1].hex()

    pow_hash = b3pow_hash(header_bytes, prev)
    pow_be = pow_hash[::-1].hex()
    pow_int = int.from_bytes(pow_hash, "little")

    short = block_hash_hex[:16] + "..."
    label_prefix = f"[M-1d/{source_rpc}] block {short}"

    ok1 = r.expect_eq(
        sha256d_be, block_hash_hex,
        f"{label_prefix}: SHA256d(header) == block.GetHash() (dual-hash ID stays SHA-256d)",
    )
    ok2 = r.expect(
        pow_int <= target,
        f"{label_prefix}: b3pow_scratch(header, prev) <= target (miner used B3PoW-Scratch)",
        f"pow_int={pow_int}, target={target}" if not (pow_int <= target) else "",
    )
    ok3 = r.expect(
        pow_be != sha256d_be,
        f"{label_prefix}: B3PoW != SHA256d (dual-hash methods are independent)",
    )
    return ok1 and ok2 and ok3


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    r = AuditResult("M-1d", "Internal miner end-to-end (B3PoW-Scratch v1.1)")
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
        print(f"  Verifying B3PoW + dual-hash design for {len(blocks)} blocks...")
        for source_rpc, h in blocks:
            verify_block(r, node.rpc, h, source_rpc)

        # Aggregate sanity assertions.
        r.expect(
            len(blocks) == 15,
            f"[M-1d] mined exactly 15 blocks across 3 RPCs (got {len(blocks)})",
        )
        per_rpc = {
            src: sum(1 for s, _ in blocks if s == src)
            for src in ("generatetoaddress", "generatetodescriptor", "generateblock")
        }
        r.expect(
            all(v == 5 for v in per_rpc.values()),
            f"[M-1d] each RPC produced 5 blocks ({per_rpc})",
        )
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
            "all per-block + aggregate checks PASS"
        )
    else:
        print(
            f"SUMMARY: {r.failed} check(s) FAILED across {len(blocks)} blocks "
            "(see PASS/FAIL log above)"
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
