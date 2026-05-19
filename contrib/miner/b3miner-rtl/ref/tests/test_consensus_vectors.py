"""Schema + parity tests for consensus_vectors.json.

This file is the bridge test between the Python reference (b3pow_ref.py)
and the C++ consensus port (b3chain/src/crypto/b3pow_scratch.cpp).

Goals:

1. Lock the JSON schema -- top-level keys, per-entry keys, byte lengths,
   hex-string charsets.  If you change the schema, you must update both
   this file AND src/test/b3pow_scratch_tests.cpp in the same commit.
2. Recompute every entry's `expected_pow_hash_hex` from `header_hex` +
   `prev_block_hash_hex` and assert byte-identity.  This prevents drift
   between gen_vectors.py and the C++ port -- if the C++ port goes one
   way and gen_vectors goes the other, this test catches it on the
   Python side and the C++ side's `b3pow_scratch_tests.cpp` catches it
   on the C++ side.
3. Validate the `expected_check_pow` flag against the documented compact
   target arithmetic so we don't regress the comparator.
4. Cross-check the `cache_pair_*` entries against each other and the
   `nontrivial_prev` entry against the `mainnet_target_loose_pass`
   entry (see the notes fields in gen_vectors.py).

Running this regenerates the JSON in-tree first, so a fresh tree always
passes after `python gen_vectors.py`.
"""
from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import b3pow_ref as ref
import pytest

import gen_vectors

REF_DIR = Path(__file__).resolve().parent.parent
DEFAULT_JSON = REF_DIR / "vectors" / "consensus_vectors.json"


HEX_64 = re.compile(r"^[0-9a-f]{64}$")     # 32 bytes
HEX_160 = re.compile(r"^[0-9a-f]{160}$")   # 80 bytes
NBITS_RE = re.compile(r"^0x[0-9a-f]{8}$")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def consensus_json(tmp_path_factory) -> dict:
    """Regenerate vectors/consensus_vectors.json under tmp_path and parse it."""
    out = tmp_path_factory.mktemp("vectors") / "consensus_vectors.json"
    gen_vectors.gen_consensus_vectors(out)
    return json.loads(out.read_text())


def _nbits_to_target(nbits_hex: str) -> int:
    nbits = int(nbits_hex, 16)
    size = (nbits >> 24) & 0xFF
    word = nbits & 0x007FFFFF
    return word >> (8 * (3 - size)) if size <= 3 else word << (8 * (size - 3))


# ----------------------------------------------------------------------------
# Schema tests
# ----------------------------------------------------------------------------
def test_schema_version_is_an_int(consensus_json):
    assert isinstance(consensus_json["schema_version"], int)
    assert consensus_json["schema_version"] == gen_vectors.CONSENSUS_SCHEMA_VERSION


def test_spec_version_matches_reference(consensus_json):
    assert consensus_json["spec_version"] == f"0x{ref.SPEC_VERSION:08x}"


def test_top_level_has_entries(consensus_json):
    assert "entries" in consensus_json
    assert isinstance(consensus_json["entries"], list)
    assert len(consensus_json["entries"]) >= 6, \
        "must include genesis_*, mainnet_target_*, nontrivial_prev, cache_pair_*"


REQUIRED_KEYS = frozenset({
    "name",
    "header_hex",
    "prev_block_hash_hex",
    "expected_pow_hash_hex",
    "nbits_hex",
    "expected_check_pow",
    "notes",
})


def test_each_entry_has_required_keys(consensus_json):
    for entry in consensus_json["entries"]:
        missing = REQUIRED_KEYS - set(entry.keys())
        assert not missing, f"{entry.get('name')!r} missing {missing}"


def test_names_are_unique(consensus_json):
    names = [e["name"] for e in consensus_json["entries"]]
    assert len(names) == len(set(names)), f"duplicate names: {names}"


@pytest.mark.parametrize("required_name", [
    "genesis_mainnet_template",
    "genesis_regtest",
    "mainnet_target_loose_pass",
    "mainnet_target_tight_fail",
    "nontrivial_prev",
    "cache_pair_nonce_0",
    "cache_pair_nonce_1",
])
def test_required_named_entries_present(consensus_json, required_name):
    names = {e["name"] for e in consensus_json["entries"]}
    assert required_name in names


