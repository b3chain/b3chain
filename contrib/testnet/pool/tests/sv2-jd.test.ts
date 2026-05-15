// Unit tests for the in-memory JD token store. DB persistence is exercised
// in the e2e suite; here we just verify in-memory issuance + single-use
// semantics. The store wraps DB calls in try/catch and continues even
// when the DB is unreachable (which is exactly the case in this test).

import test from "node:test";
import * as assert from "node:assert/strict";

// Required env vars are loaded from .env.test by `npm test`.
import { JdTokenStore } from "../src/sv2/jd/tokens";
import { makeLogger } from "../src/lib/logger";

const log = makeLogger("test");

test("JdTokenStore issues 32-byte single-use tokens", async () => {
    const s = new JdTokenStore(log);
    const tok = await s.issue({ userIdentifier: "alice", sessionId: null, coinbaseOutputMaxAdditionalSize: 64 });
    assert.equal(tok.bytes.length, 32);
    assert.equal(tok.consumed, false);
    assert.ok(tok.expiresAt > tok.issuedAt);
});

test("JdTokenStore consume() flips state and rejects re-use", async () => {
    const s = new JdTokenStore(log);
    const tok = await s.issue({ userIdentifier: "alice", sessionId: null, coinbaseOutputMaxAdditionalSize: 64 });
    const c1 = await s.consume(tok.bytes, {
        version: 0x20000000,
        coinbasePrefix: new Uint8Array([0x01]),
        coinbaseSuffix: new Uint8Array([0x02, 0x03]),
        txCount: 5,
    });
    assert.ok(c1, "first consume should succeed");
    const c2 = await s.consume(tok.bytes, {
        version: 0x20000000,
        coinbasePrefix: new Uint8Array([0x01]),
        coinbaseSuffix: new Uint8Array([0x02, 0x03]),
        txCount: 5,
    });
    assert.equal(c2, null, "second consume must return null");
});

test("JdTokenStore rejects unknown tokens", async () => {
    const s = new JdTokenStore(log);
    const fake = new Uint8Array(32).fill(0xab);
    const r = await s.consume(fake, {
        version: 0, coinbasePrefix: new Uint8Array(0), coinbaseSuffix: new Uint8Array(0), txCount: 0,
    });
    assert.equal(r, null);
});

test("JdTokenStore expires tokens past TTL", async () => {
    const s = new JdTokenStore(log);
    const tok = await s.issue({ userIdentifier: "bob", sessionId: null, coinbaseOutputMaxAdditionalSize: 64 });
    // TTL set to 1000ms via env at top of file
    await new Promise((res) => setTimeout(res, 1100));
    const r = await s.consume(tok.bytes, {
        version: 0, coinbasePrefix: new Uint8Array(0), coinbaseSuffix: new Uint8Array(0), txCount: 0,
    });
    assert.equal(r, null, "expired tokens must reject");
});
