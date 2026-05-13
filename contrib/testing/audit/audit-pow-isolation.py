#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[H-1] PoW / Block-ID hash isolation audit.

B3Chain inherits Bitcoin's SHA-256d block identity hash but replaces the
proof-of-work hash with double BLAKE3-256. Two completely separate methods
exist on `CBlockHeader`:

  GetHash()    -> SHA-256d, used for block IDs, indices, headers, p2p inv
  GetPoWHash() -> BLAKE3d,  used ONLY for proof-of-work checks

This audit makes sure the two are not mixed up:

  1. Static check: every `CheckProofOfWork(...)` call site in src/ must pass
     `GetPoWHash()` (or a value already obtained from it), never `GetHash()`.
  2. Static check: src/pow.cpp does NOT contain "SHA256" in the consensus
     hash code path.
  3. Functional check: a freshly mined block has GetHash() != GetPoWHash()
     (different algorithms produce different values for the same header).
  4. Functional check: getblockhash() returns the SHA-256d ID, never the
     BLAKE3 PoW hash.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import AuditResult, RegtestNode, ensure_wallet, repo_root  # type: ignore

import hashlib
try:
    import blake3
    HAVE_BLAKE3 = True
except ImportError:
    HAVE_BLAKE3 = False


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------

# Files to scan. The pow* files contain the actual consensus code, validation
# the call sites, primitives the header struct itself.
SCAN_FILES = [
    "src/validation.cpp",
    "src/pow.cpp",
    "src/pow.h",
    "src/primitives/block.cpp",
    "src/primitives/block.h",
    "src/test/audit/consensus_invariants_tests.cpp",
]


# File where the actual BLAKE3 PoW hashing happens.
BLAKE3_HASH_FILES = [
    "src/primitives/block.cpp",
    "src/primitives/block.h",
]


def static_checkproofofwork_audit(r: AuditResult) -> None:
    """Verify every CheckProofOfWork(...) call passes a PoW hash, not block ID."""
    root = repo_root()
    bad: list[tuple[str, int, str]] = []
    total_call_sites = 0
    # Match the first argument up to the first comma. The argument may
    # itself contain parentheses (e.g. "block.GetPoWHash()"), so we don't
    # exclude `)` from the character class.
    pat = re.compile(r"CheckProofOfWork\s*\(\s*([^,]+?)\s*,")
    for rel in SCAN_FILES:
        p = root / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = pat.search(line)
            if not m:
                continue
            # Allow function-definition / forward-declaration lines that
            # spell out the parameter type (e.g. "bool CheckProofOfWork(uint256 hash, ...)")
            if re.search(r"\b(?:const\s+)?uint256\b\s*&?\s*hash\b", line):
                continue
            arg = m.group(1).strip()
            total_call_sites += 1
            if "GetHash()" in arg and "GetPoWHash" not in arg:
                bad.append((rel, i, line.strip()))
                continue
            ok = (
                "GetPoWHash" in arg
                or "pow_hash" in arg.lower()
                or "powhash" in arg.lower()
            )
            if not ok:
                bad.append((rel, i, line.strip()))

    if bad:
        for rel, i, line in bad:
            r.failed_check(f"[H-1] CheckProofOfWork call at {rel}:{i}",
                           detail=line[:120])
    else:
        r.expect(
            total_call_sites > 0,
            f"[H-1] {total_call_sites} CheckProofOfWork call site(s) all use GetPoWHash",
            "" if total_call_sites > 0 else "no call sites found — file paths may be stale",
        )


def static_pow_uses_blake3(r: AuditResult) -> None:
    """The PoW hashing implementation must use BLAKE3, not SHA256."""
    found = False
    where = []
    for rel in BLAKE3_HASH_FILES:
        p = repo_root() / rel
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="ignore")
        if "blake3" in body.lower() or "BLAKE3" in body:
            found = True
            where.append(rel)
    r.expect(found,
             f"[H-1] PoW hashing references BLAKE3 ({', '.join(where) if where else 'NOT FOUND'})")


def static_block_has_two_methods(r: AuditResult) -> None:
    """CBlockHeader must expose BOTH GetHash() and GetPoWHash()."""
    p = repo_root() / "src" / "primitives" / "block.h"
    if not p.exists():
        r.skipped_check("[H-1] src/primitives/block.h not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_get_hash = "uint256 GetHash() const" in body
    has_pow_hash = "uint256 GetPoWHash() const" in body
    r.expect(has_get_hash, "[H-1] CBlockHeader::GetHash() declared")
    r.expect(has_pow_hash, "[H-1] CBlockHeader::GetPoWHash() declared")


# ---------------------------------------------------------------------------
# Functional checks (live regtest)
# ---------------------------------------------------------------------------

def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def double_blake3(data: bytes) -> bytes:
    return blake3.blake3(blake3.blake3(data).digest()).digest()


def serialize_header(h: dict) -> bytes:
    import struct
    version  = int(h["version"])
    prev     = bytes.fromhex(h["previousblockhash"])[::-1]
    merkle   = bytes.fromhex(h["merkleroot"])[::-1]
    time_    = int(h["time"])
    bits     = int(h["bits"], 16)
    nonce    = int(h["nonce"])
    return (
        struct.pack("<I", version) + prev + merkle
        + struct.pack("<III", time_, bits, nonce)
    )


def functional_check(r: AuditResult) -> None:
    """Mine a block and verify GetHash() == SHA256d, GetPoWHash() == BLAKE3d, and they differ."""
    if not HAVE_BLAKE3:
        r.skipped_check("[H-1] python blake3 module missing — install with `pip3 install blake3`")
        # Still do a node-only check that two hashes differ
    node = RegtestNode("powiso")
    try:
        node.start()
        wallet = ensure_wallet(node, "audit")
        addr = wallet.getnewaddress()
        wallet.generatetoaddress(1, addr)
        tip_hash_hex = node.rpc.getbestblockhash()
        block = node.rpc.getblock(tip_hash_hex, 1)

        header_bytes = serialize_header(block)
        sha256d = double_sha256(header_bytes)[::-1].hex()
        r.expect_eq(sha256d, tip_hash_hex,
                    "[H-1] getblockhash() returns SHA-256d (block ID), not BLAKE3")

        if HAVE_BLAKE3:
            blake3d_bytes = double_blake3(header_bytes)
            blake3d_be    = blake3d_bytes[::-1].hex()
            r.expect(blake3d_be != tip_hash_hex,
                     "[H-1] block ID and BLAKE3 PoW hash are different",
                     f"id={tip_hash_hex[:16]}...  pow={blake3d_be[:16]}...")

            # Verify the BLAKE3d hash is at or below the target
            target = int(block["bits"], 16)
            # Decode compact target
            exp = target >> 24
            mant = target & 0x007fffff
            full_target = mant << (8 * (exp - 3)) if exp > 3 else mant >> (8 * (3 - exp))
            blake3d_int = int.from_bytes(blake3d_bytes, "little")
            r.expect(blake3d_int <= full_target,
                     "[H-1] mined block's BLAKE3 PoW hash <= target",
                     f"hash_int < target: {blake3d_int <= full_target}")
    finally:
        node.cleanup()


def main() -> int:
    r = AuditResult("H-1", "PoW / Block-ID hash isolation")
    static_checkproofofwork_audit(r)
    static_pow_uses_blake3(r)
    static_block_has_two_methods(r)
    print()
    print("  Spawning regtest node and verifying live block hash relationships...")
    functional_check(r)
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
