// Stratum V2 Mining Protocol (extension_type = 0) messages.
//
// Reference: https://github.com/stratum-mining/sv2-spec/blob/main/05-Mining-Protocol.md

import { ReadBuf, WriteBuf } from "../types";
import { encodeFrame } from "../codec";

export const MINING_EXT = 0;

export const MSG_OPEN_STD_CHANNEL = 0x10;
export const MSG_OPEN_STD_CHANNEL_SUCCESS = 0x11;
export const MSG_OPEN_STD_CHANNEL_ERROR = 0x12;
export const MSG_OPEN_EXT_CHANNEL = 0x13;
export const MSG_OPEN_EXT_CHANNEL_SUCCESS = 0x14;
export const MSG_OPEN_EXT_CHANNEL_ERROR = 0x15;
export const MSG_NEW_MINING_JOB = 0x16;
export const MSG_NEW_EXT_MINING_JOB = 0x17;
export const MSG_SET_NEW_PREV_HASH = 0x18;
export const MSG_SET_TARGET = 0x19;
export const MSG_UPDATE_CHANNEL = 0x1a;
export const MSG_UPDATE_CHANNEL_ERROR = 0x1b;
export const MSG_CLOSE_CHANNEL = 0x1c;
export const MSG_SET_EXTRANONCE_PREFIX = 0x1d;
export const MSG_SUBMIT_SHARES_STANDARD = 0x1e;
export const MSG_SUBMIT_SHARES_EXTENDED = 0x1f;
export const MSG_SUBMIT_SHARES_SUCCESS = 0x20;
export const MSG_SUBMIT_SHARES_ERROR = 0x21;
export const MSG_SET_CUSTOM_MINING_JOB = 0x70;
export const MSG_SET_CUSTOM_MINING_JOB_SUCCESS = 0x71;
export const MSG_SET_CUSTOM_MINING_JOB_ERROR = 0x72;

// f32 helper (SV2 nominal_hash_rate)
function writeF32(w: WriteBuf, v: number): void {
    const b = new Uint8Array(4);
    new DataView(b.buffer).setFloat32(0, v, true);
    w.bytesRaw(b);
}
function readF32(r: ReadBuf): number {
    const b = r.bytesRaw(4);
    return new DataView(b.buffer, b.byteOffset, 4).getFloat32(0, true);
}

// ----------------- channel open -----------------

export interface OpenStandardMiningChannel {
    requestId: number;
    userIdentity: string;
    nominalHashRate: number;
    maxTarget: Uint8Array;
}

export function encodeOpenStandardMiningChannel(m: OpenStandardMiningChannel): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).str0_255(m.userIdentity);
    writeF32(w, m.nominalHashRate);
    w.u256(m.maxTarget);
    return encodeFrame(MINING_EXT, MSG_OPEN_STD_CHANNEL, w.finish());
}

export function decodeOpenStandardMiningChannel(payload: Uint8Array): OpenStandardMiningChannel {
    const r = new ReadBuf(payload);
    return {
        requestId: r.u32(),
        userIdentity: r.str0_255(),
        nominalHashRate: readF32(r),
        maxTarget: r.u256(),
    };
}

export interface OpenStandardMiningChannelSuccess {
    requestId: number;
    channelId: number;
    target: Uint8Array;
    extranoncePrefix: Uint8Array;
    groupChannelId: number;
}

export function encodeOpenStandardMiningChannelSuccess(m: OpenStandardMiningChannelSuccess): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).u32(m.channelId).u256(m.target).b0_255(m.extranoncePrefix).u32(m.groupChannelId);
    return encodeFrame(MINING_EXT, MSG_OPEN_STD_CHANNEL_SUCCESS, w.finish());
}

export function decodeOpenStandardMiningChannelSuccess(payload: Uint8Array): OpenStandardMiningChannelSuccess {
    const r = new ReadBuf(payload);
    return {
        requestId: r.u32(),
        channelId: r.u32(),
        target: r.u256(),
        extranoncePrefix: r.b0_255(),
        groupChannelId: r.u32(),
    };
}

