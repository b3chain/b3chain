import { test } from "node:test";
import assert from "node:assert/strict";
import { blake3d } from "../src/lib/blake3";
import {
    serializeHeader,
    bytesToHex,
    reverseBytes,
} from "../src/lib/header";
import {
    bigIntFromBytesLE,
    targetFromShareDifficulty,
    POOL_DIFF1_TARGET,
} from "../src/lib/difficulty-math";

// Round-trip: serialize a known header, hash it, verify that the share
// target derived from the connection's diff is consistent.

test("80-byte header serialization is exactly 80 bytes", () => {
    const h = serializeHeader({
        version: 1,
        prevHashHexBE: "0".repeat(64),
        merkleRootHexBE: "0".repeat(64),
        ntime: 1700000000,
        bits: 0x1d00ffff,
        nonce: 0,
    });
    assert.equal(h.length, 80);
});

test("share at exactly diff=1 must satisfy POOL_DIFF1_TARGET", () => {
    // Brute-force for a small nonce that gives a low BLAKE3d to compare
    // against POOL_DIFF1_TARGET. We pick a header whose hash starts with
    // many zero bytes to *exceed* diff 1 easily.
    const target = targetFromShareDifficulty(1);
    let foundUnder = false;
    for (let nonce = 0; nonce < 100_000 && !foundUnder; nonce++) {
        const header = serializeHeader({
            version: 1,
            prevHashHexBE: "0".repeat(64),
            merkleRootHexBE: "0".repeat(64),
            ntime: 0,
            bits: 0x207fffff,
            nonce,
        });
        const h = blake3d(header);
        if (bigIntFromBytesLE(h) <= target) foundUnder = true;
    }
    assert.ok(foundUnder, "expected at least one header within diff-1 within 100k nonces");
});

test("share at very high diff is rare (boundary check)", () => {
    // POOL_DIFF1_TARGET / 2^32 -> on average 1 hit per 4B nonces.
    const target = targetFromShareDifficulty(1 << 24);
    let hits = 0;
    for (let nonce = 0; nonce < 10_000; nonce++) {
        const h = blake3d(
            serializeHeader({
                version: 1,
                prevHashHexBE: "0".repeat(64),
                merkleRootHexBE: "0".repeat(64),
                ntime: 0,
                bits: 0x207fffff,
                nonce,
            })
        );
        if (bigIntFromBytesLE(h) <= target) hits++;
    }
    assert.ok(hits < 5, `expected very few hits at diff=2^24 over 10k nonces, got ${hits}`);
});

test("BE/LE swap is invertible", () => {
    const x = new Uint8Array(32);
    for (let i = 0; i < 32; i++) x[i] = i;
    const y = reverseBytes(reverseBytes(x));
    assert.deepEqual(y, x);
    const hex = bytesToHex(x);
    assert.equal(hex.length, 64);
});

test("POOL_DIFF1_TARGET / shareDiff matches target inverse roughly", () => {
    const t1 = targetFromShareDifficulty(1);
    const t2 = targetFromShareDifficulty(2);
    // Allow scaling-fudge: t1 should be (almost) 2x t2.
    const ratio = Number(t1) / Number(t2);
    assert.ok(ratio > 1.99 && ratio < 2.01, `ratio ${ratio}`);
    assert.ok(POOL_DIFF1_TARGET > 0n);
});
