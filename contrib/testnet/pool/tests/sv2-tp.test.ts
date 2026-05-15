// Unit tests for TP message round-trips. The poller itself requires a
// live b3chaind RPC; that is exercised in the e2e suite. Here we just
// confirm that NewTemplate and SetNewPrevHashTP frames are
// wire-symmetric end to end.

import test from "node:test";
import * as assert from "node:assert/strict";
import {
    encodeNewTemplate, decodeNewTemplate,
    encodeSetNewPrevHashTP, decodeSetNewPrevHashTP,
    encodeRequestTransactionData, decodeRequestTransactionData,
    encodeRequestTransactionDataSuccess, decodeRequestTransactionDataSuccess,
    encodeSubmitSolutionTP, decodeSubmitSolutionTP,
    encodeCoinbaseOutputDataSize, decodeCoinbaseOutputDataSize,
} from "../src/sv2/lib/messages/tp";
import { SV2_HEADER_LEN } from "../src/sv2/lib/codec";

test("NewTemplate round-trip", () => {
    const merkle = [new Uint8Array(32).fill(7), new Uint8Array(32).fill(11)];
    const enc = encodeNewTemplate({
        templateId: 999n,
        futureTemplate: false,
        version: 0x20000000,
        coinbaseTxVersion: 1,
        coinbasePrefix: new Uint8Array([1, 2, 3]),
        coinbaseTxInputSequence: 0xffffffff,
        coinbaseTxValueRemaining: 5_000_000_000n,
        coinbaseTxOutputsCount: 2,
        coinbaseTxOutputs: new Uint8Array([0xaa, 0xbb, 0xcc]),
        coinbaseTxLocktime: 0,
        merklePath: merkle,
    });
    const dec = decodeNewTemplate(enc.slice(SV2_HEADER_LEN));
    assert.equal(dec.templateId, 999n);
    assert.equal(dec.coinbaseTxValueRemaining, 5_000_000_000n);
    assert.deepEqual([...dec.coinbaseTxOutputs], [0xaa, 0xbb, 0xcc]);
    assert.equal(dec.merklePath.length, 2);
});

test("SetNewPrevHashTP round-trip", () => {
    const enc = encodeSetNewPrevHashTP({
        templateId: 42n,
        prevHash: new Uint8Array(32).fill(0x55),
        headerTimestamp: 1_700_000_000,
        nbits: 0x1d00ffff,
        target: new Uint8Array(32).fill(0xff),
    });
    const dec = decodeSetNewPrevHashTP(enc.slice(SV2_HEADER_LEN));
    assert.equal(dec.templateId, 42n);
    assert.equal(dec.headerTimestamp, 1_700_000_000);
    assert.equal(dec.nbits, 0x1d00ffff);
});

test("CoinbaseOutputDataSize round-trip", () => {
    const enc = encodeCoinbaseOutputDataSize({ coinbaseOutputMaxAdditionalSize: 100 });
    const dec = decodeCoinbaseOutputDataSize(enc.slice(SV2_HEADER_LEN));
    assert.equal(dec.coinbaseOutputMaxAdditionalSize, 100);
});

test("RequestTransactionData + Success round-trip", () => {
    const req = encodeRequestTransactionData({ templateId: 7n });
    const reqDec = decodeRequestTransactionData(req.slice(SV2_HEADER_LEN));
    assert.equal(reqDec.templateId, 7n);

    const txs = [new Uint8Array([0xaa, 0xbb]), new Uint8Array([0xcc])];
    const resp = encodeRequestTransactionDataSuccess({
        templateId: 7n, excessData: new Uint8Array(0), transactionList: txs,
    });
    const respDec = decodeRequestTransactionDataSuccess(resp.slice(SV2_HEADER_LEN));
    assert.equal(respDec.transactionList.length, 2);
    assert.deepEqual([...respDec.transactionList[1]!], [0xcc]);
});

test("SubmitSolutionTP round-trip", () => {
    const enc = encodeSubmitSolutionTP({
        templateId: 9n, version: 0x20000000, headerTimestamp: 1_700_000_001,
        headerNonce: 0xdeadbeef, coinbaseTx: new Uint8Array([1, 2, 3, 4]),
    });
    const dec = decodeSubmitSolutionTP(enc.slice(SV2_HEADER_LEN));
    assert.equal(dec.templateId, 9n);
    assert.equal(dec.headerNonce, 0xdeadbeef);
    assert.deepEqual([...dec.coinbaseTx], [1, 2, 3, 4]);
});
