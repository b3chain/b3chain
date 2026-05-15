// Convert a V1-shaped JobContext (the in-process JobManager's output) into
// SV2 NewExtendedMiningJob / NewMiningJob + SetNewPrevHash messages.
//
// We deliberately reuse the existing V1 JobManager so the pool sees one
// canonical view of templates and the SV2 + V1 coinbase / payout policy
// stays in sync. The conversion is purely a wire transformation.

import { sha256 } from "@noble/hashes/sha2";
import {
    encodeNewExtendedMiningJob, encodeNewMiningJob,
    encodeSetNewPrevHash, encodeSetTarget,
    NewExtendedMiningJob, NewMiningJob, SetNewPrevHash, SetTarget,
} from "../lib/messages/mining";
import {
    hexToBytes, reverseBytes, bytesToHex, concatBytes,
} from "../../lib/header";
import { StratumJob } from "../../stratum/job-manager";
import { ChannelState, fullExtranonce } from "./channel";

let sv2JobIdCounter = 0;

export function nextSv2JobId(): number {
    sv2JobIdCounter = (sv2JobIdCounter + 1) >>> 0;
    return sv2JobIdCounter;
}

/**
 * SV2 wants a list of internal-LE 32-byte hashes for the merkle path.
 * Our JobContext stores merkle branches as BE display-hex (because the
 * V1 wire format is BE), so reverse + decode each one.
 */
export function merklePathLE(job: StratumJob): Uint8Array[] {
    return job.merkleBranchesHexBE.map(h => reverseBytes(hexToBytes(h)));
}

/** Encode a NewExtendedMiningJob frame for an Extended channel. */
export function buildNewExtendedJob(ch: ChannelState, job: StratumJob, jobId: number): {
    msg: NewExtendedMiningJob; bytes: Uint8Array;
} {
    const msg: NewExtendedMiningJob = {
        channelId: ch.id,
        jobId,
        minNtime: null,
        version: job.version,
        versionRollingAllowed: true,
        merklePath: merklePathLE(job),
        coinbaseTxPrefix: hexToBytes(job.coinb1Hex),
        coinbaseTxSuffix: hexToBytes(job.coinb2Hex),
    };
    return { msg, bytes: encodeNewExtendedMiningJob(msg) };
}

/**
 * Encode a NewMiningJob frame for a Standard channel. Standard miners
 * receive a fully-baked merkle root (with the channel's fixed extranonce
 * already folded in) so they can mine without seeing the coinbase.
 */
export function buildNewStandardJob(ch: ChannelState, job: StratumJob, jobId: number): {
    msg: NewMiningJob; bytes: Uint8Array; merkleRootLE: Uint8Array;
} {
    const en = fullExtranonce(ch, new Uint8Array(0));
    const coinbase = concatBytes(hexToBytes(job.coinb1Hex), en, hexToBytes(job.coinb2Hex));
    const cbTxid = sha256(sha256(coinbase));
    const merkleRootLE = computeMerkleRootLE(cbTxid, job.merkleBranchesHexBE);
    const msg: NewMiningJob = {
        channelId: ch.id,
        jobId,
        minNtime: null,
        version: job.version,
        merkleRoot: merkleRootLE,
    };
    return { msg, bytes: encodeNewMiningJob(msg), merkleRootLE };
}

function computeMerkleRootLE(coinbaseTxidLE: Uint8Array, branchesBE: string[]): Uint8Array {
    let cur = coinbaseTxidLE;
    for (const bBE of branchesBE) {
        const sib = reverseBytes(hexToBytes(bBE));
        const buf = new Uint8Array(64);
        buf.set(cur, 0);
        buf.set(sib, 32);
        cur = sha256(sha256(buf));
    }
    return cur;
}

/** SetNewPrevHash for the channel. SV2 expects the prev hash in LE form. */
export function buildSetNewPrevHash(ch: ChannelState, job: StratumJob, jobId: number): {
    msg: SetNewPrevHash; bytes: Uint8Array;
} {
    const msg: SetNewPrevHash = {
        channelId: ch.id,
        jobId,
        prevHash: reverseBytes(hexToBytes(job.prevHashHexBE)),
        minNtime: job.ntimeMin,
        nbits: job.bits,
    };
    return { msg, bytes: encodeSetNewPrevHash(msg) };
}

export function buildSetTarget(ch: ChannelState): { msg: SetTarget; bytes: Uint8Array } {
    const msg: SetTarget = { channelId: ch.id, maxTarget: ch.targetBE };
    return { msg, bytes: encodeSetTarget(msg) };
}

// Re-export for callers that already have the JobContext fields.
export { bytesToHex };
