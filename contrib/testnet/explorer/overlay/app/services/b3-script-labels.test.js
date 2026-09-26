"use strict";

const assert = require("assert");
const { coinbaseScriptSummary, witnessCommitmentHash } = require("./b3-script-labels.js");

const coinbase = "02ad0b00000001000000000e2f4233436861696e20506f6f6c2f";
const summary = coinbaseScriptSummary(coinbase, 2989);
assert.deepStrictEqual(summary, { height: 2989, tag: "/B3Chain Pool/" });
assert.strictEqual(coinbaseScriptSummary(coinbase, 2988), null);
assert.strictEqual(coinbaseScriptSummary(coinbase, -1), null);

// Genesis-style script does not start with height 0.
const genesis = "04ffff001d0104455468652054696d6573";
assert.strictEqual(coinbaseScriptSummary(genesis, 0), null);

assert.deepStrictEqual(coinbaseScriptSummary("00", 0), { height: 0, tag: "" });
assert.deepStrictEqual(coinbaseScriptSummary("51", 1), { height: 1, tag: "" });
// Positive 128 is CScriptNum 0x8000, not a one-byte negative.
assert.deepStrictEqual(coinbaseScriptSummary("028000", 128), { height: 128, tag: "" });
assert.strictEqual(coinbaseScriptSummary("0180", 128), null);

const commit = "e2f61c3f71d1defd3fa999dfa36953755c690689799962b48bebd836974e8cf9";
assert.strictEqual(witnessCommitmentHash("aa21a9ed" + commit), commit);
assert.strictEqual(witnessCommitmentHash("aa21a9ed" + commit.slice(0, 10)), null);
assert.strictEqual(witnessCommitmentHash("deadbeef"), null);

console.log("b3-script-labels: ok");
