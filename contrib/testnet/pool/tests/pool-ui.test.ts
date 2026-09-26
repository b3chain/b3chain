import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import ejs from "ejs";
import { shareHashrateHps } from "../src/lib/pool-stats";
import { consumeNew } from "../src/lib/event-cursor";
import { payoutReadiness } from "../src/lib/payout-readiness";
import { rejectColumn } from "../src/lib/reject-reason";
import { userCreditFromShares } from "../src/lib/pplns-math";
import { safeNext } from "../src/web/safe-next";
import { bech32m } from "@scure/base";

test("share hashrate is 0 for an empty window", () => {
    assert.equal(shareHashrateHps(0, 300), 0);
    assert.equal(shareHashrateHps(10, 0), 0);
    assert.equal(shareHashrateHps(Number.NaN, 300), 0);
});

test("share hashrate uses diff times 2^32 over the window", () => {
    assert.equal(shareHashrateHps(1, 1), 4_294_967_296);
});

test("payout readiness covers the skip cases and the eligible case", () => {
    const base = {
        emailVerified: true,
        payoutAddress: "tb1qnotvalid",
        balance: 2,
        minimum: 1,
        network: "testnet" as const,
    };
    assert.equal(payoutReadiness({ ...base, emailVerified: false }).code, "not_verified");
    assert.equal(payoutReadiness({ ...base, payoutAddress: null }).code, "no_address");
    assert.equal(payoutReadiness({ ...base, payoutAddress: "  " }).code, "no_address");
    assert.equal(payoutReadiness(base).code, "invalid_address");
    const program = new Uint8Array(32);
    program[0] = 1;
    const good = bech32m.encode("tb3", [1, ...bech32m.toWords(program)], 200);
    assert.equal(payoutReadiness({ ...base, payoutAddress: good, balance: 0.5 }).code, "below_minimum");
    assert.equal(payoutReadiness({ ...base, payoutAddress: good, balance: 2 }).code, "eligible");
});

test("event cursor ignores rows at or below the startup mark", () => {
    const first = consumeNew(5, [{ id: 5, hash: "old" }]);
    assert.deepEqual(first.fresh, []);
    assert.equal(first.cursor, 5);
    const next = consumeNew(first.cursor, [{ id: 6, hash: "new" }]);
    assert.equal(next.fresh.length, 1);
    assert.equal(next.fresh[0]!.hash, "new");
    assert.equal(next.cursor, 6);
});

test("reject reasons map onto worker counter columns", () => {
    assert.equal(rejectColumn("duplicate"), "rejected_duplicate");
    assert.equal(rejectColumn("low-diff"), "rejected_low_diff");
    assert.equal(rejectColumn("invalid"), "rejected_invalid");
    assert.equal(rejectColumn("stale"), "rejected_other");
});

test("immature preview credits only this user's share of the window", () => {
    const amount = userCreditFromShares(
        [
            { userId: 1, diff: 1 },
            { userId: 2, diff: 3 },
        ],
        1,
        100,
        1
    );
    assert.equal(amount, 24.75);
    assert.equal(userCreditFromShares([], 1, 100, 1), 0);
});

test("safeNext allows only known pool paths", () => {
    assert.equal(safeNext("/"), "/");
    assert.equal(safeNext("/dashboard"), "/dashboard");
    assert.equal(safeNext("/dashboard/workers"), "/dashboard/workers");
    assert.equal(safeNext("/dashboard/payouts?x=1"), "/dashboard/payouts?x=1");
    assert.equal(safeNext("/blocks"), "/blocks");
    assert.equal(safeNext("/blocks/abc"), "/blocks/abc");
    assert.equal(safeNext("/getting-started"), "/getting-started");
    assert.equal(safeNext("/admin"), "/admin");
    assert.equal(safeNext("/admin/ops"), "/admin/ops");
    assert.equal(safeNext("//evil.example"), "/dashboard");
    assert.equal(safeNext("/\\example"), "/dashboard");
    assert.equal(safeNext("https://evil.example"), "/dashboard");
    assert.equal(safeNext("/auth/logout"), "/dashboard");
    assert.equal(safeNext("/metrics"), "/dashboard");
    assert.equal(safeNext("/getting-started-evil"), "/dashboard");
    assert.equal(safeNext("/dashboarding"), "/dashboard");
});

test("getting started names B3PoW-Scratch and omits blake3d", async () => {
    const views = path.join(__dirname, "..", "src", "web", "views");
    const html = await ejs.renderFile(path.join(views, "getting-started.ejs"), {
        title: "Getting started",
        poolUrl: "stratum+tcp://pool.b3chain.org:3333",
        network: "testnet",
        defaultDifficulty: 1024,
        vardiffTargetSeconds: 600,
        vardiffEnabled: false,
        networkDifficultyText: "0.00224692",
        assignedDifficultyText: "0.00224692",
        user: null,
        path: "/getting-started",
        csrfToken: "t",
        feePercent: 1,
        confirmationsRequired: 100,
        pplnsNShares: 4032,
        payoutHourly: true,
        formatDifficulty: (n: number) => String(n),
    });
    assert.match(html, /B3PoW-Scratch/);
    assert.equal(html.toLowerCase().includes("blake3d"), false);
    assert.match(html, /id="network-difficulty">0\.00224692/);
    assert.match(html, /id="assigned-difficulty">0\.00224692/);
    assert.match(html, /Shares are recorded when that email matches a registered account/);
    assert.match(html, /Payouts require a verified email/);
    assert.equal(html.includes("stay at the starting difficulty"), false);
    assert.equal(html.includes("Connections stay at"), false);
});
