// Unit tests for the SV2 type system, frame codec, and message round-trips.

import test from "node:test";
import * as assert from "node:assert/strict";
import {
    WriteBuf, ReadBuf, hexToBytes, bytesToHex,
} from "../src/sv2/lib/types";
import {
    encodeFrame, decodeHeader, splitFrames, SV2_HEADER_LEN, CHANNEL_MSG_FLAG,
} from "../src/sv2/lib/codec";
import {
    encodeSetupConnection, decodeSetupConnection, SubProtocol,
    encodeSetupConnectionSuccess, decodeSetupConnectionSuccess,
} from "../src/sv2/lib/messages/common";
import {
    encodeOpenStandardMiningChannel, decodeOpenStandardMiningChannel,
    encodeNewExtendedMiningJob, decodeNewExtendedMiningJob,
    encodeSetNewPrevHash, decodeSetNewPrevHash,
    encodeSubmitSharesExtended, decodeSubmitSharesExtended,
} from "../src/sv2/lib/messages/mining";
import {
    encodeNewTemplate, decodeNewTemplate,
    encodeSetNewPrevHashTP, decodeSetNewPrevHashTP,
} from "../src/sv2/lib/messages/tp";
import {
    encodeAllocateMiningJobToken, decodeAllocateMiningJobToken,
    encodeDeclareMiningJob, decodeDeclareMiningJob,
} from "../src/sv2/lib/messages/jd";

test("WriteBuf / ReadBuf primitive round-trip", () => {
    const w = new WriteBuf();
    w.u8(0xAB).u16(0x1234).u24(0x556677).u32(0xDEADBEEF).u64(0x0102030405060708n);
    w.bool(true).bool(false);
    w.b0_255(new Uint8Array([1, 2, 3])).b0_64k(new Uint8Array([9, 9])).b0_16m(new Uint8Array([7]));
    w.str0_255("hello sv2");
    w.u256(new Uint8Array(32).fill(0xCD));
    const out = w.finish();

    const r = new ReadBuf(out);
    assert.equal(r.u8(), 0xAB);
    assert.equal(r.u16(), 0x1234);
    assert.equal(r.u24(), 0x556677);
    assert.equal(r.u32(), 0xDEADBEEF);
    assert.equal(r.u64(), 0x0102030405060708n);
    assert.equal(r.bool(), true);
    assert.equal(r.bool(), false);
    assert.deepEqual([...r.b0_255()], [1, 2, 3]);
    assert.deepEqual([...r.b0_64k()], [9, 9]);
    assert.deepEqual([...r.b0_16m()], [7]);
    assert.equal(r.str0_255(), "hello sv2");
    assert.equal(bytesToHex(r.u256()), "cd".repeat(32));
    assert.equal(r.eof(), true);
});

test("hex helpers round-trip", () => {
    const v = hexToBytes("00ff10aa55");
    assert.deepEqual([...v], [0x00, 0xff, 0x10, 0xaa, 0x55]);
    assert.equal(bytesToHex(v), "00ff10aa55");
    assert.equal(bytesToHex(hexToBytes("0xCAFEBABE")), "cafebabe");
});

test("frame header encode/decode + channel-msg flag", () => {
    const payload = new Uint8Array([1, 2, 3, 4, 5]);
    const wire = encodeFrame(0, 0x16, payload, true);
    assert.equal(wire.length, SV2_HEADER_LEN + 5);
    const h = decodeHeader(wire);
    assert.equal(h.extensionType, 0);
    assert.equal(h.msgType, 0x16);
    assert.equal(h.msgLength, 5);
    assert.equal(h.channelMsg, true);

    // raw header bytes: extension_type LE
    assert.equal(wire[0], 0x00);
    assert.equal(wire[1], CHANNEL_MSG_FLAG >>> 8);
    assert.equal(wire[2], 0x16);
    assert.equal(wire[3], 5); assert.equal(wire[4], 0); assert.equal(wire[5], 0);
});

test("splitFrames handles partial trailing frame", () => {
    const a = encodeFrame(0, 0x10, new Uint8Array([1, 1, 1]));
    const b = encodeFrame(0, 0x11, new Uint8Array([2, 2, 2, 2]));
    const partial = b.subarray(0, b.length - 2);
    const buf = new Uint8Array(a.length + partial.length);
    buf.set(a, 0); buf.set(partial, a.length);
    const { frames, consumed } = splitFrames(buf);
    assert.equal(frames.length, 1);
    assert.equal(consumed, a.length);
});

test("SetupConnection round-trip", () => {
    const enc = encodeSetupConnection({
        protocol: SubProtocol.Mining,
        minVersion: 2, maxVersion: 2, flags: 0,
        endpointHost: "pool.b3chain.org", endpointPort: 3336,
        vendor: "b3", hardwareVersion: "x", firmware: "y", deviceId: "z",
    });
    const h = decodeHeader(enc);
    const dec = decodeSetupConnection(enc.slice(SV2_HEADER_LEN, SV2_HEADER_LEN + h.msgLength));
    assert.equal(dec.protocol, SubProtocol.Mining);
    assert.equal(dec.endpointHost, "pool.b3chain.org");
    assert.equal(dec.endpointPort, 3336);
    assert.equal(dec.deviceId, "z");
});

test("SetupConnection.Success round-trip", () => {
    const enc = encodeSetupConnectionSuccess({ usedVersion: 2, flags: 0 });
    const h = decodeHeader(enc);
    const dec = decodeSetupConnectionSuccess(enc.slice(SV2_HEADER_LEN, SV2_HEADER_LEN + h.msgLength));
    assert.equal(dec.usedVersion, 2);
});

