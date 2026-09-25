import { test } from "node:test";
import assert from "node:assert/strict";
import { splitUserName } from "../src/stratum/server";

test("email worker splits on the last dot", () => {
    assert.deepEqual(splitUserName("miner@example.com.gpu0"), ["miner@example.com", "gpu0"]);
    assert.deepEqual(splitUserName("miner@example.com.rig1"), ["miner@example.com", "rig1"]);
    assert.deepEqual(splitUserName("anonymous"), ["anonymous", "default"]);
});
