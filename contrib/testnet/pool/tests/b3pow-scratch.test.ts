// Parity test: the TypeScript port of B3PoW-Scratch v1.1 in
// `src/lib/b3pow-scratch.ts` MUST produce byte-identical pow_hash
// values to the canonical Python reference for every entry in the
// repo's consensus vectors. If this test fails, the pool will reject
// valid shares (or accept invalid ones) and consensus is broken.
//
// Vectors path is resolved relative to the b3chain repo root; CI
// runs the pool tests from `contrib/testnet/pool/`.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import {
    b3powScratch,
    checkPow,
    initScratchpad,
    intLE,
    nbitsToTarget,
    SPEC_VERSION,
} from "../src/lib/b3pow-scratch";
import { PadCache } from "../src/lib/pad-cache";

const HERE = dirname(fileURLToPath(import.meta.url));
// pool/tests/ -> pool/ -> testnet/ -> contrib/ -> b3chain/
const REPO_ROOT = resolve(HERE, "..", "..", "..", "..");
const VECTORS_PATH = resolve(
    REPO_ROOT,
    "src",
    "test",
    "data",
    "b3pow_consensus_vectors.json",
);

interface VectorsFile {
    schema_version: number;
    spec_version: string;
    entries: Array<{
        name: string;
        header_hex: string;
        prev_block_hash_hex: string;
        expected_pow_hash_hex: string;
        nbits_hex: string;
        expected_check_pow: boolean;
    }>;
}

function loadVectors(): VectorsFile {
    const text = readFileSync(VECTORS_PATH, "utf8");
    return JSON.parse(text) as VectorsFile;
}

function hexToBytes(hex: string): Uint8Array {
    if (hex.length % 2 !== 0) throw new Error("odd-length hex");
    const out = new Uint8Array(hex.length / 2);
    for (let i = 0; i < out.length; i++) {
        out[i] = parseInt(hex.substr(i * 2, 2), 16);
    }
    return out;
}

function bytesToHex(b: Uint8Array): string {
    let s = "";
    for (let i = 0; i < b.length; i++) {
        const v = b[i];
        s += (v < 16 ? "0" : "") + v.toString(16);
    }
    return s;
}

test("SPEC_VERSION matches consensus vectors", () => {
    const v = loadVectors();
    assert.equal(`0x${SPEC_VERSION.toString(16).padStart(8, "0")}`, v.spec_version);
});

test("B3PoW-Scratch v1.1 TS port matches every consensus vector", () => {
    const v = loadVectors();
    assert.ok(v.entries.length > 0, "expected at least one consensus vector");
    for (const entry of v.entries) {
        const header = hexToBytes(entry.header_hex);
        const prev = hexToBytes(entry.prev_block_hash_hex);
        const expected = entry.expected_pow_hash_hex;

        assert.equal(header.length, 80, `${entry.name}: header must be 80 B`);
        assert.equal(prev.length, 32, `${entry.name}: prev must be 32 B`);

        const got = b3powScratch(header, prev).powHash;
        assert.equal(
            bytesToHex(got),
            expected,
            `${entry.name}: pow_hash mismatch (TS port vs JSON vector)`,
        );

        const target = nbitsToTarget(parseInt(entry.nbits_hex, 16));
        const meets = intLE(got) <= target;
        assert.equal(
            meets,
            entry.expected_check_pow,
            `${entry.name}: expected_check_pow mismatch`,
        );
    }
});

test("checkPow() wrapper agrees with manual integer compare", () => {
    const v = loadVectors();
    for (const entry of v.entries) {
        const header = hexToBytes(entry.header_hex);
        const prev = hexToBytes(entry.prev_block_hash_hex);
        const nbits = parseInt(entry.nbits_hex, 16);
        assert.equal(
            checkPow(header, prev, nbits),
            entry.expected_check_pow,
            `${entry.name}: checkPow disagrees with expected`,
        );
    }
});

test("PadCache returns fresh copies and is bit-exact across reuse", () => {
    const v = loadVectors();
    const pairs = v.entries.filter((e) => e.prev_block_hash_hex);
    if (pairs.length < 1) return; // nothing to assert
    const cache = new PadCache(2);

    for (const entry of pairs) {
        const header = hexToBytes(entry.header_hex);
        const prev = hexToBytes(entry.prev_block_hash_hex);
        const expected = entry.expected_pow_hash_hex;

        // First call: cache miss, builds pristine + returns a copy.
        const pad1 = cache.getFresh(prev);
        const h1 = b3powScratch(header, prev, pad1).powHash;
        assert.equal(bytesToHex(h1), expected, `${entry.name}: first hash`);

        // Second call: cache hit, must return ANOTHER fresh copy and
        // produce the byte-identical hash.
        const pad2 = cache.getFresh(prev);
        const h2 = b3powScratch(header, prev, pad2).powHash;
        assert.equal(bytesToHex(h2), expected, `${entry.name}: second hash (cached)`);
    }

    const stats = cache.stats();
    assert.ok(stats.hits > 0, "expected at least one cache hit");
});

test("initScratchpad is deterministic given the same parent", () => {
    const prev = new Uint8Array(32);
    for (let i = 0; i < 32; i++) prev[i] = i;
    const a = initScratchpad(prev);
    const b = initScratchpad(prev);
    assert.deepEqual(a, b);
    assert.equal(a.length, 1024 * 1024);
});
