// SV2 SubmitShares* -> existing V1 share-validator bridge.
//
// We take an SV2 share submission, reconstruct the same {extranonce1,
// extranonce2, ntime, nonce} shape the V1 validator expects, run it
// through validateShare(), and emit the same protocol-agnostic ShareEvent
// that the V1 stratum server emits. The pool daemon, PPLNS engine, and
// dashboard never need to know which protocol delivered the share.

import { validateShare, ShareCheck } from "../../stratum/share-validator";
import { JobContext } from "../../stratum/share-validator";
import { bytesToHex } from "../../lib/header";
import { ChannelState, fullExtranonce } from "./channel";
import { ShareEvent } from "../../lib/ipc";
import { submitBlock } from "../../lib/rpc";
import { Logger } from "../../lib/logger";

export interface SubmitArgs {
    channel: ChannelState;
    job: JobContext;
    sequenceNumber: number;
    nonce: number;
    ntime: number;
    version: number;
    /** Extranonce field carried in SubmitSharesExtended (empty for Standard). */
    extranonce: Uint8Array;
    /** Block height (for ShareEvent). */
    blockHeight: number;
    /** Network difficulty (for ShareEvent). */
    networkDifficulty?: number;
}

export type SubmitOutcome =
    | { ok: true; check: Extract<ShareCheck, { ok: true }>; event: ShareEvent }
    | { ok: false; reason: string };

export async function processSubmit(
    args: SubmitArgs,
    log: Logger,
): Promise<SubmitOutcome> {
    const en = fullExtranonce(args.channel, args.extranonce);
    const en1Hex = bytesToHex(en.subarray(0, args.channel.extranoncePrefix.length));
    const en2Hex = bytesToHex(en.subarray(args.channel.extranoncePrefix.length));
    const check = validateShare({
        job: args.job,
        extranonce1Hex: en1Hex,
        extranonce2Hex: en2Hex,
        ntime: args.ntime,
        nonce: args.nonce,
        shareDifficulty: args.channel.shareDifficulty,
    });
    if (!check.ok) return { ok: false, reason: check.reason };

    if (check.isBlock && check.serializedBlockHex) {
        try {
            await submitBlock(check.serializedBlockHex);
            log.info({ blockHash: check.blockHashHexBE, height: args.blockHeight }, "sv2 block submitted");
        } catch (e) {
            log.error({ err: (e as Error).message }, "sv2 submitBlock failed");
        }
    }

    const event: ShareEvent = {
        type: "share",
        user: args.channel.userIdentity,
        workerName: workerNameFromIdentity(args.channel.userIdentity),
        diff: args.channel.shareDifficulty,
        isBlock: check.isBlock,
        blockHash: check.isBlock ? check.blockHashHexBE : undefined,
        blockHeight: args.blockHeight,
        networkDifficulty: args.networkDifficulty,
        timestampMs: Date.now(),
    };
    return { ok: true, check, event };
}

function workerNameFromIdentity(id: string): string {
    const dot = id.indexOf(".");
    return dot >= 0 ? id.slice(dot + 1) : "default";
}
