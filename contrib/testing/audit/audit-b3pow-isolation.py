#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[H-1] PoW / Block-ID hash isolation audit (B3PoW-Scratch v1.1).

B3Chain inherits Bitcoin's SHA-256d block identity hash but replaces
the proof-of-work hash with B3PoW-Scratch v1.1 (a memory-hard BLAKE3
variant with a 1 MB scratchpad; see
contrib/miner/b3miner-rtl/SPEC.md). Two completely separate methods
exist on `CBlockHeader`:

  GetHash()    -> SHA-256d, used for block IDs, headers, p2p inv, ...
  GetPoWHash() -> B3PoW-Scratch, used ONLY for proof-of-work checks

This audit verifies the two are not confused:

  H-1 (static): every `CheckProofOfWork(...)` call site in src/ must
                pass `GetPoWHash()` output (or a value derived from
                it), never `GetHash()`.
  H-1 (static): src/primitives/block.cpp uses the b3pow_scratch port
                rather than vanilla BLAKE3 in the PoW path.
  H-1 (static): src/primitives/block.h declares the new 4-arg
                GetPoWHash signature (prev_block_hash, pad, budget,
                out_exceeded).
  H-1 (functional): getblockhash() returns SHA-256d, GetPoWHash()
                via b3pow_ref agrees with the running node, and the
                two hashes never collide.

Sub-checks added since v1.1 (kept inside H-1 so the master checklist
ID is stable):
  H-1.1: BlockValidationResult::BLOCK_POW_BUDGET is wired through
         MaybePunishNodeForBlock in src/net_processing.cpp.
  H-1.2: ChainstateManager owns a b3pow::Cache (LRU scratchpad cache
         keyed by prev_block_hash, depth from b3pow_cache_depth).
  H-1.3: MAX_B3POW_VERIFY_PER_BATCH is enforced in
         ProcessHeadersMessage in src/net_processing.cpp.
