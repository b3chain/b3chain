# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Reduced-memory cost model for B3PoW-Scratch v1.1.1.

This module is not consensus and it is not a miner. The node verifier
stays in ``src/crypto/b3pow_scratch.cpp`` and always uses the full pad.

Two checks live here:

* Regenerating a block with ``BLAKE3-XOF(prev || i)`` after that block
  has been read-modify-written does not restore the honest pad.
* A checkpoint-replay evaluator whose scratchpad resident set stays
  within ``memory_bytes`` produces the same ``pow_hash`` as the honest
  loop. Each dirty miss is charged the mix steps of one replay from the
  last checkpoint that still held the block, or from iteration 0 when
  no retained checkpoint holds it.

The replay charge is a lower bound: nested misses inside a replay are
not added again. A ratio under a SPEC floor is therefore real (the
honest cost was not reached). A ratio above a floor does not prove a
tighter bound.
"""
from __future__ import annotations

import struct
from collections import OrderedDict
from dataclasses import dataclass

import b3pow_ref as ref


# SPEC §8.C claimed minimum mix-step ratio versus the honest path.
# Keys are resident-set caps in bytes. Updated if a hash-equivalent
# run lands below a floor (see tests/test_reduced_memory.py).
SPEC_FLOORS_MIB = {
    512 * 1024: 2.0,
    256 * 1024: 4.0,
    128 * 1024: 8.0,
}


@dataclass
class ReducedMemoryResult:
    pow_hash: bytes
    mix_steps: int
    stored_bytes: int
    peak_resident_bytes: int
    dirty_misses: int
    xof_fills: int
    iterations: int

    @property
    def ratio(self) -> float:
        if self.iterations <= 0:
            return 0.0
        return self.mix_steps / self.iterations


def xof_block(prev_block_hash: bytes, index: int) -> bytes:
    """Initial scratchpad block ``i``. SPEC §6.1."""
    return ref.blake3_xof(prev_block_hash + struct.pack("<I", index), ref.BLOCK_BYTES)


def block_index(lane: int, addr: int) -> int:
    return lane * ref.LANE_BLOCKS + addr


def honest_pow_hash(
    header: bytes,
    prev_block_hash: bytes,
    iterations: int | None = None,
) -> bytes:
    """Honest pad loop. ``iterations=None`` matches ``b3pow_scratch``."""
    n = ref.ITERATIONS if iterations is None else iterations
    assert len(header) == 80 and len(prev_block_hash) == 32
    assert 1 <= n <= ref.ITERATIONS
    nonce = header[76:80]
    lanes = ref.init_lanes(ref.blake3_hash(header))
    pad = ref.init_scratchpad(prev_block_hash)
    for r in range(n):
        addrs = ref.derive_addresses(lanes, r)
        blocks = ref.read_scratchpad_blocks(pad, addrs)
        lanes, new_blocks = ref.mix_step(lanes, blocks)
        ref.write_scratchpad_blocks(pad, addrs, new_blocks)
    return ref.blake3_hash(ref.serialise_lanes(lanes) + nonce)


def first_mutated_block(
    header: bytes,
    prev_block_hash: bytes,
    iterations: int = 4,
) -> tuple[int, bytes, bytes]:
    """Return ``(index, pad_bytes, xof_bytes)`` for the first written block.

    ``pad_bytes`` is the block after the write. ``xof_bytes`` is the
    SPEC §6.1 initial value. They differ once a read-modify-write has
    landed, which is why XOF rebuild is not a reduced-memory evaluator.
    """
    assert 1 <= iterations <= ref.ITERATIONS
    lanes = ref.init_lanes(ref.blake3_hash(header))
    pad = ref.init_scratchpad(prev_block_hash)
    for r in range(iterations):
        addrs = ref.derive_addresses(lanes, r)
        blocks = ref.read_scratchpad_blocks(pad, addrs)
        lanes, new_blocks = ref.mix_step(lanes, blocks)
        ref.write_scratchpad_blocks(pad, addrs, new_blocks)
        for lane, addr in enumerate(addrs):
            idx = block_index(lane, addr)
            base = idx * ref.BLOCK_BYTES
            pad_bytes = bytes(pad[base : base + ref.BLOCK_BYTES])
            xof_bytes = xof_block(prev_block_hash, idx)
            if pad_bytes != xof_bytes:
                return idx, pad_bytes, xof_bytes
    raise AssertionError("no written block diverged from its XOF image")


class _Lru:
    """Block store capped at ``capacity`` entries of ``BLOCK_BYTES``."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._data: OrderedDict[int, bytes] = OrderedDict()

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, index: int) -> bool:
        return index in self._data

    def get(self, index: int) -> bytes | None:
        value = self._data.get(index)
        if value is None:
            return None
        self._data.move_to_end(index)
        return value

    def insert(self, index: int, value: bytes) -> None:
        if index in self._data:
            self._data.move_to_end(index)
            self._data[index] = value
            return
        self._data[index] = value
        self._data.move_to_end(index)
        while len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def snapshot(self) -> _Lru:
        other = _Lru(self.capacity)
        other._data = OrderedDict(self._data)
        return other


