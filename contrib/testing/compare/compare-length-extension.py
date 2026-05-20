#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Length-extension demonstration: SHA-256 vulnerable, BLAKE3 immune.

A naive MAC built as `tag = H(secret || message)` is forgeable for
Merkle-Damgard hashes (MD5, SHA-1, SHA-256, SHA-512) using the classic
length-extension trick: given `tag` and `len(secret)`, an attacker can
compute `H(secret || message || padding || extra)` without knowing
`secret`.

This script:
  1. Builds the vulnerable SHA-256 MAC, runs the LE attack, demonstrates
     a forged tag that the verifier accepts.
  2. Repeats with BLAKE3, demonstrates the same trick fails (BLAKE3 is a
     tree hash with built-in domain separation).

Notes:
  - Bitcoin's use of SHA-256d (`H(H(x))` rather than `H(secret || x)`)
    sidesteps this attack entirely. The point of this comparison is the
    *construction* — a naive user of SHA-256 can fall into the LE trap;
    a naive user of BLAKE3 cannot.
  - The attack itself is decades old; we re-implement it here for
    education, not to claim a novel result.

Outputs:
  - markdown table on stdout
  - results/length-extension-<host>-<ts>.json
  - exit 0 always (pure demo)
"""

from __future__ import annotations

import hashlib
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from compare_common import CompareResult, write_result, md_table, have_blake3  # noqa: E402


# ---------------------------------------------------------------------------
# A reference SHA-256 with state injection.
# Pure-Python (slow) so we can resume from an arbitrary internal state.
# Adapted from FIPS 180-4 pseudocode. ~150 lines, no external dependency.
# ---------------------------------------------------------------------------

_K = (
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
)
_H0 = (0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
       0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19)
_MASK = 0xFFFFFFFF


def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & _MASK


def _compress(state: tuple[int, ...], block: bytes) -> tuple[int, ...]:
    w = list(struct.unpack(">16I", block))
    for i in range(16, 64):
        s0 = _rotr(w[i-15], 7) ^ _rotr(w[i-15], 18) ^ (w[i-15] >> 3)
        s1 = _rotr(w[i-2], 17) ^ _rotr(w[i-2], 19) ^ (w[i-2] >> 10)
        w.append((w[i-16] + s0 + w[i-7] + s1) & _MASK)
    a, b, c, d, e, f, g, h = state
    for i in range(64):
        S1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
        ch = (e & f) ^ ((~e) & g) & _MASK
        t1 = (h + S1 + ch + _K[i] + w[i]) & _MASK
        S0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
        mj = (a & b) ^ (a & c) ^ (b & c)
        t2 = (S0 + mj) & _MASK
        h = g
        g = f
        f = e
        e = (d + t1) & _MASK
        d = c
        c = b
        b = a
        a = (t1 + t2) & _MASK
    return tuple((s + v) & _MASK for s, v in zip(state, (a, b, c, d, e, f, g, h)))


def _md_padding(message_length: int) -> bytes:
    """Standard SHA-256 / MD-style padding for a message of given length (bytes)."""
    bits = message_length * 8
    pad = b"\x80"
    pad += b"\x00" * ((56 - (message_length + 1) % 64) % 64)
    pad += struct.pack(">Q", bits)
    return pad


def sha256_from_state(initial_state: tuple[int, ...], absorbed_length: int,
                      data: bytes) -> bytes:
    """
    Compute SHA-256(continuation) starting from `initial_state` as if the hash
    had already absorbed `absorbed_length` bytes. Then absorb `data` and
    finalise with proper MD padding accounting for the *full* length.
    """
    state = initial_state
    full_length = absorbed_length + len(data)
    buf = data + _md_padding(full_length)
    for i in range(0, len(buf), 64):
        state = _compress(state, buf[i:i+64])
    return b"".join(struct.pack(">I", s) for s in state)


def attack_sha256(secret_len: int, message: bytes, append: bytes
                  ) -> tuple[bytes, bytes, float]:
    """
    Given the original tag (which we compute below) for some unknown secret of
    known length, forge a new tag for `message || padding || append`.

    Returns (forged_tag, forged_message_suffix, elapsed_seconds).
    """
    # 1. Compute the genuine tag (using the unknown secret).
    secret = b"\xab" * secret_len  # the verifier knows this; the attacker doesn't
    genuine_tag = hashlib.sha256(secret + message).digest()

    # 2. Attacker re-creates the internal state from the public tag.
    state = struct.unpack(">8I", genuine_tag)
    absorbed = secret_len + len(message)
    # Round absorbed up to the next 64-byte boundary because the verifier's
    # H(secret||message) ended after MD padding was applied.
    pad_for_original = _md_padding(absorbed)
    absorbed_after_pad = absorbed + len(pad_for_original)

    t0 = time.perf_counter()
    forged_tag = sha256_from_state(state, absorbed_after_pad, append)
    elapsed = time.perf_counter() - t0

    # 3. The forged message that the verifier will independently hash and
    # accept is: original_message || pad_for_original || append.
    forged_message = message + pad_for_original + append

    return forged_tag, forged_message, elapsed


def verify_sha256(secret: bytes, message: bytes, claimed_tag: bytes) -> bool:
    return hashlib.sha256(secret + message).digest() == claimed_tag


# ---------------------------------------------------------------------------
# BLAKE3 attempt (must fail).
# ---------------------------------------------------------------------------

def attack_blake3(secret_len: int, message: bytes, append: bytes
                  ) -> tuple[bool, float]:
    """Try the same trick on BLAKE3. Returns (succeeded, elapsed_seconds).

    Real-world note: there is no known length-extension attack on BLAKE3.
    The "attempt" here is to apply the SHA-256-style state recovery, observe
    that the resulting tag does NOT match a fresh BLAKE3 of the forged
    message, and report failure. This is empirical evidence, not a proof.
    """
    import blake3
    secret = b"\xab" * secret_len
    genuine_tag = blake3.blake3(secret + message).digest()

    t0 = time.perf_counter()
    # Pretend the BLAKE3 internal state can be derived from the tag (it
    # cannot — BLAKE3 outputs only XOF blocks of an internal CV chain).
    pretend_state = genuine_tag  # this is wrong by construction
    # Try to "extend" by hashing pretend_state || message || append.
    forged_tag = blake3.blake3(pretend_state + append).digest()
    elapsed = time.perf_counter() - t0

    # Verifier independently hashes secret || message || padding(?) || append.
    # We try both the SHA-256-style suffix and a plain-append suffix.
    for forged_message in (message + b"\x00" * 9 + append, message + append):
        if blake3.blake3(secret + forged_message).digest() == forged_tag:
            return True, elapsed
    return False, elapsed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("Length-extension demo: SHA-256 (vulnerable) vs BLAKE3 (immune)\n")

    secret_len = 16
    message    = b"amount=100&to=alice"
    append     = b"&to=mallory&override=true"

    result = CompareResult(comparison="length-extension")
    result.notes.append(
        "Demonstrates the classic LE attack on a naive H(secret||msg) MAC. "
        "Bitcoin's H(H(x)) construction is not vulnerable; this is a "
        "construction-level comparison, not a Bitcoin attack."
    )

    # ---- SHA-256 ----
    forged_tag, forged_msg, sha_elapsed = attack_sha256(secret_len, message, append)
    secret = b"\xab" * secret_len
    accepted = verify_sha256(secret, forged_msg, forged_tag)

    print("[1] SHA-256  H(secret || msg) MAC")
    print(f"    secret length:  {secret_len} bytes (known to attacker, value secret)")
    print(f"    message:        {message!r}")
    print(f"    appended:       {append!r}")
    print(f"    attack time:    {sha_elapsed*1e6:.1f} us")
    print(f"    forged tag:     {forged_tag.hex()}")
    print(f"    verifier says:  {'ACCEPTED (forgery succeeded)' if accepted else 'rejected'}")
    print()

    result.add_row(
        algo="sha256",
        attack_succeeded=accepted,
        attack_microseconds=sha_elapsed * 1e6,
        forged_tag_hex=forged_tag.hex(),
    )

    # ---- BLAKE3 ----
    blake3_ok = False
    blake3_elapsed = 0.0
    if have_blake3():
        blake3_ok, blake3_elapsed = attack_blake3(secret_len, message, append)
        print("[2] BLAKE3  H(secret || msg) MAC")
        print(f"    attack time:    {blake3_elapsed*1e6:.1f} us")
        print(f"    verifier says:  {'ACCEPTED (would be a real result)' if blake3_ok else 'rejected (expected)'}")
        result.add_row(
            algo="blake3",
            attack_succeeded=blake3_ok,
            attack_microseconds=blake3_elapsed * 1e6,
        )
    else:
        print("[2] BLAKE3 demo skipped (pip3 install blake3)")
        result.notes.append("BLAKE3 portion skipped — module not available")

    result.summary["sha256_le_attack_succeeded"] = accepted
    if have_blake3():
        result.summary["blake3_le_attack_succeeded"] = blake3_ok

    path = write_result(result)
    print(f"\n  wrote {path}")
    print()
    print(md_table(
        ["algorithm", "attack succeeded?", "time"],
        [
            ["sha256", "YES (forgery)" if accepted else "no", f"{sha_elapsed*1e6:.1f} us"],
            ["blake3", "YES (real result)" if (have_blake3() and blake3_ok) else "no",
             f"{blake3_elapsed*1e6:.1f} us" if have_blake3() else "-"],
        ],
    ))

    print(
        "\nTakeaway: a naive `tag = H(secret || message)` MAC is forgeable for "
        "any Merkle-Damgard hash including SHA-256. BLAKE3's tree construction "
        "(plus its dedicated keyed_hash mode) makes the same attack fail by "
        "construction. Bitcoin's use of H(H(x)) for block / tx ids does not "
        "rely on the secret-prefix MAC pattern, so this demo is about general "
        "construction safety, not a Bitcoin vulnerability."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