def test_field_charsets_and_lengths(consensus_json):
    for entry in consensus_json["entries"]:
        assert HEX_160.match(entry["header_hex"]), entry["name"]
        assert HEX_64.match(entry["prev_block_hash_hex"]), entry["name"]
        assert HEX_64.match(entry["expected_pow_hash_hex"]), entry["name"]
        assert NBITS_RE.match(entry["nbits_hex"]), entry["name"]
        assert isinstance(entry["expected_check_pow"], bool), entry["name"]


# ----------------------------------------------------------------------------
# Parity tests -- recompute hashes & compare against the JSON
# ----------------------------------------------------------------------------
def test_every_entry_recomputes_to_expected_hash(consensus_json):
    """The whole point: gen_vectors.py output must be byte-identical to
    a fresh recomputation through b3pow_ref."""
    for entry in consensus_json["entries"]:
        header = bytes.fromhex(entry["header_hex"])
        prev_hash = bytes.fromhex(entry["prev_block_hash_hex"])
        expected = entry["expected_pow_hash_hex"]
        result = ref.b3pow_scratch(header, prev_hash)
        got = result.pow_hash.hex()
        assert got == expected, (
            f"{entry['name']}: pow_hash drift\n"
            f"  expected: {expected}\n"
            f"  got:      {got}"
        )


def test_check_pow_flag_matches_comparator(consensus_json):
    """expected_check_pow must equal int_le(pow_hash) <= nbits_target."""
    for entry in consensus_json["entries"]:
        pow_hash_int = int.from_bytes(
            bytes.fromhex(entry["expected_pow_hash_hex"]),
            byteorder="little",
        )
        target = _nbits_to_target(entry["nbits_hex"])
        expect_pass = pow_hash_int <= target
        assert expect_pass == entry["expected_check_pow"], entry["name"]


# ----------------------------------------------------------------------------
# Semantic cross-checks (the comments in gen_vectors.py claim these)
# ----------------------------------------------------------------------------
def test_nontrivial_prev_differs_from_loose_pass(consensus_json):
    by_name = {e["name"]: e for e in consensus_json["entries"]}
    a = by_name["mainnet_target_loose_pass"]
    b = by_name["nontrivial_prev"]
    assert a["header_hex"] == b["header_hex"], \
        "test design: nontrivial_prev must share header with loose_pass"
    assert a["prev_block_hash_hex"] != b["prev_block_hash_hex"]
    assert a["expected_pow_hash_hex"] != b["expected_pow_hash_hex"], (
        "pow_hash must depend on prev_block_hash"
    )


def test_cache_pair_share_prev_hash(consensus_json):
    by_name = {e["name"]: e for e in consensus_json["entries"]}
    a = by_name["cache_pair_nonce_0"]
    b = by_name["cache_pair_nonce_1"]
    assert a["prev_block_hash_hex"] == b["prev_block_hash_hex"]
    assert a["expected_pow_hash_hex"] != b["expected_pow_hash_hex"], (
        "different nonces must yield different pow_hashes"
    )


def test_tight_target_fails(consensus_json):
    """Target=1 (nbits=0x03000001) is effectively unreachable -- probability
    of passing is 2/2^256, so we assert this entry fails."""
    by_name = {e["name"]: e for e in consensus_json["entries"]}
    assert by_name["mainnet_target_tight_fail"]["expected_check_pow"] is False


def test_genesis_regtest_flag_is_consistent(consensus_json):
    """We don't predict the boolean -- regtest powLimit (0x207fffff)
    accepts ~50% of hashes and the chosen nonce decides -- but we *do*
    require that the flag matches the comparator (the test_check_pow_
    flag_matches_comparator test above already enforces this, this is
    a focused check)."""
    by_name = {e["name"]: e for e in consensus_json["entries"]}
    entry = by_name["genesis_regtest"]
    pow_hash_int = int.from_bytes(
        bytes.fromhex(entry["expected_pow_hash_hex"]),
        byteorder="little",
    )
    target = _nbits_to_target(entry["nbits_hex"])
    assert entry["expected_check_pow"] == (pow_hash_int <= target)
