import { test } from "node:test";
import assert from "node:assert/strict";
import { blake3d, blake3once } from "../src/lib/blake3";

// Single BLAKE3 of empty input — published constant.
test("BLAKE3 of empty input", () => {
    const h = Buffer.from(blake3once(new Uint8Array(0))).toString("hex");
    assert.equal(
        h,
        "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
    );
});

// Double BLAKE3 of empty input — see b3chain/doc/mining.md.
test("BLAKE3d of empty input matches doc/mining.md vector", () => {
    const h = Buffer.from(blake3d(new Uint8Array(0))).toString("hex");
    assert.equal(
        h,
        "fb6d63b21d8c9f215de0e4fd9f4d0e7ed53ff023c7243e76f5a7367b2a4507b6"
    );
});

test("BLAKE3d of 80 zero bytes is deterministic", () => {
    const a = blake3d(new Uint8Array(80));
    const b = blake3d(new Uint8Array(80));
    assert.deepEqual(a, b);
    assert.equal(a.length, 32);
});