def b3pow_scratch_reduced(
    header: bytes,
    prev_block_hash: bytes,
    memory_bytes: int,
    iterations: int | None = None,
) -> ReducedMemoryResult:
    """Hash-equivalent evaluator with a scratchpad resident cap.

    Live store and one checkpoint share ``memory_bytes``. Lane state is
    not counted: it is 256 bytes and is required even for the honest
    loop. A read of a block that was never written is the XOF image and
    costs no mix step. A read of a mutated block that is absent from
    both stores is a dirty miss: charge one replay from the checkpoint
    when that checkpoint still holds the block or the block was written
    after the checkpoint, otherwise charge a replay from iteration 0.
    """
    n = ref.ITERATIONS if iterations is None else iterations
    assert len(header) == 80 and len(prev_block_hash) == 32
    assert memory_bytes >= ref.BLOCK_BYTES * 2
    assert 1 <= n <= ref.ITERATIONS

    capacity = memory_bytes // ref.BLOCK_BYTES
    cp_cap = max(1, capacity // 2)
    live_cap = capacity - cp_cap
    if live_cap < 1:
        live_cap = 1
        cp_cap = capacity - 1

    nonce = header[76:80]
    lanes = ref.init_lanes(ref.blake3_hash(header))
    pad = ref.init_scratchpad(prev_block_hash)

    live = _Lru(live_cap)
    checkpoint = _Lru(cp_cap)
    cp_r = 0
    last_write: dict[int, int] = {}
    dirty_misses = 0
    xof_fills = 0
    replay_steps = 0
    peak_blocks = 0

    # Snapshot often enough that a window of 8-wide touches can land
    # in the live store before the next checkpoint.
    k = max(1, live_cap // ref.LANES)

    def note_peak() -> None:
        nonlocal peak_blocks
        peak_blocks = max(peak_blocks, len(live) + len(checkpoint))

    for r in range(n):
        if r != 0 and r % k == 0:
            # Retain the hottest live blocks. Dropped dirty blocks are
            # recoverable only by replaying from iteration 0.
            checkpoint = _Lru(cp_cap)
            for idx, value in list(live._data.items())[-cp_cap:]:
                checkpoint.insert(idx, value)
            cp_r = r
            note_peak()

        addrs = ref.derive_addresses(lanes, r)
        blocks: list[bytes] = []
        for lane, addr in enumerate(addrs):
            idx = block_index(lane, addr)
            base = idx * ref.BLOCK_BYTES
            honest = bytes(pad[base : base + ref.BLOCK_BYTES])
            hit = live.get(idx)
            if hit is None:
                hit = checkpoint.get(idx)
            if hit is not None:
                if hit != honest:
                    raise RuntimeError(
                        f"resident block {idx} diverged from the honest pad"
                    )
                blocks.append(honest)
                continue
            if idx not in last_write:
                xof = xof_block(prev_block_hash, idx)
                if xof != honest:
                    raise RuntimeError(
                        f"unwritten block {idx} does not match XOF"
                    )
                xof_fills += 1
                live.insert(idx, honest)
                note_peak()
                blocks.append(honest)
                continue

            dirty_misses += 1
            written_at = last_write[idx]
            if written_at >= cp_r:
                replay_steps += r - cp_r
            else:
                replay_steps += r
            live.insert(idx, honest)
            note_peak()
            blocks.append(honest)

        lanes, new_blocks = ref.mix_step(lanes, blocks)
        ref.write_scratchpad_blocks(pad, addrs, new_blocks)
        for lane, addr in enumerate(addrs):
            idx = block_index(lane, addr)
            base = idx * ref.BLOCK_BYTES
            updated = bytes(pad[base : base + ref.BLOCK_BYTES])
            last_write[idx] = r
            live.insert(idx, updated)
        note_peak()

    peak_resident = peak_blocks * ref.BLOCK_BYTES
    if peak_resident > memory_bytes:
        raise RuntimeError(
            f"resident set {peak_resident} exceeded cap {memory_bytes}"
        )

    pow_hash = ref.blake3_hash(ref.serialise_lanes(lanes) + nonce)
    return ReducedMemoryResult(
        pow_hash=pow_hash,
        mix_steps=n + replay_steps,
        stored_bytes=peak_resident,
        peak_resident_bytes=peak_resident,
        dirty_misses=dirty_misses,
        xof_fills=xof_fills,
        iterations=n,
    )
