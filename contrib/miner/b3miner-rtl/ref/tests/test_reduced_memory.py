# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Reduced-memory recompute tests for B3PoW-Scratch.

Short cases are the CI gate. The full 2048-iteration floor check is
marked ``slow`` and is part of the same suite; CI runs it because
``pytest -q tests/`` does not exclude marks. Skip it only if a full
hash exceeds about a minute (see MEASUREMENT.md).
"""
from __future__ import annotations

import pytest

import b3pow_reduced as rm
import b3pow_ref as ref


def _header(nonce: int = 1) -> bytes:
    hdr = bytearray(80)
    hdr[0:4] = (1).to_bytes(4, "little")
    hdr[76:80] = nonce.to_bytes(4, "little")
    return bytes(hdr)


def _prev() -> bytes:
    return bytes(range(32))


def test_xof_rebuild_diverges_after_write():
    idx, pad_bytes, xof_bytes = rm.first_mutated_block(_header(), _prev(), iterations=4)
    assert pad_bytes != xof_bytes
    assert idx >= 0


def test_xof_image_matches_unwritten_init():
    prev = _prev()
    assert rm.xof_block(prev, 0) == ref.blake3_xof(
        prev + (0).to_bytes(4, "little"), ref.BLOCK_BYTES
    )


def test_short_replay_matches_honest_hash():
    header, prev = _header(), _prev()
    iterations = 64
    honest = rm.honest_pow_hash(header, prev, iterations)
    for memory in (512 * 1024, 256 * 1024, 128 * 1024):
        result = rm.b3pow_scratch_reduced(
            header, prev, memory_bytes=memory, iterations=iterations
        )
        assert result.pow_hash == honest
        assert result.peak_resident_bytes <= memory
        assert result.mix_steps >= iterations


def test_honest_full_loop_matches_reference():
    header, prev = _header(2), _prev()
    assert rm.honest_pow_hash(header, prev) == ref.b3pow_scratch(header, prev).pow_hash


def test_tiny_cap_still_matches_and_misses():
    """A cap below the touch set must dirty-miss and still hash-match."""
    header, prev = _header(3), _prev()
    # 32 iterations touch each block once, so a small cap never misses.
    # 256 iterations re-read lanes and must pay for evicted blocks.
    iterations = 256
    honest = rm.honest_pow_hash(header, prev, iterations)
    result = rm.b3pow_scratch_reduced(
        header, prev, memory_bytes=4 * 1024, iterations=iterations
    )
    assert result.pow_hash == honest
    assert result.dirty_misses > 0
    assert result.ratio > 1.0
    assert result.peak_resident_bytes <= 4 * 1024


@pytest.mark.slow
def test_full_iteration_floors():
    """SPEC §8.C floors on a full 2048-iteration hash.

    A ratio under the published floor means the table is wrong. This
    test fails closed so the SPEC is lowered in the same change; do not
    relax the floor to keep a failing measurement.
    """
    header, prev = _header(4), _prev()
    honest = ref.b3pow_scratch(header, prev).pow_hash
    shortfalls = []
    for memory, floor in rm.SPEC_FLOORS_MIB.items():
        result = rm.b3pow_scratch_reduced(header, prev, memory_bytes=memory)
        assert result.pow_hash == honest
        assert result.iterations == ref.ITERATIONS
        assert result.peak_resident_bytes <= memory
        if result.ratio + 1e-9 < floor:
            shortfalls.append(
                f"{memory // 1024} KiB measured {result.ratio:.3f} "
                f"< floor {floor:.3f} "
                f"(dirty_misses={result.dirty_misses}, "
                f"mix_steps={result.mix_steps})"
            )
    assert not shortfalls, (
        "SPEC §8.C floor is above the hash-equivalent measurement; "
        "lower the table to the measured ratio:\n" + "\n".join(shortfalls)
    )
