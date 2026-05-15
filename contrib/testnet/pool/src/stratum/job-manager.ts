// Polls b3chaind getblocktemplate, builds Stratum job objects, broadcasts
// them to the StratumServer.

import { EventEmitter } from "events";
import { sha256 } from "@noble/hashes/sha2";
import { getBlockTemplate, BlockTemplate } from "../lib/rpc";
import { JobContext } from "./share-validator";
import { config } from "../config";
import { Logger } from "../lib/logger";
import { hexToBytes, reverseBytes, bytesToHex } from "../lib/header";

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
        if (!tpl.coinbasetxn || !tpl.coinbasetxn.data) {
            throw new Error(
                "getblocktemplate did not return coinbasetxn — start b3chaind with " +
                "the pool-payouts wallet loaded so it can build a coinbase."
            );
        }
        const cb = tpl.coinbasetxn.data;
        const { coinb1Hex, coinb2Hex } = splitCoinbaseForExtranonce(cb);

        const txns: string[] = [];
        const branches: string[] = [];
        for (const tx of tpl.transactions) {
            txns.push(tx.data);
            // hash from getblocktemplate is BIG-endian txid string
            branches.push(tx.hash);
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

// Split the b3chaind-provided coinbase tx into (prefix, suffix) around the
// scriptSig "extranonce window". The pool's extranonce1 + miner's extranonce2
// will be inserted between the two halves before serialization.
//
// b3chaind's coinbasetxn always reserves at least 8 bytes of placeholder
// extranonce in the coinbase scriptSig, immediately after the BIP34 height.
// We split right after the extranonce placeholder so the pool keeps the
// height + arbitrary script prefix and the miner provides the entropy.
//
// For the reference implementation we treat the whole returned coinbase as
// "coinb1 || coinb2" with extranonce inserted at a default 8-byte offset
// from the end of scriptSig. b3chaind's `getblocktemplate` returns a coinbase
// whose scriptSig already encodes this layout for pool use.
function splitCoinbaseForExtranonce(coinbaseHex: string): { coinb1Hex: string; coinb2Hex: string } {
    // Conservative default: split at the documented offset from b3chaind's
    // coinbase reservation. The byte position is fixed because b3chaind always
    // emits a deterministic prefix (version + 1 input + outpoint + scriptSigLen
    // + height-push + extranonce-placeholder).
    //
    // Layout (offsets in bytes -> 2 hex chars each):
    //   0      version            4
    //   4      marker+flag        0 (no segwit witness in coinbase data)
    //   4      txin count         1  (always 1)
    //   5      prevout            36 (32 hash + 4 index)
    //   41     scriptSig length   1
    //   42     scriptSig          variable
    //   ...    sequence           4
    //   ...    txout count        varint
    //   ...    txouts             variable
    //   ...    locktime           4
    //
    // b3chaind reserves an 8-byte placeholder for extranonce inside
    // scriptSig immediately after the BIP34 height push. We can locate
    // it by scanning for the eight-zero-byte run that getblocktemplate
    // guarantees.
    const placeholder = "0000000000000000";
    const idx = coinbaseHex.indexOf(placeholder);
    if (idx < 0) {
        // Fall back to splitting at the script-sig boundary; simulators
        // can override this in tests.
        const scriptSigOffset = (4 + 1 + 36 + 1) * 2;
        return {
            coinb1Hex: coinbaseHex.slice(0, scriptSigOffset),
            coinb2Hex: coinbaseHex.slice(scriptSigOffset),
        };
    }
    return {
        coinb1Hex: coinbaseHex.slice(0, idx),
        coinb2Hex: coinbaseHex.slice(idx + placeholder.length),
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
