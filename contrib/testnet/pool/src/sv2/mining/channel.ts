// Per-channel state for the Stratum V2 Mining Protocol pool.
//
// The pool gives every channel an `extranonce_prefix` that the miner must
// embed in the coinbase. For Standard channels we pin the full 8-byte
// extranonce slot to a per-channel random value (the miner only rolls
// nonce / ntime / version). For Extended channels we hand out a 4-byte
// prefix and let the miner roll the trailing 4 bytes via SubmitSharesExt.
// The actual extranonce slot is reconstructed at validation time as
//   prefix || rolledExtranonce.
//
// The total extranonce length matches the V1 layout (8 bytes), so the
// V1 share-validator can be reused unmodified.

import { randomBytes } from "node:crypto";
import { POOL_DIFF1_TARGET, targetFromShareDifficulty } from "../../lib/difficulty-math";

export const SV2_EXTRANONCE_TOTAL = 8;

export type ChannelKind = "standard" | "extended";

export interface ChannelState {
    id: number;                       // pool-assigned channel_id
    kind: ChannelKind;
    requestId: number;
    userIdentity: string;
    /** Pool-side prefix bytes glued in front of the miner-supplied extranonce. */
    extranoncePrefix: Uint8Array;
    /** Bytes the miner can roll. 0 for standard, (8 - prefix.length) for extended. */
    extranonceSize: number;
    /** Group channel that the miner asked to be part of (0 = none). */
    groupChannelId: number;
    /** Most recent share-difficulty target as 32-byte BE U256. */
    targetBE: Uint8Array;
    /** Floating share difficulty kept for vardiff bookkeeping. */
    shareDifficulty: number;
    /** Last sequence_number we accepted on this channel. */
    lastAcceptedSequence: number;
    /** Last job id we sent to this channel. */
    lastJobId: number;
    /** Last NewExtendedMiningJob clean-jobs decision. */
    cleanJobs: boolean;
}

export class ChannelTable {
    private byId = new Map<number, ChannelState>();
    private nextId = 1;

    open(opts: {
        kind: ChannelKind;
        requestId: number;
        userIdentity: string;
        nominalHashRate: number;
        defaultDifficulty: number;
        prefixLen?: number;
    }): ChannelState {
        const id = this.nextId++;
        const prefixLen = opts.kind === "standard"
            ? SV2_EXTRANONCE_TOTAL
            : Math.min(opts.prefixLen ?? 4, SV2_EXTRANONCE_TOTAL - 1);
        const extranoncePrefix = new Uint8Array(randomBytes(prefixLen));
        const extranonceSize = SV2_EXTRANONCE_TOTAL - prefixLen;
        const ch: ChannelState = {
            id,
            kind: opts.kind,
            requestId: opts.requestId,
            userIdentity: opts.userIdentity,
            extranoncePrefix,
            extranonceSize,
            groupChannelId: 0,
            targetBE: targetU256BE(opts.defaultDifficulty),
            shareDifficulty: opts.defaultDifficulty,
            lastAcceptedSequence: 0,
            lastJobId: 0,
            cleanJobs: true,
        };
        this.byId.set(id, ch);
        return ch;
    }

    get(id: number): ChannelState | undefined { return this.byId.get(id); }

    delete(id: number): void { this.byId.delete(id); }

    all(): ChannelState[] { return [...this.byId.values()]; }

    setShareDifficulty(id: number, diff: number): void {
        const c = this.byId.get(id);
        if (!c) return;
        c.shareDifficulty = diff;
        c.targetBE = targetU256BE(diff);
    }
}

/**
 * Encode a share-difficulty target as the 32-byte big-endian bytes that
 * SV2 puts on the wire (max_target / target U256). Higher difficulty
 * means smaller target.
 */
export function targetU256BE(shareDifficulty: number): Uint8Array {
    const t = targetFromShareDifficulty(shareDifficulty);
    return bigIntToBe32(t);
}

export function maxTargetU256BE(): Uint8Array {
    return bigIntToBe32(POOL_DIFF1_TARGET);
}

export function bigIntToBe32(n: bigint): Uint8Array {
    const out = new Uint8Array(32);
    let v = n;
    for (let i = 31; i >= 0; i--) {
        out[i] = Number(v & 0xffn);
        v >>= 8n;
    }
    return out;
}

/**
 * Reconstruct the full 8-byte extranonce slot from an SV2 channel + an
 * extranonce field carried in SubmitSharesExtended. Standard submits
 * pass an empty Uint8Array.
 */
export function fullExtranonce(ch: ChannelState, submitted: Uint8Array): Uint8Array {
    if (submitted.length !== ch.extranonceSize) {
        throw new Error(
            `extranonce length mismatch: channel expects ${ch.extranonceSize}, got ${submitted.length}`,
        );
    }
    const out = new Uint8Array(SV2_EXTRANONCE_TOTAL);
    out.set(ch.extranoncePrefix, 0);
    out.set(submitted, ch.extranoncePrefix.length);
    return out;
}
