"""b3pow_ref.py -- authoritative Python reference for B3PoW-Scratch v1.1.

This module is THE spec (see ../SPEC.md). All RTL modules in ../rtl/
must produce byte-identical results, and CI enforces that via the
hex vectors emitted by ../gen_vectors.py.

The implementation is deliberately verbose:

* No NumPy.  Plain Python ints + struct.pack so the algorithm can be
  cross-checked by anyone reading this file -- it doubles as the
  reference for future b3chaind C++ validator and pool implementers.
* No micro-optimisations.  Speed is irrelevant; clarity and parity
  with SPEC.md are.

Run the tests:

    cd b3chain/contrib/miner/b3miner-rtl/ref
    python -m pytest -q

Dependencies: pure-Python `blake3` (PyPI).  See requirements.txt.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import List, Tuple

try:
    from blake3 import blake3 as _blake3
except ImportError as exc:  # pragma: no cover -- helpful failure
    raise SystemExit(
        "The 'blake3' PyPI package is required.\n"
        "    pip install -r requirements.txt"
    ) from exc


# ----------------------------------------------------------------------------
# Locked constants (mirror of ../rtl/params_pkg.sv and ../SPEC.md §3)
# ----------------------------------------------------------------------------
SPEC_VERSION = 0x00010101  # 1.1.1 (F-1: ITER_MUL[7] distinct)
REG_ID_MAGIC = 0xB3110002  # build 0002 (rebuild required for ITER_MUL[7])

SCRATCH_BYTES = 1_048_576       # 1 MB
LANES = 8
LANE_BYTES = SCRATCH_BYTES // LANES        # 131072
BLOCK_BYTES = 64
LANE_BLOCKS = LANE_BYTES // BLOCK_BYTES    # 2048
ADDR_BITS = (LANE_BLOCKS - 1).bit_length() # 11
ITERATIONS = 2048
INNER_ROUNDS = 2
LANE_BITS = 256
STATE_BITS = LANE_BITS * LANES             # 2048
SCRATCH_BLOCKS = SCRATCH_BYTES // BLOCK_BYTES  # 16384

# BLAKE3 primitive
BLAKE3_IV = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)
BLAKE3_PERM = (2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8)
BLAKE3_ROUNDS = 7
FLAG_CHUNK_START = 0x01
FLAG_CHUNK_END = 0x02
FLAG_ROOT = 0x08

# wyhash secret table (SPEC.md §3).  All entries are odd, well-distributed,
# pairwise distinct.  L=7 used to be a duplicate of L=1 and was fixed in
# v1.1.1 (F-1, see doc/security/B3POW-51-ATTACK-ANALYSIS.md).
ITER_MUL: Tuple[int, ...] = (
    0xA0761D6478BD642F,
    0xE7037ED1A0B428DB,
    0x8EBC6AF09C88C6E3,
    0x589965CC75374CC3,
    0x1D8E4E27C47D124F,
    0xEB44ACCAB455D165,
    0xC863B19A77C75D70,
    0x6E5C6F88AA5BDA77,
)
assert len(ITER_MUL) == LANES
assert len(set(ITER_MUL)) == LANES, "ITER_MUL entries must be pairwise distinct"

# Lane shuffle permutation applied between inner rounds (SPEC §6.5).
# Chosen so each lane sees every other lane within INNER_ROUNDS=2 with the
# minimum number of swaps.  Permutation: L' = (5*L + 1) mod 8.
LANE_SHUFFLE: Tuple[int, ...] = (1, 6, 3, 0, 5, 2, 7, 4)
assert sorted(LANE_SHUFFLE) == list(range(LANES))


# ----------------------------------------------------------------------------
# Low-level helpers
# ----------------------------------------------------------------------------
def mask32(x: int) -> int:
    return x & 0xFFFFFFFF


def mask64(x: int) -> int:
    return x & 0xFFFFFFFFFFFFFFFF


def rotr32(x: int, n: int) -> int:
    x &= 0xFFFFFFFF
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def rotr64(x: int, n: int) -> int:
    x &= 0xFFFFFFFFFFFFFFFF
    return ((x >> n) | (x << (64 - n))) & 0xFFFFFFFFFFFFFFFF


def le_words(buf: bytes) -> List[int]:
    """Unpack a byte buffer (multiple of 4) into a list of u32-LE words."""
    assert len(buf) % 4 == 0
    return list(struct.unpack(f"<{len(buf)//4}I", buf))


def pack_le_words(words) -> bytes:
    return struct.pack(f"<{len(words)}I", *words)


# ----------------------------------------------------------------------------
# BLAKE3 round / compress  (matches ../b3chain-gpuminer/kernels/blake3.cuh)
# ----------------------------------------------------------------------------
def g(s: List[int], a: int, b: int, c: int, d: int, mx: int, my: int) -> None:
    s[a] = mask32(s[a] + s[b] + mx)
    s[d] = rotr32(s[d] ^ s[a], 16)
    s[c] = mask32(s[c] + s[d])
    s[b] = rotr32(s[b] ^ s[c], 12)
    s[a] = mask32(s[a] + s[b] + my)
    s[d] = rotr32(s[d] ^ s[a], 8)
    s[c] = mask32(s[c] + s[d])
    s[b] = rotr32(s[b] ^ s[c], 7)


def round_fn(state: List[int], m: List[int]) -> None:
    # columns
    g(state, 0, 4, 8, 12, m[0], m[1])
    g(state, 1, 5, 9, 13, m[2], m[3])
    g(state, 2, 6, 10, 14, m[4], m[5])
    g(state, 3, 7, 11, 15, m[6], m[7])
    # diagonals
    g(state, 0, 5, 10, 15, m[8], m[9])
    g(state, 1, 6, 11, 12, m[10], m[11])
    g(state, 2, 7, 8, 13, m[12], m[13])
    g(state, 3, 4, 9, 14, m[14], m[15])


def permute_msg(m: List[int]) -> List[int]:
    return [m[BLAKE3_PERM[i]] for i in range(16)]


def blake3_compress_full(
    cv: List[int],
    block: List[int],
    counter: int,
    block_len: int,
    flags: int,
) -> List[int]:
    """Reference BLAKE3 compress -- 7 rounds, 16-word output.

    Identical to UpstreamBlake3.compress (see BLAKE3 paper Figure 1).
    """
    assert len(cv) == 8
    assert len(block) == 16
    state = list(cv) + list(BLAKE3_IV[:4]) + [
        counter & 0xFFFFFFFF,
        (counter >> 32) & 0xFFFFFFFF,
        block_len & 0xFFFFFFFF,
        flags & 0xFFFFFFFF,
    ]
    m = list(block)
    for _ in range(BLAKE3_ROUNDS):
        round_fn(state, m)
        m = permute_msg(m)
    # finalise per BLAKE3 spec: first 8 ^ last 8
    out = [mask32(state[i] ^ state[i + 8]) for i in range(8)] + \
          [mask32(state[i] ^ cv[i - 8]) for i in range(8, 16)]
    return out


def blake3_short_compress(
    cv: List[int],
    block: List[int],
    inner_rounds: int = INNER_ROUNDS,
) -> Tuple[List[int], List[int]]:
    """Reduced-round BLAKE3 compress used by mixing_core.

    Runs `inner_rounds` rounds (vs 7 for full BLAKE3) on the state.
    The first 8 output words feed the new lane state; the full 16 words
    of the message after permutation feed the scratchpad writeback.

    This is the simulation of a single hardware mixing iteration, per
    lane.  See SPEC.md §6.5.
    """
    state = list(cv) + list(BLAKE3_IV[:4]) + [0, 0, BLOCK_BYTES, 0]
    m = list(block)
    for _ in range(inner_rounds):
        round_fn(state, m)
        m = permute_msg(m)
    new_cv = [mask32(state[i] ^ state[i + 8]) for i in range(8)]
    return new_cv, m


# ----------------------------------------------------------------------------
# BLAKE3 XOF wrapper -- used by scratch_init (SPEC §6.1)
# ----------------------------------------------------------------------------
def blake3_xof(input_bytes: bytes, out_len: int) -> bytes:
    """BLAKE3 in extendable-output mode."""
    return _blake3(input_bytes).digest(length=out_len)


def blake3_hash(input_bytes: bytes) -> bytes:
    return _blake3(input_bytes).digest()


# ----------------------------------------------------------------------------
# B3PoW-Scratch -- top-level (SPEC §5)
# ----------------------------------------------------------------------------
@dataclass
class B3PowResult:
    pow_hash: bytes              # 32 bytes
    lanes_final: List[bytes]     # 8 × 32 bytes (post-loop, pre-final-hash)
    scratch_final_sample: bytes  # first 64 bytes of pad after mining (debug)
    iterations: int = ITERATIONS


def init_scratchpad(prev_block_hash: bytes) -> bytearray:
    """Fill the 1 MB scratchpad from BLAKE3-XOF(prev_hash || i) per SPEC §6.1.

    Returns a bytearray of length SCRATCH_BYTES.
    """
    assert len(prev_block_hash) == 32
    pad = bytearray(SCRATCH_BYTES)
    for i in range(SCRATCH_BLOCKS):
        chunk = blake3_xof(prev_block_hash + struct.pack("<I", i), BLOCK_BYTES)
        pad[i * BLOCK_BYTES : (i + 1) * BLOCK_BYTES] = chunk
    return pad


def init_lanes(seed: bytes) -> List[bytes]:
    """Per-lane initial state -- SPEC §6.2."""
    assert len(seed) == 32
    out = []
    for L in range(LANES):
        out.append(blake3_hash(seed + struct.pack("<I", L)))
    return out


def derive_addresses(lanes: List[bytes], iter_idx: int) -> List[int]:
    """Per-lane scratchpad block-address -- SPEC §6.3.

    Algorithm (every lane L independently):

        mul64 = ((hi XOR iter_idx) * ITER_MUL[L]) mod 2^64
        mixed = lo XOR rotr64(mul64, 23)
        addr  = mixed mod LANE_BLOCKS

    iter_idx is XOR'd into `hi` BEFORE the multiplication so that its
    bits diffuse through every output bit (multiplication mixes high
    and low halves).  Putting iter_idx post-rotate (as v0.1 of this
    file did) leaves it at bit position 41 of `mixed` after rotation by
    23, which never reaches the 11-bit address window.
    """
    addrs = []
    mask = LANE_BLOCKS - 1
    for L in range(LANES):
        lo = struct.unpack("<Q", lanes[L][0:8])[0]
        hi = struct.unpack("<Q", lanes[L][8:16])[0]
        mul = mask64(mask64(hi ^ iter_idx) * ITER_MUL[L])
        mixed = lo ^ rotr64(mul, 23)
        addrs.append(mixed & mask)
    return addrs


def read_scratchpad_blocks(pad: bytearray, addrs: List[int]) -> List[bytes]:
    """Per-lane parallel read -- SPEC §6.4."""
    out = []
    for L in range(LANES):
        base = L * LANE_BYTES + addrs[L] * BLOCK_BYTES
        out.append(bytes(pad[base : base + BLOCK_BYTES]))
    return out


def write_scratchpad_blocks(pad: bytearray, addrs: List[int], new_blocks: List[bytes]) -> None:
    """Per-lane parallel write -- SPEC §6.6."""
    for L in range(LANES):
        base = L * LANE_BYTES + addrs[L] * BLOCK_BYTES
        pad[base : base + BLOCK_BYTES] = new_blocks[L]


def mix_step(
    lanes: List[bytes],
    blocks: List[bytes],
) -> Tuple[List[bytes], List[bytes]]:
    """Per-iteration mix -- SPEC §6.5.

    Returns (new_lanes, blocks_to_write_back).
    """
    new_lanes = [b""] * LANES
    new_blocks = [b""] * LANES

    # Per-lane reduced-round BLAKE3 compress.
    for L in range(LANES):
        cv_words = le_words(lanes[L])               # 8 words
        msg_words = le_words(blocks[L])             # 16 words
        new_cv_words, permuted_msg = blake3_short_compress(cv_words, msg_words)
        new_lanes[L] = pack_le_words(new_cv_words)  # 32 bytes
        # Writeback = original block XOR permuted_msg serialised
        permuted_bytes = pack_le_words(permuted_msg)
        new_blocks[L] = bytes(a ^ b for a, b in zip(blocks[L], permuted_bytes))

    # Apply lane shuffle (cross-lane diffusion, SPEC §6.5)
    shuffled = [new_lanes[LANE_SHUFFLE[L]] for L in range(LANES)]
    return shuffled, new_blocks


def serialise_lanes(lanes: List[bytes]) -> bytes:
    """SPEC §6.7: concat(lanes[0..7]) -> 256 bytes."""
    out = b"".join(lanes)
    assert len(out) == LANES * 32
    return out


def b3pow_scratch(
    header: bytes,
    prev_block_hash: bytes,
    pad: bytearray | None = None,
) -> B3PowResult:
    """Top-level PoW function.

    Args:
        header: 80-byte block header.
        prev_block_hash: 32-byte SHA-256d hash of parent block.
        pad: optional pre-initialised scratchpad (re-use across nonces
             for the same prev_block_hash, per SPEC §5).

    Returns:
        `B3PowResult` with the 32-byte pow_hash plus debug fields.
    """
    assert len(header) == 80
    assert len(prev_block_hash) == 32

    nonce = header[76:80]
    seed = blake3_hash(header)

    if pad is None:
        pad = init_scratchpad(prev_block_hash)

    lanes = init_lanes(seed)

    for r in range(ITERATIONS):
        addrs = derive_addresses(lanes, r)
        blocks = read_scratchpad_blocks(pad, addrs)
        new_lanes, new_blocks = mix_step(lanes, blocks)
        # SPEC §5: writeback = block XOR mix_output
        # Mix already XOR'd inside mix_step (returning blocks-XOR-mix);
        # so we just write back new_blocks.
        write_scratchpad_blocks(pad, addrs, new_blocks)
        lanes = new_lanes

    pow_hash = blake3_hash(serialise_lanes(lanes) + nonce)
    return B3PowResult(
        pow_hash=pow_hash,
        lanes_final=lanes,
        scratch_final_sample=bytes(pad[:BLOCK_BYTES]),
    )


# ----------------------------------------------------------------------------
# Network target comparison (SPEC §7)
# ----------------------------------------------------------------------------
def int_le(buf: bytes) -> int:
    """Interpret a 32-byte buffer as a little-endian 256-bit integer."""
    return int.from_bytes(buf, byteorder="little")


def nbits_to_target(nbits: int) -> int:
    """Bitcoin-compact-encoded target (matches src/pow.cpp::SetCompact)."""
    size = (nbits >> 24) & 0xFF
    word = nbits & 0x007FFFFF
    if size <= 3:
        return word >> (8 * (3 - size))
    return word << (8 * (size - 3))


def check_pow(header: bytes, prev_block_hash: bytes, nbits: int) -> bool:
    """True iff this header is a valid PoW (B3PoW-Scratch v1.1)."""
    result = b3pow_scratch(header, prev_block_hash)
    return int_le(result.pow_hash) <= nbits_to_target(nbits)


# ----------------------------------------------------------------------------
# Convenience for vector generation
# ----------------------------------------------------------------------------
def header_with_nonce(template: bytes, nonce: int) -> bytes:
    assert len(template) == 80
    return template[:76] + struct.pack("<I", nonce)


__all__ = [
    "SPEC_VERSION", "REG_ID_MAGIC",
    "SCRATCH_BYTES", "LANES", "LANE_BYTES", "BLOCK_BYTES",
    "LANE_BLOCKS", "ADDR_BITS", "ITERATIONS", "INNER_ROUNDS",
    "BLAKE3_IV", "BLAKE3_PERM", "ITER_MUL", "LANE_SHUFFLE",
    "g", "round_fn", "permute_msg",
    "blake3_compress_full", "blake3_short_compress",
    "blake3_xof", "blake3_hash",
    "init_scratchpad", "init_lanes",
    "derive_addresses", "read_scratchpad_blocks", "write_scratchpad_blocks",
    "mix_step", "serialise_lanes", "b3pow_scratch",
    "B3PowResult",
    "int_le", "nbits_to_target", "check_pow",
    "header_with_nonce",
]
