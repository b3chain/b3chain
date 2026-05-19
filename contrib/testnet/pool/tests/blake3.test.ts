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

// Double BLAKE3 of empty input — independently computed reference
// vector via Python's `blake3` package, kept here to detect any
// accidental BLAKE3 primitive regression in the pool shim.  Note: as
// of B3PoW-Scratch v1.1 the chain no longer uses double-BLAKE3 for PoW
// directly; BLAKE3 is now the inner primitive of the scratch PoW (see
// SECURITY-AUDIT H-1 / contrib/miner/b3miner-rtl/SPEC.md).
test("BLAKE3d of empty input is deterministic", () => {
    const h = Buffer.from(blake3d(new Uint8Array(0))).toString("hex");
    assert.equal(
        h,
        "82878ed8a480ee41775636820e05a934ca5c747223ca64306658ee5982e6c227"
    );
});

test("BLAKE3d of 80 zero bytes is deterministic", () => {
    const a = blake3d(new Uint8Array(80));
    const b = blake3d(new Uint8Array(80));
    assert.deepEqual(a, b);
    assert.equal(a.length, 32);
});
