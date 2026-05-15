// SV2 Template Distribution poller.
//
// Polls b3chaind's getblocktemplate at the configured cadence and emits
// "template" events containing fully-shaped SV2 NewTemplate +
// SetNewPrevHashTP descriptors. Distinct from JobManager because the SV2
// TD layer needs raw transaction bytes (for RequestTransactionData) while
// the V1 mining path only needs txids + transaction hex.

import { EventEmitter } from "events";
import { config } from "../../config";
import { Logger } from "../../lib/logger";
import { getBlockTemplate, BlockTemplate } from "../../lib/rpc";
import { addressToScriptPubKey } from "../../lib/address";
import {
    hexToBytes, bytesToHex, reverseBytes, varInt, concatBytes, uint32LE,
} from "../../lib/header";
import {
    NewTemplate, SetNewPrevHashTP,
    encodeNewTemplate, encodeSetNewPrevHashTP,
} from "../lib/messages/tp";
import { sha256 } from "@noble/hashes/sha2";

let templateCounter = 0n;

export interface TpTemplateBundle {
    templateId: bigint;
    height: number;
    bits: number;
    coinbaseValue: bigint;
    /** Encoded NewTemplate frame bytes ready to send. */
    newTemplate: NewTemplate;
    newTemplateBytes: Uint8Array;
    /** Encoded SetNewPrevHash (TP variant) frame bytes ready to send. */
    setNewPrevHash: SetNewPrevHashTP;
    setNewPrevHashBytes: Uint8Array;
    /** Raw tx bytes (excludes coinbase). Used for RequestTransactionData. */
    transactionList: Uint8Array[];
    /** Stable b3chaind hash of (prevhash + tx_count + curtime). */
    sig: string;
}

export class TpPoller extends EventEmitter {
    private timer: NodeJS.Timeout | null = null;
    private lastSig = "";
    private current: TpTemplateBundle | null = null;
    private templateCache = new Map<bigint, TpTemplateBundle>();

    constructor(private log: Logger) { super(); }

    start(): void {
        void this.poll();
        this.timer = setInterval(() => void this.poll(), config.tp.pollMs);
    }

    stop(): void {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
    }

    getCurrent(): TpTemplateBundle | null { return this.current; }

    getById(templateId: bigint): TpTemplateBundle | undefined {
        return this.templateCache.get(templateId);
    }

    private async poll(): Promise<void> {
        let tpl: BlockTemplate;
        try {
            tpl = await getBlockTemplate();
        } catch (e) {
            this.log.warn({ err: (e as Error).message }, "tp getblocktemplate failed");
            return;
        }
        const sig = `${tpl.previousblockhash}|${tpl.transactions.length}|${tpl.curtime}`;
        if (sig === this.lastSig && this.current) return;
        this.lastSig = sig;

        const bundle = buildBundle(tpl);
        this.current = bundle;
        this.templateCache.set(bundle.templateId, bundle);
        if (this.templateCache.size > 256) {
            const oldest = this.templateCache.keys().next().value;
            if (oldest !== undefined) this.templateCache.delete(oldest);
        }
        this.emit("template", bundle);
        this.log.info({
            templateId: bundle.templateId.toString(),
            height: bundle.height,
            txns: bundle.transactionList.length,
        }, "tp new template");
    }
}