export interface OpenExtendedMiningChannel {
    requestId: number;
    userIdentity: string;
    nominalHashRate: number;
    maxTarget: Uint8Array;
    minExtranonceSize: number;
}

export function encodeOpenExtendedMiningChannel(m: OpenExtendedMiningChannel): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).str0_255(m.userIdentity);
    writeF32(w, m.nominalHashRate);
    w.u256(m.maxTarget).u16(m.minExtranonceSize);
    return encodeFrame(MINING_EXT, MSG_OPEN_EXT_CHANNEL, w.finish());
}

export function decodeOpenExtendedMiningChannel(payload: Uint8Array): OpenExtendedMiningChannel {
    const r = new ReadBuf(payload);
    return {
        requestId: r.u32(),
        userIdentity: r.str0_255(),
        nominalHashRate: readF32(r),
        maxTarget: r.u256(),
        minExtranonceSize: r.u16(),
    };
}

export interface OpenExtendedMiningChannelSuccess {
    requestId: number;
    channelId: number;
    target: Uint8Array;
    extranonceSize: number;
    extranoncePrefix: Uint8Array;
}

export function encodeOpenExtendedMiningChannelSuccess(m: OpenExtendedMiningChannelSuccess): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).u32(m.channelId).u256(m.target).u16(m.extranonceSize).b0_255(m.extranoncePrefix);
    return encodeFrame(MINING_EXT, MSG_OPEN_EXT_CHANNEL_SUCCESS, w.finish());
}

export function decodeOpenExtendedMiningChannelSuccess(payload: Uint8Array): OpenExtendedMiningChannelSuccess {
    const r = new ReadBuf(payload);
    return {
        requestId: r.u32(),
        channelId: r.u32(),
        target: r.u256(),
        extranonceSize: r.u16(),
        extranoncePrefix: r.b0_255(),
    };
}

export interface OpenChannelError {
    requestId: number;
    errorCode: string;
}

export function encodeOpenChannelError(msgType: number, m: OpenChannelError): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.requestId).str0_255(m.errorCode);
    return encodeFrame(MINING_EXT, msgType, w.finish());
}

// ----------------- jobs -----------------

export interface NewMiningJob {
    channelId: number;
    jobId: number;
    minNtime: number | null; // OPTION u32
    version: number;
    merkleRoot: Uint8Array;
}

function encodeOptionU32(w: WriteBuf, v: number | null): void {
    if (v === null) { w.u8(0); return; }
    w.u8(1).u32(v >>> 0);
}
function decodeOptionU32(r: ReadBuf): number | null {
    const tag = r.u8();
    if (tag === 0) return null;
    return r.u32();
}

export function encodeNewMiningJob(m: NewMiningJob): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.jobId);
    encodeOptionU32(w, m.minNtime);
    w.u32(m.version >>> 0).u256(m.merkleRoot);
    return encodeFrame(MINING_EXT, MSG_NEW_MINING_JOB, w.finish(), true);
}

export function decodeNewMiningJob(payload: Uint8Array): NewMiningJob {
    const r = new ReadBuf(payload);
    return {
        channelId: r.u32(),
        jobId: r.u32(),
        minNtime: decodeOptionU32(r),
        version: r.u32(),
        merkleRoot: r.u256(),
    };
}

export interface NewExtendedMiningJob {
    channelId: number;
    jobId: number;
    minNtime: number | null;
    version: number;
    versionRollingAllowed: boolean;
    merklePath: Uint8Array[]; // SEQ0_255 of U256
    coinbaseTxPrefix: Uint8Array;
    coinbaseTxSuffix: Uint8Array;
}

export function encodeNewExtendedMiningJob(m: NewExtendedMiningJob): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.jobId);
    encodeOptionU32(w, m.minNtime);
    w.u32(m.version >>> 0).bool(m.versionRollingAllowed);
    w.seq0_255<Uint8Array>(m.merklePath, (ww, h) => ww.u256(h));
    w.b0_64k(m.coinbaseTxPrefix).b0_64k(m.coinbaseTxSuffix);
    return encodeFrame(MINING_EXT, MSG_NEW_EXT_MINING_JOB, w.finish(), true);
}

