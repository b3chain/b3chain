// Polls b3chaind getblocktemplate, builds Stratum job objects, broadcasts
// them to the StratumServer.

import { EventEmitter } from "events";
import { sha256 } from "@noble/hashes/sha2";
import { getBlockTemplate, BlockTemplate } from "../lib/rpc";
import { JobContext } from "./share-validator";
import { config } from "../config";
import { Logger } from "../lib/logger";
import {
    hexToBytes,
    reverseBytes,
    bytesToHex,
    varInt,
    concatBytes,
    uint32LE,
} from "../lib/header";
import { addressToScriptPubKey } from "../lib/address";

let jobCounter = 0;

export interface StratumJob extends JobContext {
    cleanJobs: boolean;
    ntimeMin: number;
    ntimeRoll: number;
}

export class JobManager extends EventEmitter {
    private timer: NodeJS.Timeout | null = null;
    private lastTemplateHash: string = "";
    private currentJob: StratumJob | null = null;
    private jobsById = new Map<string, StratumJob>();
    private maxJobs = 32;

    constructor(private log: Logger) {
        super();
    }

    start(): void {
        this.poll();
        this.timer = setInterval(() => this.poll(), config.pool.templatePollMs);
    }

    stop(): void {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
    }

    getCurrent(): StratumJob | null {
        return this.currentJob;
    }

    getById(id: string): StratumJob | undefined {
        return this.jobsById.get(id);
    }

    private async poll(): Promise<void> {
        let tpl: BlockTemplate;
        try {
            tpl = await getBlockTemplate();
        } catch (e) {
            this.log.warn({ err: (e as Error).message }, "getblocktemplate failed");
            this.emit("template-error", e);
            return;
        }
        const sig = `${tpl.previousblockhash}|${tpl.transactions.length}|${tpl.curtime}`;
        const isNew = sig !== this.lastTemplateHash;
        if (!isNew && this.currentJob) return;
        this.lastTemplateHash = sig;

        const job = this.buildJob(tpl);
        this.currentJob = job;
        this.jobsById.set(job.jobId, job);
        // Trim cache
        if (this.jobsById.size > this.maxJobs) {
            const oldest = this.jobsById.keys().next().value;
            if (oldest !== undefined) this.jobsById.delete(oldest);
        }
        this.emit("job", job);
        this.log.info({ jobId: job.jobId, height: job.height, txns: tpl.transactions.length }, "new job");
    }

    private buildJob(tpl: BlockTemplate): StratumJob {
        // Pool builds the coinbase locally, mirroring what every modern
        // mining pool does. b3chaind / Bitcoin Core 30+ no longer returns
        // `coinbasetxn` from getblocktemplate, so we compose it ourselves
        // from `coinbasevalue` and the pool's payout address.
        const { coinb1Hex, coinb2Hex } = buildCoinbase(
            tpl,
            config.rpc.payoutAddress,
            "/B3Chain Pool/"
        );

        const txns: string[] = [];
        const branches: string[] = [];
        for (const tx of tpl.transactions) {
            txns.push(tx.data);
            // The block merkle root is computed from txids (witness-stripped),
            // not wtxids. getblocktemplate returns the txid in `txid` for
            // segwit txs and falls back to `hash` for non-segwit txs (where
            // they are equal anyway).
            branches.push(tx.txid ?? tx.hash);
        }
        const merkleBranches = computeMerkleBranches(branches);

        jobCounter = (jobCounter + 1) % 0xfffffff;
        const jobId = jobCounter.toString(16).padStart(7, "0");

        const job: StratumJob = {
            jobId,
            coinb1Hex,
            coinb2Hex,
            merkleBranchesHexBE: merkleBranches,
            version: tpl.version,
            bits: parseInt(tpl.bits, 16),
            prevHashHexBE: tpl.previousblockhash,
            networkTargetHexBE: tpl.target,
            txnsHex: txns,
            height: tpl.height,
            cleanJobs: true,
            ntimeMin: tpl.mintime,
            ntimeRoll: tpl.curtime,
        };
        return job;
    }
}

// Encodes an integer as a minimal CScriptNum push (used for BIP34 height).
function scriptNumPush(n: number): Uint8Array {
    if (n === 0) return new Uint8Array([0x00]);
    const negative = n < 0;
    let abs = Math.abs(n);
    const bytes: number[] = [];
    while (abs > 0) {
        bytes.push(abs & 0xff);
        abs >>>= 8;
    }
    if (bytes[bytes.length - 1]! & 0x80) bytes.push(negative ? 0x80 : 0x00);
    else if (negative) bytes[bytes.length - 1] |= 0x80;
    const len = bytes.length;
    const out = new Uint8Array(1 + len);
    out[0] = len; // OP_PUSHBYTES_<len>
    out.set(bytes, 1);
    return out;
}