function buildBundle(tpl: BlockTemplate): TpTemplateBundle {
    templateCounter = (templateCounter + 1n) & 0xffffffffffffffffn;
    const tid = templateCounter;

    const spk = addressToScriptPubKey(config.rpc.payoutAddress);
    if (!spk) throw new Error(`B3POOL_PAYOUT_ADDRESS=${config.rpc.payoutAddress} invalid`);

    // Build coinbase prefix (everything up to the extranonce slot) and
    // outputs blob (vout list as a single byte buffer). The extranonce
    // slot is 8 bytes and is implied by SV2's coinbase_max_extra_size
    // negotiated separately via CoinbaseOutputDataSize.
    const heightPush = scriptNumPush(tpl.height);
    const tag = new TextEncoder().encode("/B3Chain Pool SV2/");
    const tagPush = concatBytes(new Uint8Array([tag.length]), tag);
    // Coinbase scriptSig layout: heightPush || extranonce(8) || tagPush
    // SV2 NewTemplate.coinbase_prefix = serialized tx bytes up to (but not
    // including) the extranonce slot. SV2 expects the receiving JD client
    // to splice extranonce_prefix || extranonce into the slot.
    //
    // Tx layout (no segwit marker on coinbase):
    //   version(4) || in_count(varint=1) || prevout(36) || scriptSigLen(varint)
    //     || scriptSig(...) || sequence(4)
    //   || out_count(varint) || out[0..n] || locktime(4)
    const prevout = new Uint8Array(36); prevout.fill(0xff, 32);
    const scriptSigLen = heightPush.length + 8 + tagPush.length;
    const coinbasePrefix = concatBytes(
        uint32LE(1),
        new Uint8Array([0x01]),
        prevout,
        varInt(scriptSigLen),
        heightPush,
    );

    // Coinbase outputs blob (the value/scriptPubKey payment + optional
    // witness commitment). SV2 spec requires JD clients to know what
    // outputs the pool will append.
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
    const coinbaseTxOutputs = concatBytes(...vouts);

    // Merkle path (excluding coinbase).
    const txids: string[] = [];
    const transactionList: Uint8Array[] = [];
    for (const tx of tpl.transactions) {
        txids.push(tx.txid ?? tx.hash);
        transactionList.push(hexToBytes(tx.data));
    }
    const merklePath = merklePathFromTxids(txids);

    const newTemplate: NewTemplate = {
        templateId: tid,
        futureTemplate: false,
        version: tpl.version,
        coinbaseTxVersion: 1,
        coinbasePrefix,
        coinbaseTxInputSequence: 0xffffffff,
        coinbaseTxValueRemaining: value,
        coinbaseTxOutputsCount: vouts.length,
        coinbaseTxOutputs,
        coinbaseTxLocktime: 0,
        merklePath,
    };

    const setNewPrevHash: SetNewPrevHashTP = {
        templateId: tid,
        prevHash: reverseBytes(hexToBytes(tpl.previousblockhash)),
        headerTimestamp: tpl.curtime,
        nbits: parseInt(tpl.bits, 16),
        target: reverseBytes(hexToBytes(tpl.target)),
    };

    return {
        templateId: tid,
        height: tpl.height,
        bits: parseInt(tpl.bits, 16),
        coinbaseValue: value,
        newTemplate,
        newTemplateBytes: encodeNewTemplate(newTemplate),
        setNewPrevHash,
        setNewPrevHashBytes: encodeSetNewPrevHashTP(setNewPrevHash),
        transactionList,
        sig: bytesToHex(sha256(new TextEncoder().encode(`${tpl.previousblockhash}|${tpl.curtime}`))),
    };
}

function merklePathFromTxids(txidsHexBE: string[]): Uint8Array[] {
    if (txidsHexBE.length === 0) return [];
    const branches: Uint8Array[] = [];
    let level: (Uint8Array | null)[] = [null, ...txidsHexBE.map(h => reverseBytes(hexToBytes(h)))];
    while (level.length > 1) {
        const sibling = level[1];
        if (sibling) branches.push(sibling);
        const next: (Uint8Array | null)[] = [null];
        for (let i = 2; i < level.length; i += 2) {
            const left = level[i];
            const right = i + 1 < level.length ? level[i + 1] : level[i];
            if (!left || !right) { next.push(null); continue; }
            const buf = new Uint8Array(64);
            buf.set(left, 0); buf.set(right, 32);
            next.push(sha256(sha256(buf)));
        }
        level = next;
    }
    return branches;
}

function scriptNumPush(n: number): Uint8Array {
    if (n === 0) return new Uint8Array([0x00]);
    let abs = Math.abs(n);
    const bytes: number[] = [];
    while (abs > 0) { bytes.push(abs & 0xff); abs >>>= 8; }
    const lastIdx = bytes.length - 1;
    const last = bytes[lastIdx]!;
    if (last & 0x80) bytes.push(0x00);
    const out = new Uint8Array(1 + bytes.length);
    out[0] = bytes.length;
    out.set(bytes, 1);
    return out;
}