export function decodeNewExtendedMiningJob(payload: Uint8Array): NewExtendedMiningJob {
    const r = new ReadBuf(payload);
    return {
        channelId: r.u32(),
        jobId: r.u32(),
        minNtime: decodeOptionU32(r),
        version: r.u32(),
        versionRollingAllowed: r.bool(),
        merklePath: r.seq0_255<Uint8Array>(rr => rr.u256()),
        coinbaseTxPrefix: r.b0_64k(),
        coinbaseTxSuffix: r.b0_64k(),
    };
}

export interface SetNewPrevHash {
    channelId: number;
    jobId: number;
    prevHash: Uint8Array;
    minNtime: number;
    nbits: number;
}

export function encodeSetNewPrevHash(m: SetNewPrevHash): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.jobId).u256(m.prevHash).u32(m.minNtime >>> 0).u32(m.nbits >>> 0);
    return encodeFrame(MINING_EXT, MSG_SET_NEW_PREV_HASH, w.finish(), true);
}

export function decodeSetNewPrevHash(payload: Uint8Array): SetNewPrevHash {
    const r = new ReadBuf(payload);
    return {
        channelId: r.u32(),
        jobId: r.u32(),
        prevHash: r.u256(),
        minNtime: r.u32(),
        nbits: r.u32(),
    };
}

export interface SetTarget {
    channelId: number;
    maxTarget: Uint8Array;
}

export function encodeSetTarget(m: SetTarget): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u256(m.maxTarget);
    return encodeFrame(MINING_EXT, MSG_SET_TARGET, w.finish(), true);
}

export function decodeSetTarget(payload: Uint8Array): SetTarget {
    const r = new ReadBuf(payload);
    return { channelId: r.u32(), maxTarget: r.u256() };
}

// ----------------- channel mgmt -----------------

export interface CloseChannel {
    channelId: number;
    reasonCode: string;
}

export function encodeCloseChannel(m: CloseChannel): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).str0_255(m.reasonCode);
    return encodeFrame(MINING_EXT, MSG_CLOSE_CHANNEL, w.finish(), true);
}

export interface UpdateChannel {
    channelId: number;
    nominalHashRate: number;
    maxTarget: Uint8Array;
}

export function decodeUpdateChannel(payload: Uint8Array): UpdateChannel {
    const r = new ReadBuf(payload);
    return { channelId: r.u32(), nominalHashRate: readF32(r), maxTarget: r.u256() };
}

export interface SetExtranoncePrefix {
    channelId: number;
    extranoncePrefix: Uint8Array;
}

export function encodeSetExtranoncePrefix(m: SetExtranoncePrefix): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).b0_255(m.extranoncePrefix);
    return encodeFrame(MINING_EXT, MSG_SET_EXTRANONCE_PREFIX, w.finish(), true);
}

// ----------------- shares -----------------

export interface SubmitSharesStandard {
    channelId: number;
    sequenceNumber: number;
    jobId: number;
    nonce: number;
    ntime: number;
    version: number;
}

export function encodeSubmitSharesStandard(m: SubmitSharesStandard): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.sequenceNumber).u32(m.jobId)
        .u32(m.nonce >>> 0).u32(m.ntime >>> 0).u32(m.version >>> 0);
    return encodeFrame(MINING_EXT, MSG_SUBMIT_SHARES_STANDARD, w.finish(), true);
}

export function decodeSubmitSharesStandard(payload: Uint8Array): SubmitSharesStandard {
    const r = new ReadBuf(payload);
    return {
        channelId: r.u32(),
        sequenceNumber: r.u32(),
        jobId: r.u32(),
        nonce: r.u32(),
        ntime: r.u32(),
        version: r.u32(),
    };
}

export interface SubmitSharesExtended {
    channelId: number;
    sequenceNumber: number;
    jobId: number;
    nonce: number;
    ntime: number;
    version: number;
    extranonce: Uint8Array;
}

