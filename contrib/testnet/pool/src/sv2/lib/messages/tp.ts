// Stratum V2 Template Distribution Protocol messages.
//
// Reference: https://github.com/stratum-mining/sv2-spec/blob/main/07-Template-Distribution-Protocol.md

import { ReadBuf, WriteBuf } from "../types";
import { encodeFrame } from "../codec";

export const TP_EXT = 0;

export const MSG_COINBASE_OUTPUT_DATA_SIZE = 0x70;
export const MSG_NEW_TEMPLATE = 0x71;
export const MSG_SET_NEW_PREV_HASH_TP = 0x72;
export const MSG_REQUEST_TX_DATA = 0x73;
export const MSG_REQUEST_TX_DATA_SUCCESS = 0x74;
export const MSG_REQUEST_TX_DATA_ERROR = 0x75;
export const MSG_SUBMIT_SOLUTION_TP = 0x76;

export interface CoinbaseOutputDataSize {
    coinbaseOutputMaxAdditionalSize: number;
}

export function encodeCoinbaseOutputDataSize(m: CoinbaseOutputDataSize): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.coinbaseOutputMaxAdditionalSize >>> 0);
    return encodeFrame(TP_EXT, MSG_COINBASE_OUTPUT_DATA_SIZE, w.finish());
}

export function decodeCoinbaseOutputDataSize(payload: Uint8Array): CoinbaseOutputDataSize {
    const r = new ReadBuf(payload);
    return { coinbaseOutputMaxAdditionalSize: r.u32() };
}

export interface NewTemplate {
    templateId: bigint;
    futureTemplate: boolean;
    version: number;
    coinbaseTxVersion: number;
    coinbasePrefix: Uint8Array;
    coinbaseTxInputSequence: number;
    coinbaseTxValueRemaining: bigint;
    coinbaseTxOutputsCount: number;
    coinbaseTxOutputs: Uint8Array;
    coinbaseTxLocktime: number;
    merklePath: Uint8Array[];
}

export function encodeNewTemplate(m: NewTemplate): Uint8Array {
    const w = new WriteBuf();
    w.u64(m.templateId).bool(m.futureTemplate)
        .u32(m.version >>> 0).u32(m.coinbaseTxVersion >>> 0)
        .b0_255(m.coinbasePrefix).u32(m.coinbaseTxInputSequence >>> 0)
        .u64(m.coinbaseTxValueRemaining).u32(m.coinbaseTxOutputsCount >>> 0)
        .b0_64k(m.coinbaseTxOutputs).u32(m.coinbaseTxLocktime >>> 0)
        .seq0_255<Uint8Array>(m.merklePath, (ww, h) => ww.u256(h));
    return encodeFrame(TP_EXT, MSG_NEW_TEMPLATE, w.finish());
}

export function decodeNewTemplate(payload: Uint8Array): NewTemplate {
    const r = new ReadBuf(payload);
    return {
        templateId: r.u64(),
        futureTemplate: r.bool(),
        version: r.u32(),
        coinbaseTxVersion: r.u32(),
        coinbasePrefix: r.b0_255(),
        coinbaseTxInputSequence: r.u32(),
        coinbaseTxValueRemaining: r.u64(),
        coinbaseTxOutputsCount: r.u32(),
        coinbaseTxOutputs: r.b0_64k(),
        coinbaseTxLocktime: r.u32(),
        merklePath: r.seq0_255<Uint8Array>(rr => rr.u256()),
    };
}

export interface SetNewPrevHashTP {
    templateId: bigint;
    prevHash: Uint8Array;
    headerTimestamp: number;
    nbits: number;
    target: Uint8Array;
}

export function encodeSetNewPrevHashTP(m: SetNewPrevHashTP): Uint8Array {
    const w = new WriteBuf();
    w.u64(m.templateId).u256(m.prevHash).u32(m.headerTimestamp >>> 0).u32(m.nbits >>> 0).u256(m.target);
    return encodeFrame(TP_EXT, MSG_SET_NEW_PREV_HASH_TP, w.finish());
}

export function decodeSetNewPrevHashTP(payload: Uint8Array): SetNewPrevHashTP {
    const r = new ReadBuf(payload);
    return {
        templateId: r.u64(),
        prevHash: r.u256(),
        headerTimestamp: r.u32(),
        nbits: r.u32(),
        target: r.u256(),
    };
}

export interface RequestTransactionData {
    templateId: bigint;
}

export function encodeRequestTransactionData(m: RequestTransactionData): Uint8Array {
    const w = new WriteBuf();
    w.u64(m.templateId);
    return encodeFrame(TP_EXT, MSG_REQUEST_TX_DATA, w.finish());
}

export function decodeRequestTransactionData(payload: Uint8Array): RequestTransactionData {
    const r = new ReadBuf(payload);
    return { templateId: r.u64() };
}

export interface RequestTransactionDataSuccess {
    templateId: bigint;
    excessData: Uint8Array;
    transactionList: Uint8Array[]; // SEQ0_64K of B0_16M
}

export function encodeRequestTransactionDataSuccess(m: RequestTransactionDataSuccess): Uint8Array {
    const w = new WriteBuf();
    w.u64(m.templateId).b0_64k(m.excessData);
    w.seq0_64k<Uint8Array>(m.transactionList, (ww, t) => ww.b0_16m(t));
    return encodeFrame(TP_EXT, MSG_REQUEST_TX_DATA_SUCCESS, w.finish());
}

export function decodeRequestTransactionDataSuccess(payload: Uint8Array): RequestTransactionDataSuccess {
    const r = new ReadBuf(payload);
    return {
        templateId: r.u64(),
        excessData: r.b0_64k(),
        transactionList: r.seq0_64k<Uint8Array>(rr => rr.b0_16m()),
    };
}

export interface SubmitSolutionTP {
    templateId: bigint;
    version: number;
    headerTimestamp: number;
    headerNonce: number;
    coinbaseTx: Uint8Array;
}

export function encodeSubmitSolutionTP(m: SubmitSolutionTP): Uint8Array {
    const w = new WriteBuf();
    w.u64(m.templateId).u32(m.version >>> 0).u32(m.headerTimestamp >>> 0).u32(m.headerNonce >>> 0).b0_64k(m.coinbaseTx);
    return encodeFrame(TP_EXT, MSG_SUBMIT_SOLUTION_TP, w.finish());
}

export function decodeSubmitSolutionTP(payload: Uint8Array): SubmitSolutionTP {
    const r = new ReadBuf(payload);
    return {
        templateId: r.u64(),
        version: r.u32(),
        headerTimestamp: r.u32(),
        headerNonce: r.u32(),
        coinbaseTx: r.b0_64k(),
    };
}
