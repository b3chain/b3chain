import { test } from "node:test";
import assert from "node:assert/strict";

// Pure PPLNS math: replicates the math inside src/pool/pplns.ts so we
// can hand-verify the worked example from docs/PPLNS.md without touching
// the database.

interface Share { userId: number; diff: number }

function pplnsCredits(shares: Share[], reward: number, feeFraction: number): Map<number, number> {
    const distributable = reward * (1 - feeFraction);
    const totals = new Map<number, number>();
    let sum = 0;
    for (const s of shares) {
        totals.set(s.userId, (totals.get(s.userId) ?? 0) + s.diff);
        sum += s.diff;
    }
    const out = new Map<number, number>();
    for (const [uid, d] of totals) {
        out.set(uid, Number(((d / sum) * distributable).toFixed(8)));
    }
    return out;
}

test("docs/PPLNS.md worked example", () => {
    // Each user is one share at the listed diff.
    const shares: Share[] = [
        { userId: 1, diff: 800 },
        { userId: 2, diff: 200 },
        { userId: 3, diff: 1000 },
    ];
    const credits = pplnsCredits(shares, 50.0, 0.01);
    assert.equal(credits.get(1), 19.8);
    assert.equal(credits.get(2), 4.95);
    assert.equal(credits.get(3), 24.75);
    let sum = 0;
    for (const v of credits.values()) sum += v;
    // Total credited == reward * (1 - fee)
    assert.ok(Math.abs(sum - 49.5) < 1e-8, `total=${sum}`);
});

test("equal shares -> equal credits", () => {
    const shares: Share[] = Array.from({ length: 10 }, (_, i) => ({ userId: i, diff: 1 }));
    const credits = pplnsCredits(shares, 100, 0);
    for (let i = 0; i < 10; i++) assert.equal(credits.get(i), 10);
});

test("zero fee -> entire reward distributed", () => {
    const credits = pplnsCredits([{ userId: 1, diff: 1 }], 25, 0);
    assert.equal(credits.get(1), 25);
});

test("100% fee -> no credits", () => {
    const credits = pplnsCredits([{ userId: 1, diff: 1 }], 25, 1);
    assert.equal(credits.get(1), 0);
});

test("user appearing in multiple shares accumulates", () => {
    const credits = pplnsCredits(
        [
            { userId: 1, diff: 100 },
            { userId: 1, diff: 100 },
            { userId: 2, diff: 200 },
        ],
        40,
        0
    );
    assert.equal(credits.get(1), 20);
    assert.equal(credits.get(2), 20);
});
