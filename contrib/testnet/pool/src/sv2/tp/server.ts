// SV2 Template Distribution server.
//
// Listens on a TCP port (loopback by default), speaks the SV2 Template
// Distribution Protocol *without* Noise: TP is a private interface
// between the pool and a co-located template provider, the SV2 spec
// permits unencrypted TP, and we keep the bind on 127.0.0.1.
//
// Per-connection lifecycle:
//   - Wait for CoinbaseOutputDataSize (one-shot)
//   - Send the current SetNewPrevHashTP + NewTemplate
//   - Push subsequent NewTemplate / SetNewPrevHashTP whenever the poller
//     emits one
//   - Respond to RequestTransactionData with the cached tx list
//   - Forward SubmitSolutionTP to b3chaind via submitblock

import { EventEmitter } from "events";
import * as net from "net";
import { sha256 } from "@noble/hashes/sha2";
import { Logger } from "../../lib/logger";
import { TpPoller, TpTemplateBundle } from "./poller";
import { splitFrames } from "../lib/codec";
import {
    MSG_COINBASE_OUTPUT_DATA_SIZE,
    MSG_REQUEST_TX_DATA, MSG_SUBMIT_SOLUTION_TP,
    decodeCoinbaseOutputDataSize, decodeRequestTransactionData,
    decodeSubmitSolutionTP,
    encodeRequestTransactionDataSuccess,
} from "../lib/messages/tp";
import { submitBlock } from "../../lib/rpc";
import {
    serializeHeader, hexToBytes, bytesToHex, varInt, concatBytes,
} from "../../lib/header";
import { reverseBytes } from "../../lib/header";

interface TpConn {
    id: number;
    socket: net.Socket;
    state: "AWAIT_CODS" | "READY" | "DEAD";
    coinbaseOutputMaxAdditionalSize: number;
    buf: Uint8Array;
}

let nextConnId = 1;

export interface Sv2TpServerOptions {
    bind: string;
    port: number;
    poller: TpPoller;
    log: Logger;
}

export class Sv2TpServer extends EventEmitter {
    private server: net.Server | null = null;
    private conns = new Set<TpConn>();

    constructor(private opts: Sv2TpServerOptions) { super(); }

    async listen(): Promise<void> {
        await new Promise<void>((res, rej) => {
            const s = net.createServer((sock) => this.accept(sock));
            s.on("error", rej);
            s.listen(this.opts.port, this.opts.bind, () => {
                s.removeListener("error", rej);
                this.server = s;
                this.opts.log.info({ bind: this.opts.bind, port: this.opts.port }, "sv2 tp server listening");
                res();
            });
        });
        this.opts.poller.on("template", (b) => this.broadcast(b));
    }

    async close(): Promise<void> {
        for (const c of this.conns) c.socket.destroy();
        if (this.server) await new Promise<void>((res) => this.server!.close(() => res()));
    }

    private accept(socket: net.Socket): void {
        const c: TpConn = {
            id: nextConnId++,
            socket,
            state: "AWAIT_CODS",
            coinbaseOutputMaxAdditionalSize: 0,
            buf: new Uint8Array(0),
        };
        this.conns.add(c);
        socket.on("data", (chunk) => this.onData(c, chunk));
        socket.on("close", () => { c.state = "DEAD"; this.conns.delete(c); });
        socket.on("error", (e) => this.opts.log.warn({ err: e.message, id: c.id }, "tp conn error"));
        this.opts.log.info({ id: c.id, peer: socket.remoteAddress }, "tp conn accepted");
    }

    private onData(c: TpConn, chunk: Buffer): void {
        if (c.state === "DEAD") return;
        const cb = chunk;
        const merged = new Uint8Array(c.buf.length + cb.length);
        merged.set(c.buf, 0);
        merged.set(new Uint8Array(cb.buffer, cb.byteOffset, cb.length), c.buf.length);
        const { frames, consumed } = splitFrames(merged);
        c.buf = merged.subarray(consumed);
        for (const f of frames) this.dispatch(c, f.header.msgType, f.payload);
    }

    private dispatch(c: TpConn, msgType: number, payload: Uint8Array): void {
        switch (msgType) {
            case MSG_COINBASE_OUTPUT_DATA_SIZE: {
                const m = decodeCoinbaseOutputDataSize(payload);
                c.coinbaseOutputMaxAdditionalSize = m.coinbaseOutputMaxAdditionalSize;
                c.state = "READY";
                this.opts.log.info({ id: c.id, max: m.coinbaseOutputMaxAdditionalSize }, "tp client ready");
                const cur = this.opts.poller.getCurrent();
                if (cur) this.sendCurrent(c, cur);
                break;
            }
            case MSG_REQUEST_TX_DATA: {
                const m = decodeRequestTransactionData(payload);
                const b = this.opts.poller.getById(m.templateId);
                if (!b) {
                    this.opts.log.warn({ id: c.id, templateId: m.templateId.toString() }, "request-tx for unknown template");
                    return;
                }
                const wire = encodeRequestTransactionDataSuccess({
                    templateId: m.templateId,
                    excessData: new Uint8Array(0),
                    transactionList: b.transactionList,
                });
                c.socket.write(Buffer.from(wire));
                break;
            }
            case MSG_SUBMIT_SOLUTION_TP: {
                const m = decodeSubmitSolutionTP(payload);
                void this.handleSolution(c, m);
                break;
            }
            default:
                this.opts.log.debug({ id: c.id, msgType }, "tp unhandled");
        }
    }

    private async handleSolution(c: TpConn, sol: ReturnType<typeof decodeSubmitSolutionTP>): Promise<void> {
        const b = this.opts.poller.getById(sol.templateId);
        if (!b) {
            this.opts.log.warn({ id: c.id, templateId: sol.templateId.toString() }, "tp solution for unknown template");
            return;
        }
        // Reconstruct the block: header(80) || varInt(txCount) || coinbase || txns...
        const merkleRootLE = reconstructMerkleRoot(sol.coinbaseTx, b.newTemplate.merklePath);
        const header = serializeHeader({
            version: sol.version,
            prevHashHexBE: bytesToHex(reverseBytes(b.setNewPrevHash.prevHash)),
            merkleRootHexBE: bytesToHex(reverseBytes(merkleRootLE)),
            ntime: sol.headerTimestamp,
            bits: b.bits,
            nonce: sol.headerNonce,
        });
        const txCount = 1 + b.transactionList.length;
        const block = concatBytes(header, varInt(txCount), sol.coinbaseTx, ...b.transactionList);
        try {
            await submitBlock(bytesToHex(block));
            this.opts.log.info({ id: c.id, height: b.height }, "tp solution submitted");
        } catch (e) {
            this.opts.log.error({ id: c.id, err: (e as Error).message }, "tp submitBlock failed");
        }
    }

    private sendCurrent(c: TpConn, b: TpTemplateBundle): void {
        c.socket.write(Buffer.from(b.setNewPrevHashBytes));
        c.socket.write(Buffer.from(b.newTemplateBytes));
    }

    private broadcast(b: TpTemplateBundle): void {
        for (const c of this.conns) {
            if (c.state !== "READY") continue;
            this.sendCurrent(c, b);
        }
    }
}

function reconstructMerkleRoot(coinbaseTx: Uint8Array, merklePath: Uint8Array[]): Uint8Array {
    let cur = sha256(sha256(coinbaseTx));
    for (const sib of merklePath) {
        const buf = new Uint8Array(64);
        buf.set(cur, 0); buf.set(sib, 32);
        cur = sha256(sha256(buf));
    }
    return cur;
}

// re-export for callers
export { hexToBytes };
