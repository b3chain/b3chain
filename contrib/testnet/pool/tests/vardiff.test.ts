import { test } from "node:test";
import assert from "node:assert/strict";
import { Vardiff } from "../src/stratum/difficulty";

test("vardiff raises diff when shares come too fast", () => {
    let now = 1_000_000;
    const v = new Vardiff({
        targetSeconds: 10,
        retuneSeconds: 30,
        minDiff: 1,
        maxDiff: 1_000_000,
        initialDiff: 100,
        maxStep: 4,
    }, now);
    // Submit 30 shares in 30 seconds (1/sec; way too fast vs target 10s).
    for (let i = 0; i < 30; i++) {
        v.onShareAccepted();
    }
    const next = v.maybeRetune(now + 30_000);
    assert.ok(next !== null);
    assert.ok(next! > 100, `expected diff to increase, got ${next}`);
});

test("vardiff lowers diff when shares are too slow", () => {
    const v = new Vardiff({
        targetSeconds: 10,
        retuneSeconds: 30,
        minDiff: 1,
        maxDiff: 1_000_000,
        initialDiff: 1000,
        maxStep: 4,
    }, 1_000_000);
    // 1 share in 30 seconds (target 10s) -> diff should drop ~3x.
    v.onShareAccepted();
    const next = v.maybeRetune(1_000_000 + 30_000);
    assert.ok(next !== null);
    assert.ok(next! < 1000, `expected diff to decrease, got ${next}`);
});

test("vardiff respects minDiff/maxDiff", () => {
    const v = new Vardiff({
        targetSeconds: 10,
        retuneSeconds: 30,
        minDiff: 50,
        maxDiff: 200,
        initialDiff: 100,
        maxStep: 4,
    }, 1_000_000);
    // Burst — should clip at max
    for (let i = 0; i < 1000; i++) v.onShareAccepted();
    const up = v.maybeRetune(1_000_000 + 30_000);
    assert.ok(up !== null && up <= 200, `clipped to maxDiff, got ${up}`);
});

test("vardiff converges within ~10 retunes from constant input", () => {
    let t = 0;
    const v = new Vardiff({
        targetSeconds: 10,
        retuneSeconds: 30,
        minDiff: 1,
        maxDiff: 10_000_000,
        initialDiff: 1,
        maxStep: 4,
    }, t);
    let lastDiff = v.diff;
    // Simulate a miner that produces a fixed hashrate so the actual share
    // rate = diff_constant / current_diff. Pick a constant such that the
    // converged diff is ~256.
    const hashrateConstant = 256 * 0.1; // shares per second when diff = 1
    const targetPerSec = 1 / 10;        // target 1 share / 10s
    for (let step = 0; step < 30; step++) {
        const elapsed = 30;
        // approximate fractional shares
        const expected = (hashrateConstant / lastDiff) * elapsed;
        for (let i = 0; i < Math.floor(expected); i++) v.onShareAccepted();
        t += elapsed * 1000;
        const next = v.maybeRetune(t);
        if (next !== null) lastDiff = next;
    }
    // Converged diff should be ~ hashrateConstant / targetPerSec = 256
    assert.ok(lastDiff > 64 && lastDiff < 1024, `converged diff out of band: ${lastDiff}`);
});
