import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyCandidate } from "../src/stratum/share-validator";
import { targetFromShareDifficulty } from "../src/lib/difficulty-math";

test("a network-valid hash is kept when it misses a harder share target", () => {
    const shareTarget = 50n;
    const networkTarget = 200n;
    const pow = 100n;
    const out = classifyCandidate(pow, shareTarget, networkTarget);
    assert.deepEqual(out, { ok: true, isBlock: true, meetsShare: false });
});

test("a hash meeting both targets is a credited share and a block", () => {
    const out = classifyCandidate(10n, 50n, 200n);
    assert.deepEqual(out, { ok: true, isBlock: true, meetsShare: true });
});

test("a hash missing both targets is low-diff", () => {
    const out = classifyCandidate(300n, 50n, 200n);
    assert.deepEqual(out, { ok: false, reason: "low-diff" });
});

test("fractional difficulty 0.00008 converts without collapsing", () => {
    const t = targetFromShareDifficulty(0.00008);
    const one = targetFromShareDifficulty(1);
    assert.ok(t > one);
    assert.equal(t, (one * 1_000_000n) / 80n);
});
