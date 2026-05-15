// Stratum V2 Job Declaration Protocol messages.
//
// Reference: https://github.com/stratum-mining/sv2-spec/blob/main/06-Job-Declaration-Protocol.md

import { ReadBuf, WriteBuf } from "../types";
import { encodeFrame } from "../codec";

export const JD_EXT = 0;

export const MSG_ALLOCATE_JOB_TOKEN = 0x50;
export const MSG_ALLOCATE_JOB_TOKEN_SUCCESS = 0x51;
export const MSG_DECLARE_MINING_JOB = 0x57;
export const MSG_DECLARE_MINING_JOB_SUCCESS = 0x58;
export const MSG_DECLARE_MINING_JOB_ERROR = 0x59;
export const MSG_IDENTIFY_TRANSACTIONS = 0x5a;
export const MSG_IDENTIFY_TRANSACTIONS_SUCCESS = 0x5b;
export const MSG_PROVIDE_MISSING_TRANSACTIONS = 0x5c;
export const MSG_PROVIDE_MISSING_TRANSACTIONS_SUCCESS = 0x5d;
export const MSG_SUBMIT_SOLUTION_JD = 0x60;

export interface AllocateMiningJobToken {
    userIdentifier: string;
    requestId: number;
}

export function encodeAllocateMiningJobToken(m: AllocateMiningJobToken): Uint8Array {
    const w = new WriteBuf();
    w.str0_255(m.userIdentifier).u32(m.requestId);
    return encodeFrame(JD_EXT, MSG_ALLOCATE_JOB_TOKEN, w.finish());
}

export function decodeAllocateMiningJobToken(payload: Uint8Array): AllocateMiningJobToken {
    const r = new ReadBuf(payload);
    return { userIdentifier: r.str0_255(), requestId: r.u32() };
}

export interface AllocateMiningJobTokenSuccess {
    requestId: number;
    miningJobToken: Uint8Array;
    coinbaseOutputMaxAdditionalSize: number;
    asyncMiningAllowed: boolean;
    coinbaseOutput: Uint8Array;
}

export function encodeAllocateMiningJobTokenSuccess(m: AllocateMiningJobTokenSuccess): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).b0_255(m.miningJobToken)
        .u32(m.coinbaseOutputMaxAdditionalSize >>> 0)
        .bool(m.asyncMiningAllowed)
        .b0_64k(m.coinbaseOutput);
    return encodeFrame(JD_EXT, MSG_ALLOCATE_JOB_TOKEN_SUCCESS, w.finish());
}

export function decodeAllocateMiningJobTokenSuccess(payload: Uint8Array): AllocateMiningJobTokenSuccess {
    const r = new ReadBuf(payload);
    return {
        requestId: r.u32(),
        miningJobToken: r.b0_255(),
        coinbaseOutputMaxAdditionalSize: r.u32(),
        asyncMiningAllowed: r.bool(),
        coinbaseOutput: r.b0_64k(),
    };
}

export interface DeclareMiningJob {
    requestId: number;
    miningJobToken: Uint8Array;
    version: number;
    coinbasePrefix: Uint8Array;
    coinbaseSuffix: Uint8Array;
    txShortHashList: Uint8Array[]; // SEQ0_64K of U256
    txHashListHash: Uint8Array;
    excessData: Uint8Array;
}

export function encodeDeclareMiningJob(m: DeclareMiningJob): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).b0_255(m.miningJobToken).u32(m.version >>> 0)
        .b0_255(m.coinbasePrefix).b0_64k(m.coinbaseSuffix)
        .seq0_64k<Uint8Array>(m.txShortHashList, (ww, h) => ww.u256(h))
        .u256(m.txHashListHash).b0_64k(m.excessData);
    return encodeFrame(JD_EXT, MSG_DECLARE_MINING_JOB, w.finish());
}

export function decodeDeclareMiningJob(payload: Uint8Array): DeclareMiningJob {
    const r = new ReadBuf(payload);
    return {
        requestId: r.u32(),
        miningJobToken: r.b0_255(),
        version: r.u32(),
        coinbasePrefix: r.b0_255(),
        coinbaseSuffix: r.b0_64k(),
        txShortHashList: r.seq0_64k<Uint8Array>(rr => rr.u256()),
        txHashListHash: r.u256(),
        excessData: r.b0_64k(),
    };
}

export interface DeclareMiningJobSuccess {
    requestId: number;
    newMiningJobToken: Uint8Array;
}

export function encodeDeclareMiningJobSuccess(m: DeclareMiningJobSuccess): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).b0_255(m.newMiningJobToken);
    return encodeFrame(JD_EXT, MSG_DECLARE_MINING_JOB_SUCCESS, w.finish());
}

export interface DeclareMiningJobError {
    requestId: number;
    errorCode: string;
    errorDetails: Uint8Array;
}

export function encodeDeclareMiningJobError(m: DeclareMiningJobError): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).str0_255(m.errorCode).b0_64k(m.errorDetails);
    return encodeFrame(JD_EXT, MSG_DECLARE_MINING_JOB_ERROR, w.finish());
}

export interface SubmitSolutionJD {
    extranonce: Uint8Array;
    prevHash: Uint8Array;
    ntime: number;
    nonce: number;
    nbits: number;
    version: number;
}

export function encodeSubmitSolutionJD(m: SubmitSolutionJD): Uint8Array {
    const w = new WriteBuf();
    w.b0_255(m.extranonce).u256(m.prevHash).u32(m.ntime >>> 0).u32(m.nonce >>> 0)
        .u32(m.nbits >>> 0).u32(m.version >>> 0);
    return encodeFrame(JD_EXT, MSG_SUBMIT_SOLUTION_JD, w.finish());
}
