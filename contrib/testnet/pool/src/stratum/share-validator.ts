// Validate a single share submission against (a) the share-difficulty
// target and (b) the network block target.

import { sha256 } from "@noble/hashes/sha2";
import { blake3d } from "../lib/blake3";
import {
    HeaderInput,
    serializeHeader,
    bytesToHex,
    reverseBytes,
    coinbaseTxId,
    computeMerkleRoot,
    hexToBytes,
    concatBytes,
    varInt,
} from "../lib/header";
import {
    bigIntFromBytesLE,
    targetFromShareDifficulty,
} from "../lib/difficulty-math";

export type ShareCheckOk = {
    ok: true;
    isBlock: boolean;
    powHashHexBE: string;
    powInt: bigint;
    blockHashHexBE: string;
    serializedHeader: Uint8Array;
    serializedBlockHex?: string;
};

export type ShareCheckFail = {
    ok: false;
    reason: "stale" | "duplicate" | "low-diff" | "invalid";
    detail?: string;
};

export type ShareCheck = ShareCheckOk | ShareCheckFail;

export interface JobContext {
    jobId: string;
    coinb1Hex: string;
    coinb2Hex: string;
    merkleBranchesHexBE: string[];
    version: number;
    bits: number;
    prevHashHexBE: string;
    networkTargetHexBE: string;
    txnsHex: string[];
    height: number;
}

export interface ShareInput {
    job: JobContext;
    extranonce1Hex: string;
    extranonce2Hex: string;
    ntime: number;
    nonce: number;
    shareDifficulty: number;
}

export function buildHeader(s: ShareInput): { header: Uint8Array; coinbase: Uint8Array; merkleRootLE: Uint8Array } {
    const coinb1 = hexToBytes(s.job.coinb1Hex);
    const en1 = hexToBytes(s.extranonce1Hex);
    const en2 = hexToBytes(s.extranonce2Hex);
    const coinb2 = hexToBytes(s.job.coinb2Hex);
    const coinbase = concatBytes(coinb1, en1, en2, coinb2);
    const cbTxid = coinbaseTxId(coinbase);
    const merkleRoot = computeMerkleRoot(cbTxid, s.job.merkleBranchesHexBE);
    const headerInput: HeaderInput = {
        version: s.job.version,
        prevHashHexBE: s.job.prevHashHexBE,
        merkleRootHexBE: bytesToHex(reverseBytes(merkleRoot)),
        ntime: s.ntime,
        bits: s.job.bits,
        nonce: s.nonce,
    };
    return { header: serializeHeader(headerInput), coinbase, merkleRootLE: merkleRoot };
}

export function validateShare(s: ShareInput): ShareCheck {
    let header: Uint8Array;
    let coinbase: Uint8Array;
    try {
        const built = buildHeader(s);
        header = built.header;
        coinbase = built.coinbase;
    } catch (e) {
        return { ok: false, reason: "invalid", detail: (e as Error).message };
    }

    const powLE = blake3d(header);
    const powInt = bigIntFromBytesLE(powLE);

    // Network target (BE-display hex like getblocktemplate gives us).
    const networkTarget = bigIntFromBytesLE(reverseBytes(hexToBytes(s.job.networkTargetHexBE)));

    // Share target derived from current connection difficulty.
    const shareTarget = targetFromShareDifficulty(s.shareDifficulty);

    if (powInt > shareTarget) {
        return { ok: false, reason: "low-diff" };
    }

    const isBlock = powInt <= networkTarget;
    const blockHashLE = doubleSha256Local(header);
    const blockHashHexBE = bytesToHex(reverseBytes(blockHashLE));

    let serializedBlockHex: string | undefined;
    if (isBlock) {
        serializedBlockHex = serializeBlockHex(header, [coinbase, ...s.job.txnsHex.map((h) => hexToBytes(h))]);
    }

    return {
        ok: true,
        isBlock,
        powHashHexBE: bytesToHex(reverseBytes(powLE)),
        powInt,
        blockHashHexBE,
        serializedHeader: header,
        serializedBlockHex,
    };
}

function doubleSha256Local(b: Uint8Array): Uint8Array {
    return sha256(sha256(b));
}

function serializeBlockHex(header: Uint8Array, txns: Uint8Array[]): string {
    const parts: Uint8Array[] = [header, varInt(txns.length), ...txns];
    return bytesToHex(concatBytes(...parts));
}
