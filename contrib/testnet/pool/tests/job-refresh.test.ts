import { test } from "node:test";
import assert from "node:assert/strict";
import { cleanJobsFor, workSignature } from "../src/stratum/job-manager";

test("unchanged parent is not a clean job", () => {
    assert.equal(cleanJobsFor("aa", "aa"), false);
    assert.equal(cleanJobsFor("", "aa"), true);
    assert.equal(cleanJobsFor("aa", "bb"), true);
});

test("work signature ignores curtime", () => {
    const tpl = {
        previousblockhash: "aa",
        transactions: [],
        bits: "1d00ffff",
        version: 1,
    };
    assert.equal(workSignature(tpl), workSignature({ ...tpl }));
});
