import { test } from "node:test";
import assert from "node:assert/strict";
import {
    targetFromBits,
    targetFromShareDifficulty,
    shareDifficultyFromTarget,
    POOL_DIFF1_TARGET,
    networkDifficultyFromBits,
    bigIntFromBytesLE,
} from "../src/lib/difficulty-math";

test("diff1 round-trips", () => {
    const t = targetFromShareDifficulty(1);
    // Allow off-by-one from integer scaling.
    assert.ok(t > 0n);
    assert.ok(POOL_DIFF1_TARGET - t < 1024n);
    const d = shareDifficultyFromTarget(t);
    assert.ok(Math.abs(d - 1) < 1e-3);
});

test("higher diff -> lower target", () => {
    const t1 = targetFromShareDifficulty(1);
    const t1024 = targetFromShareDifficulty(1024);
    assert.ok(t1024 < t1);
    assert.ok(t1 / t1024 > 1000n && t1 / t1024 < 1100n);
});

test("nBits 0x1d00ffff -> Bitcoin's diff1 target (sanity)", () => {
    const t = targetFromBits(0x1d00ffff);
    assert.equal(t.toString(16), "ffff0000000000000000000000000000000000000000000000000000");
});

test("network difficulty grows as nBits target shrinks", () => {
    const easy = networkDifficultyFromBits(0x1d00ffff);
    const hard = networkDifficultyFromBits(0x1c00ffff);
    assert.ok(hard > easy);
});

test("bigIntFromBytesLE round-trips", () => {
    const buf = new Uint8Array([0x78, 0x56, 0x34, 0x12]);
    assert.equal(bigIntFromBytesLE(buf), 0x12345678n);
});
