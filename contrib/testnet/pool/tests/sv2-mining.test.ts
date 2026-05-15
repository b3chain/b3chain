// Unit tests for the SV2 mining channel layer + JD coinbase validation.
// We deliberately avoid network/DB so these can run in any environment.

import test from "node:test";
import * as assert from "node:assert/strict";

// Required env vars are loaded from .env.test by `npm test`.
import {
    ChannelTable, fullExtranonce, SV2_EXTRANONCE_TOTAL,
    targetU256BE, maxTargetU256BE,
} from "../src/sv2/mining/channel";
import { POOL_DIFF1_TARGET, bigIntFromBytesBE } from "../src/lib/difficulty-math";
import { validateDeclaredCoinbase } from "../src/sv2/jd/custom_job";
import { addressToScriptPubKey } from "../src/lib/address";
import { concatBytes, varInt } from "../src/lib/header";

test("ChannelTable: standard channel pins full 8-byte extranonce", () => {
    const t = new ChannelTable();
    const ch = t.open({
        kind: "standard", requestId: 1, userIdentity: "alice",
        nominalHashRate: 1e6, defaultDifficulty: 1024,
    });
    assert.equal(ch.extranoncePrefix.length, SV2_EXTRANONCE_TOTAL);
    assert.equal(ch.extranonceSize, 0);
    // standard fullExtranonce must accept empty submitted
    const en = fullExtranonce(ch, new Uint8Array(0));
    assert.equal(en.length, 8);
    assert.deepEqual(en, ch.extranoncePrefix);
});

test("ChannelTable: extended channel splits prefix + rolled extranonce", () => {
    const t = new ChannelTable();
    const ch = t.open({
        kind: "extended", requestId: 2, userIdentity: "bob",
        nominalHashRate: 1e6, defaultDifficulty: 2048, prefixLen: 4,
    });
    assert.equal(ch.extranoncePrefix.length, 4);
    assert.equal(ch.extranonceSize, 4);
    const en = fullExtranonce(ch, new Uint8Array([1, 2, 3, 4]));
    assert.deepEqual([...en.subarray(0, 4)], [...ch.extranoncePrefix]);
    assert.deepEqual([...en.subarray(4)], [1, 2, 3, 4]);
    assert.throws(() => fullExtranonce(ch, new Uint8Array([1, 2, 3]))); // wrong size
});

test("targetU256BE matches POOL_DIFF1 / shareDifficulty", () => {
    const t = targetU256BE(1);
    const got = bigIntFromBytesBE(t);
    assert.equal(got, POOL_DIFF1_TARGET);

    const t2 = targetU256BE(2);
    const got2 = bigIntFromBytesBE(t2);
    assert.ok(got2 < POOL_DIFF1_TARGET, "diff 2 target should be smaller than diff 1");
    assert.equal(maxTargetU256BE().length, 32);
});

test("validateDeclaredCoinbase accepts coinbase paying the pool", () => {
    const spk = addressToScriptPubKey(process.env.B3POOL_PAYOUT_ADDRESS!);
    assert.ok(spk, "payout SPK must encode");
    // Build a minimal coinbaseSuffix:
    //   sequence(4)=0xffffffff || varInt(out_count)=1 || out0
    // out0 = value(8)=10000 || varInt(spkLen) || spk || locktime(4)
    const seq = Uint8Array.from([0xff, 0xff, 0xff, 0xff]);
    const value = new Uint8Array(8);
    new DataView(value.buffer).setBigUint64(0, 10000n, true);
    const out0 = concatBytes(value, varInt(spk!.length), spk!);
    const locktime = new Uint8Array(4);
    const suffix = concatBytes(seq, Uint8Array.from([0x01]), out0, locktime);
    const r = validateDeclaredCoinbase(suffix, 1n);
    assert.equal(r.ok, true);
    assert.equal(r.poolValueSat, 10000n);
});

test("validateDeclaredCoinbase rejects coinbase that pays a different scriptPubKey", () => {
    const seq = Uint8Array.from([0xff, 0xff, 0xff, 0xff]);
    const value = new Uint8Array(8);
    new DataView(value.buffer).setBigUint64(0, 10000n, true);
    // Pay an unrelated 22-byte P2WPKH-like SPK (0x00 0x14 || 20 zero bytes).
    const otherSpk = Uint8Array.from([0x00, 0x14, ...new Array(20).fill(0)]);
    const out0 = concatBytes(value, varInt(otherSpk.length), otherSpk);
    const locktime = new Uint8Array(4);
    const suffix = concatBytes(seq, Uint8Array.from([0x01]), out0, locktime);
    const r = validateDeclaredCoinbase(suffix, 1n);
    assert.equal(r.ok, false);
    assert.equal(r.reason, "coinbase-does-not-pay-pool");
});

test("validateDeclaredCoinbase reports parse-error on truncated input", () => {
    const r = validateDeclaredCoinbase(Uint8Array.from([0xff, 0xff]), 1n);
    assert.equal(r.ok, false);
    assert.match(r.reason ?? "", /parse-error|coinbase-does-not-pay-pool/);
});