test("OpenStandardMiningChannel round-trip", () => {
    const enc = encodeOpenStandardMiningChannel({
        requestId: 42, userIdentity: "alice.worker1",
        nominalHashRate: 1.5e9, maxTarget: new Uint8Array(32).fill(0xff),
    });
    const dec = decodeOpenStandardMiningChannel(enc.slice(SV2_HEADER_LEN));
    assert.equal(dec.requestId, 42);
    assert.equal(dec.userIdentity, "alice.worker1");
    assert.ok(Math.abs(dec.nominalHashRate - 1.5e9) / 1.5e9 < 1e-5);
});

test("NewExtendedMiningJob round-trip", () => {
    const merklePath = [new Uint8Array(32).fill(1), new Uint8Array(32).fill(2)];
    const enc = encodeNewExtendedMiningJob({
        channelId: 1, jobId: 7, minNtime: null, version: 0x20000000,
        versionRollingAllowed: true, merklePath,
        coinbaseTxPrefix: new Uint8Array([1, 2, 3]),
        coinbaseTxSuffix: new Uint8Array([4, 5, 6, 7]),
    });
    const h = decodeHeader(enc);
    assert.equal(h.channelMsg, true);
    const dec = decodeNewExtendedMiningJob(enc.slice(SV2_HEADER_LEN));
    assert.equal(dec.channelId, 1);
    assert.equal(dec.jobId, 7);
    assert.equal(dec.minNtime, null);
    assert.equal(dec.merklePath.length, 2);
    assert.deepEqual([...dec.coinbaseTxSuffix], [4, 5, 6, 7]);
});

test("SetNewPrevHash round-trip", () => {
    const enc = encodeSetNewPrevHash({
        channelId: 1, jobId: 7, prevHash: new Uint8Array(32).fill(0xab),
        minNtime: 1_700_000_000, nbits: 0x1d00ffff,
    });
    const dec = decodeSetNewPrevHash(enc.slice(SV2_HEADER_LEN));
    assert.equal(dec.minNtime, 1_700_000_000);
    assert.equal(dec.nbits, 0x1d00ffff);
});

test("SubmitSharesExtended round-trip", () => {
    const enc = encodeSubmitSharesExtended({
        channelId: 11, sequenceNumber: 99, jobId: 7,
        nonce: 0xCAFEBABE, ntime: 1_700_000_001, version: 0x20000000,
        extranonce: new Uint8Array([0, 0, 0, 0, 1, 2, 3, 4]),
    });
    const dec = decodeSubmitSharesExtended(enc.slice(SV2_HEADER_LEN));
    assert.equal(dec.channelId, 11);
    assert.equal(dec.sequenceNumber, 99);
    assert.equal(dec.nonce, 0xCAFEBABE);
    assert.equal(dec.extranonce.length, 8);
});

test("TP NewTemplate + SetNewPrevHash round-trip", () => {
    const tmpl = encodeNewTemplate({
        templateId: 12345n, futureTemplate: false, version: 0x20000000,
        coinbaseTxVersion: 1, coinbasePrefix: new Uint8Array([1, 2, 3]),
        coinbaseTxInputSequence: 0xffffffff, coinbaseTxValueRemaining: 5_000_000_000n,
        coinbaseTxOutputsCount: 1, coinbaseTxOutputs: new Uint8Array([9, 9, 9, 9]),
        coinbaseTxLocktime: 0, merklePath: [new Uint8Array(32).fill(7)],
    });
    const dec = decodeNewTemplate(tmpl.slice(SV2_HEADER_LEN));
    assert.equal(dec.templateId, 12345n);
    assert.equal(dec.coinbaseTxValueRemaining, 5_000_000_000n);

    const ph = encodeSetNewPrevHashTP({
        templateId: 12345n, prevHash: new Uint8Array(32).fill(0x01),
        headerTimestamp: 1_700_000_000, nbits: 0x1d00ffff,
        target: new Uint8Array(32).fill(0xff),
    });
    const phd = decodeSetNewPrevHashTP(ph.slice(SV2_HEADER_LEN));
    assert.equal(phd.headerTimestamp, 1_700_000_000);
});

test("JD AllocateMiningJobToken + DeclareMiningJob round-trip", () => {
    const a = encodeAllocateMiningJobToken({ userIdentifier: "alice", requestId: 1 });
    const ad = decodeAllocateMiningJobToken(a.slice(SV2_HEADER_LEN));
    assert.equal(ad.userIdentifier, "alice");

    const d = encodeDeclareMiningJob({
        requestId: 2, miningJobToken: new Uint8Array([0x55, 0xAA]),
        version: 0x20000000, coinbasePrefix: new Uint8Array([1]),
        coinbaseSuffix: new Uint8Array([2, 3]),
        txShortHashList: [new Uint8Array(32).fill(0x42)],
        txHashListHash: new Uint8Array(32).fill(0x77),
        excessData: new Uint8Array([]),
    });
    const dd = decodeDeclareMiningJob(d.slice(SV2_HEADER_LEN));
    assert.equal(dd.requestId, 2);
    assert.equal(dd.txShortHashList.length, 1);
});

// Golden vector: a hand-encoded SetupConnection.Success for {usedVersion:2, flags:0}
// must encode to exactly these bytes (extension_type=0, msg_type=0x01, msg_length=6).
test("SetupConnection.Success golden vector", () => {
    const enc = encodeSetupConnectionSuccess({ usedVersion: 2, flags: 0 });
    // 6-byte header (ext=0000, msg=01, len=060000) + 6-byte payload
    // (usedVersion=0200, flags=00000000) = 12 bytes total.
    assert.equal(bytesToHex(enc), "000001060000020000000000");
});