export function encodeSubmitSharesExtended(m: SubmitSharesExtended): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.sequenceNumber).u32(m.jobId)
        .u32(m.nonce >>> 0).u32(m.ntime >>> 0).u32(m.version >>> 0)
        .b0_255(m.extranonce);
    return encodeFrame(MINING_EXT, MSG_SUBMIT_SHARES_EXTENDED, w.finish(), true);
}

export function decodeSubmitSharesExtended(payload: Uint8Array): SubmitSharesExtended {
    const r = new ReadBuf(payload);
    return {
        channelId: r.u32(),
        sequenceNumber: r.u32(),
        jobId: r.u32(),
        nonce: r.u32(),
        ntime: r.u32(),
        version: r.u32(),
        extranonce: r.b0_255(),
    };
}

export interface SubmitSharesSuccess {
    channelId: number;
    lastSequenceNumber: number;
    newSubmitsAcceptedCount: number;
    newSharesSum: bigint;
}

export function encodeSubmitSharesSuccess(m: SubmitSharesSuccess): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.lastSequenceNumber).u32(m.newSubmitsAcceptedCount).u64(m.newSharesSum);
    return encodeFrame(MINING_EXT, MSG_SUBMIT_SHARES_SUCCESS, w.finish(), true);
}

export function decodeSubmitSharesSuccess(payload: Uint8Array): SubmitSharesSuccess {
    const r = new ReadBuf(payload);
    return {
        channelId: r.u32(),
        lastSequenceNumber: r.u32(),
        newSubmitsAcceptedCount: r.u32(),
        newSharesSum: r.u64(),
    };
}

export interface SubmitSharesError {
    channelId: number;
    sequenceNumber: number;
    errorCode: string;
}

export function encodeSubmitSharesError(m: SubmitSharesError): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.sequenceNumber).str0_255(m.errorCode);
    return encodeFrame(MINING_EXT, MSG_SUBMIT_SHARES_ERROR, w.finish(), true);
}

// ----------------- custom mining job (JD bridge) -----------------

export interface SetCustomMiningJob {
    channelId: number;
    requestId: number;
    miningJobToken: Uint8Array;
    version: number;
    prevHash: Uint8Array;
    minNtime: number;
    nbits: number;
    coinbaseTxVersion: number;
    coinbasePrefix: Uint8Array;
    coinbaseTxInputNSequence: number;
    coinbaseTxValueRemaining: bigint;
    coinbaseTxOutputs: Uint8Array;
    coinbaseTxLocktime: number;
    merklePath: Uint8Array[];
}

export function encodeSetCustomMiningJob(m: SetCustomMiningJob): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.requestId).b0_255(m.miningJobToken)
        .u32(m.version >>> 0).u256(m.prevHash).u32(m.minNtime >>> 0).u32(m.nbits >>> 0)
        .u32(m.coinbaseTxVersion >>> 0).b0_255(m.coinbasePrefix)
        .u32(m.coinbaseTxInputNSequence >>> 0).u64(m.coinbaseTxValueRemaining)
        .b0_64k(m.coinbaseTxOutputs).u32(m.coinbaseTxLocktime >>> 0)
        .seq0_255<Uint8Array>(m.merklePath, (ww, h) => ww.u256(h));
    return encodeFrame(MINING_EXT, MSG_SET_CUSTOM_MINING_JOB, w.finish(), true);
}

export interface SetCustomMiningJobSuccess {
    channelId: number;
    requestId: number;
    jobId: number;
}

export function encodeSetCustomMiningJobSuccess(m: SetCustomMiningJobSuccess): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.requestId).u32(m.jobId);
    return encodeFrame(MINING_EXT, MSG_SET_CUSTOM_MINING_JOB_SUCCESS, w.finish(), true);
}

export interface SetCustomMiningJobError {
    channelId: number;
    requestId: number;
    errorCode: string;
}

export function encodeSetCustomMiningJobError(m: SetCustomMiningJobError): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId).u32(m.requestId).str0_255(m.errorCode);
    return encodeFrame(MINING_EXT, MSG_SET_CUSTOM_MINING_JOB_ERROR, w.finish(), true);
}