"""

from __future__ import annotations

import hashlib
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

from audit_common import (  # type: ignore # noqa: E402
    AuditResult,
    RegtestNode,
    ensure_wallet,
    repo_root,
)

# Make b3pow_ref importable for the functional check.
REF_DIR = repo_root() / "contrib" / "miner" / "b3miner-rtl" / "ref"
sys.path.insert(0, str(REF_DIR))
try:
    import b3pow_ref  # type: ignore
    HAVE_B3POW = True
except ImportError:
    HAVE_B3POW = False


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------

SCAN_FILES = [
    "src/validation.cpp",
    "src/pow.cpp",
    "src/pow.h",
    "src/primitives/block.cpp",
    "src/primitives/block.h",
    "src/rpc/mining.cpp",
    "src/test/util/pow.h",
    "src/test/audit/consensus_invariants_tests.cpp",
]

# B3PoW-Scratch port lives here; the PoW path in block.cpp must include it
# rather than the bare BLAKE3 library.
B3POW_HASH_FILES = [
    "src/primitives/block.cpp",
    "src/primitives/block.h",
]


def static_checkproofofwork_audit(r: AuditResult) -> None:
    """Every CheckProofOfWork(...) call passes a PoW hash, not a block ID."""
    root = repo_root()
    bad: list[tuple[str, int, str]] = []
    total_call_sites = 0
    pat = re.compile(r"CheckProofOfWork\s*\(\s*([^,]+?)\s*,")
    for rel in SCAN_FILES:
        p = root / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = pat.search(line)
            if not m:
                continue
            # Allow function-definition / forward-declaration lines.
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
                or "*pow_opt" in arg
                or "*pow_hash_opt" in arg
            )
            if not ok:
                bad.append((rel, i, line.strip()))

    if bad:
        for rel, i, line in bad:
            r.failed_check(
                f"[H-1] CheckProofOfWork call at {rel}:{i}",
                detail=line[:120],
            )
    else:
        r.expect(
            total_call_sites > 0,
            f"[H-1] {total_call_sites} CheckProofOfWork call site(s) all use a PoW hash",
            "" if total_call_sites > 0 else "no call sites found - file paths may be stale",
        )


def static_pow_uses_b3pow_scratch(r: AuditResult) -> None:
    """The PoW path in primitives/block.* must use b3pow_scratch."""
    found = False
    where: list[str] = []
    for rel in B3POW_HASH_FILES:
        p = repo_root() / rel
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="ignore")
        if "b3pow" in body or "b3pow_scratch" in body or "<crypto/b3pow_scratch.h>" in body:
            found = True
            where.append(rel)
    r.expect(
        found,
        f"[H-1] PoW path references b3pow_scratch ({', '.join(where) if where else 'NOT FOUND'})",
    )


def static_block_has_both_methods(r: AuditResult) -> None:
    """CBlockHeader must declare BOTH GetHash() and the v1.1 GetPoWHash(...)."""
    p = repo_root() / "src" / "primitives" / "block.h"
    if not p.exists():
        r.skipped_check("[H-1] src/primitives/block.h not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_get_hash = "uint256 GetHash() const" in body
    # The v1.1 GetPoWHash signature takes prev_block_hash + pad + budget + out_exceeded.
    has_pow_hash = "GetPoWHash(" in body and "prev_block_hash" in body and "budget" in body
    r.expect(has_get_hash, "[H-1] CBlockHeader::GetHash() declared")
    r.expect(
        has_pow_hash,
        "[H-1] CBlockHeader::GetPoWHash(prev_block_hash, pad, budget, out_exceeded) declared",
    )


def static_budget_routed_to_misbehaving(r: AuditResult) -> None:
    """[H-1.1] BLOCK_POW_BUDGET routes to Misbehaving in net_processing.cpp."""
    p = repo_root() / "src" / "net_processing.cpp"
    if not p.exists():
        r.skipped_check("[H-1.1] src/net_processing.cpp not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_case = "BlockValidationResult::BLOCK_POW_BUDGET" in body
    has_misbehaving = 'Misbehaving(*peer, "b3pow-budget-exceeded")' in body
    r.expect(
        has_case and has_misbehaving,
        "[H-1.1] BLOCK_POW_BUDGET routes to Misbehaving(\"b3pow-budget-exceeded\")",
    )


def static_chainstate_owns_b3pow_cache(r: AuditResult) -> None:
    """[H-1.2] ChainstateManager owns a b3pow::Cache."""
    p = repo_root() / "src" / "validation.h"
    if not p.exists():
        r.skipped_check("[H-1.2] src/validation.h not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_decl = "b3pow::Cache" in body and "m_b3pow_cache" in body
    r.expect(has_decl, "[H-1.2] ChainstateManager::m_b3pow_cache declared")


def static_headers_sync_cap(r: AuditResult) -> None:
    """[H-1.3] MAX_B3POW_VERIFY_PER_BATCH enforced in ProcessHeadersMessage."""
    p = repo_root() / "src" / "net_processing.cpp"
    if not p.exists():
        r.skipped_check("[H-1.3] src/net_processing.cpp not found", "")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_cap = "MAX_B3POW_VERIFY_PER_BATCH" in body
    has_resize = "headers.resize(MAX_B3POW_VERIFY_PER_BATCH)" in body
    r.expect(
        has_cap and has_resize,
        "[H-1.3] MAX_B3POW_VERIFY_PER_BATCH caps HEADERS batches",
    )


# ---------------------------------------------------------------------------
# Functional checks (live regtest)
# ---------------------------------------------------------------------------

def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def serialize_header(h: dict) -> bytes:
    return (
        struct.pack("<I", int(h["version"]))
        + bytes.fromhex(h["previousblockhash"])[::-1]
        + bytes.fromhex(h["merkleroot"])[::-1]
        + struct.pack(
            "<III",
            int(h["time"]),
            int(h["bits"], 16),
            int(h["nonce"]),
        )
    )


def target_from_nbits(nbits: int) -> int:
    exp = nbits >> 24
    mant = nbits & 0x7FFFFF
    return mant << (8 * (exp - 3)) if exp > 3 else mant >> (8 * (3 - exp))


def functional_check(r: AuditResult) -> None:
    """Mine a block; verify identity stays SHA-256d and PoW is B3PoW-Scratch <= target."""
    if not HAVE_B3POW:
        r.skipped_check(
            "[H-1] b3pow_ref unavailable - functional check skipped "
            "(ensure contrib/miner/b3miner-rtl/ref/ is present and `pip3 install blake3`)",
            "",
        )
        return
    node = RegtestNode("b3powiso")
    try:
        node.start()
        wallet = ensure_wallet(node, "audit")
        addr = wallet.getnewaddress()
        wallet.generatetoaddress(1, addr)

        tip_hash_hex = node.rpc.getbestblockhash()
        block = node.rpc.getblock(tip_hash_hex, 1)
        header_bytes = serialize_header(block)

        # Identity hash MUST still be SHA-256d.
        sha256d = double_sha256(header_bytes)[::-1].hex()
        r.expect_eq(
            sha256d,
            tip_hash_hex,
            "[H-1] getblockhash() returns SHA-256d (block ID), not B3PoW",
        )

        # PoW hash via b3pow_ref MUST satisfy the target.
        prev = bytes.fromhex(block["previousblockhash"])[::-1]
        pow_hash = b3pow_ref.b3pow_scratch(header_bytes, prev).pow_hash
        pow_be = pow_hash[::-1].hex()
        pow_int = int.from_bytes(pow_hash, "little")
        target = target_from_nbits(int(block["bits"], 16))

        r.expect(
            pow_be != tip_hash_hex,
            "[H-1] block ID and B3PoW hash are different",
            f"id={tip_hash_hex[:16]}... pow={pow_be[:16]}...",
        )
        r.expect(
            pow_int <= target,
            "[H-1] mined block's B3PoW hash <= target",
            f"pow_int <= target: {pow_int <= target}",
        )
    finally:
        node.cleanup()


def main() -> int:
    r = AuditResult("H-1", "PoW / Block-ID isolation (B3PoW-Scratch v1.1)")
    static_checkproofofwork_audit(r)
    static_pow_uses_b3pow_scratch(r)
    static_block_has_both_methods(r)
    static_budget_routed_to_misbehaving(r)
    static_chainstate_owns_b3pow_cache(r)
    static_headers_sync_cap(r)
    print()
    print("  Spawning regtest node and verifying live block hash relationships...")
    functional_check(r)
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