// Builds the full coinbase hex and pre-splits it into (coinb1, coinb2)
// around the 8-byte extranonce placeholder so the Stratum server can
// inject extranonce1 || extranonce2 between the halves at submission time.
//
// Layout of the coinbase scriptSig we emit:
//   <BIP34 height push> || <extranonce placeholder, 8 zero bytes> || <pool tag>
//
// Layout of the coinbase outputs:
//   vout[0] : coinbasevalue → P2WPKH(payoutAddress)
//   vout[1] : 0             → OP_RETURN witness commitment (when present
//                              in tpl.default_witness_commitment)
function buildCoinbase(
    tpl: BlockTemplate,
    payoutAddress: string,
    poolTag: string
): { coinb1Hex: string; coinb2Hex: string } {
    const spk = addressToScriptPubKey(payoutAddress);
    if (!spk) throw new Error(`B3POOL_PAYOUT_ADDRESS is not a valid bech32 address: ${payoutAddress}`);

    // ---- scriptSig (variable) -------------------------------------
    const heightPush = scriptNumPush(tpl.height);                  // BIP34 height
    const extranoncePlaceholder = new Uint8Array(8);               // 8 zero bytes
    const tagBytes = new TextEncoder().encode(poolTag);
    if (tagBytes.length > 75) throw new Error("pool tag too long");
    const tagPush = concatBytes(new Uint8Array([tagBytes.length]), tagBytes);

    const scriptSig = concatBytes(heightPush, extranoncePlaceholder, tagPush);
    if (scriptSig.length > 100) throw new Error("coinbase scriptSig > 100 bytes");

    // ---- vin[0] (the coinbase input) ------------------------------
    // Layout: prevout(36) || varInt(scriptSigLen) || scriptSig || sequence(4)
    // We don't materialize vin as one buffer because we need the split
    // to land inside scriptSig (between heightPush and tagPush).
    const prevout = new Uint8Array(36);                            // 32B null hash + 4B 0xffffffff
    prevout.fill(0xff, 32);
    const sequence = uint32LE(0xffffffff);

    // ---- vout list -----------------------------------------------
    const value = BigInt(tpl.coinbasevalue);
    const valueBytes = new Uint8Array(8);
    new DataView(valueBytes.buffer).setBigUint64(0, value, true);
    const vout0 = concatBytes(valueBytes, varInt(spk.length), spk);

    const vouts: Uint8Array[] = [vout0];
    if (tpl.default_witness_commitment) {
        const wcSpk = hexToBytes(tpl.default_witness_commitment);
        const zero = new Uint8Array(8);
        vouts.push(concatBytes(zero, varInt(wcSpk.length), wcSpk));
    }

    // ---- assemble tx (no segwit marker; coinbase has no witness) -
    const version = uint32LE(1);
    const txinCount = new Uint8Array([1]);
    const txoutCount = new Uint8Array([vouts.length]);
    const locktime = uint32LE(0);

    // The split must land ON the 8 placeholder bytes so the Stratum
    // server can splice extranonce1 || extranonce2 between coinb1 and
    // coinb2 at submit time. Build prefix and suffix explicitly rather
    // than searching the serialized form.
    const coinb1 = concatBytes(version, txinCount, prevout, varInt(scriptSig.length), heightPush);
    const coinb2 = concatBytes(tagPush, sequence, txoutCount, ...vouts, locktime);

    return {
        coinb1Hex: bytesToHex(coinb1),
        coinb2Hex: bytesToHex(coinb2),
    };
}

// Compute the Bitcoin-style merkle branches that the miner needs in order
// to reconstruct the merkle root from its own coinbase txid. branches[i]
// is the sibling hash to combine with the working hash at level i.
function computeMerkleBranches(txidsHexBE: string[]): string[] {
    if (txidsHexBE.length === 0) return [];
    const branches: string[] = [];
    let level: (string | null)[] = [null, ...txidsHexBE]; // null placeholder for coinbase
    while (level.length > 1) {
        const sibling = level[1];
        if (typeof sibling === "string") branches.push(sibling);
        const next: (string | null)[] = [null];
        for (let i = 2; i < level.length; i += 2) {
            const left = level[i];
            const right = i + 1 < level.length ? level[i + 1] : level[i];
            if (typeof left !== "string" || typeof right !== "string") {
                next.push(null);
            } else {
                next.push(combineHashesBE(left, right));
            }
        }
        level = next;
    }
    return branches;
}

function combineHashesBE(aBE: string, bBE: string): string {
    const a = reverseBytes(hexToBytes(aBE));
    const b = reverseBytes(hexToBytes(bBE));
    const concat = new Uint8Array(64);
    concat.set(a, 0);
    concat.set(b, 32);
    const dh = sha256(sha256(concat));
    return bytesToHex(reverseBytes(dh));
}
