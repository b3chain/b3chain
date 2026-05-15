// Job-Declaration server.
//
// Runs in-process with the SV2 mining pool. Accepts JD client connections
// over Noise NX on a separate TCP port, handles AllocateMiningJobToken /
// DeclareMiningJob, validates the declared coinbase pays the pool, then
// asks the mining server to push a SetCustomMiningJob over the matching
// open Mining channel.
//
// We keep this isolated from the mining server: it exposes a single
// `deliverCustomJob()` callback so this file has no compile-time dep on
// Sv2MiningServer internals.

import { EventEmitter } from "events";
import * as net from "net";
import { Logger } from "../../lib/logger";
import { config } from "../../config";
import { NoiseNX, NoiseTransport } from "../lib/noise";
import { encodeCertificate, type Sv2Certificate } from "../lib/cert";
import { splitFrames, SV2_HEADER_LEN, decodeHeader } from "../lib/codec";
import {
    decodeSetupConnection, encodeSetupConnectionSuccess, encodeSetupConnectionError,
    SubProtocol, MSG_SETUP_CONNECTION,
} from "../lib/messages/common";
import {
    MSG_ALLOCATE_JOB_TOKEN, MSG_DECLARE_MINING_JOB,
    decodeAllocateMiningJobToken, decodeDeclareMiningJob,
    encodeAllocateMiningJobTokenSuccess,
    encodeDeclareMiningJobSuccess, encodeDeclareMiningJobError,
} from "../lib/messages/jd";
import { JdTokenStore } from "./tokens";
import { validateDeclaredCoinbase } from "./custom_job";
import { addressToScriptPubKey } from "../../lib/address";
import { concatBytes, varInt } from "../../lib/header";

export interface CustomJobDelivery {
    requestId: number;
    miningJobToken: Uint8Array;
    version: number;
    coinbasePrefix: Uint8Array;
    coinbaseSuffix: Uint8Array;
    /** Pool-tracked sat value that this miner committed to send to the pool. */
    poolValueSat: bigint;
}

export interface Sv2JdServerOptions {
    bind: string;
    port: number;
    staticKey: { priv: Uint8Array; pub: Uint8Array };
    cert: Sv2Certificate;
    log: Logger;
    /**
     * The mining server registers a delivery callback. The JD server invokes
     * it when DeclareMiningJob succeeds. The mining server is then
     * responsible for pushing SetCustomMiningJob over an appropriate
     * Mining channel and acknowledging back via the returned promise.
     */
    deliverCustomJob: (job: CustomJobDelivery, userIdentity: string) => Promise<{ ok: boolean; reason?: string }>;
}

interface JdConn {
    id: number;
    socket: net.Socket;
    state: "HANDSHAKE_M1" | "SETUP_PENDING" | "READY" | "DEAD";
    nx?: NoiseNX;
    hsBuf: Uint8Array;
    transport?: NoiseTransport;
    plain: Uint8Array;
    ct: Uint8Array;
    userIdentity: string;
}

let nextConnId = 1;

export class Sv2JdServer extends EventEmitter {
    private server: net.Server | null = null;
    private conns = new Set<JdConn>();
    private tokens: JdTokenStore;

    constructor(private opts: Sv2JdServerOptions) {
        super();
        this.tokens = new JdTokenStore(opts.log);
    }

    async listen(): Promise<void> {
        await new Promise<void>((res, rej) => {
            const s = net.createServer((sock) => this.accept(sock));
            s.on("error", rej);
            s.listen(this.opts.port, this.opts.bind, () => {
                s.removeListener("error", rej);
                this.server = s;
                this.opts.log.info({ bind: this.opts.bind, port: this.opts.port }, "sv2 jd server listening");
                res();
            });
        });
    }

    async close(): Promise<void> {
        for (const c of this.conns) c.socket.destroy();
        if (this.server) await new Promise<void>((res) => this.server!.close(() => res()));
    }

    private accept(socket: net.Socket): void {
        const c: JdConn = {
            id: nextConnId++,
            socket,
            state: "HANDSHAKE_M1",
            nx: new NoiseNX("responder", this.opts.staticKey),
            hsBuf: new Uint8Array(0),
            plain: new Uint8Array(0),
            ct: new Uint8Array(0),
            userIdentity: "",
        };
        this.conns.add(c);
        socket.on("data", (chunk) => this.onData(c, chunk));
        socket.on("error", (e) => this.opts.log.warn({ err: e.message, id: c.id }, "jd conn error"));
        socket.on("close", () => { c.state = "DEAD"; this.conns.delete(c); });
        this.opts.log.info({ id: c.id, peer: socket.remoteAddress }, "jd conn accepted");
    }

    private onData(c: JdConn, chunk: Buffer): void {
        if (c.state === "DEAD") return;
        try {
            if (c.state === "HANDSHAKE_M1") return this.handshake(c, chunk);
            c.ct = appendBytes(c.ct, chunk);
            if (!c.transport) return;
            const { frames, consumed } = c.transport.decryptFrames(c.ct);
            c.ct = c.ct.subarray(consumed);
            for (const fr of frames) this.handlePlainBytes(c, fr);
        } catch (e) {
            this.opts.log.warn({ err: (e as Error).message, id: c.id }, "jd onData failed");
            c.socket.destroy();
        }
    }

    private handshake(c: JdConn, chunk: Buffer): void {
        if (!c.nx) throw new Error("jd nx missing");
        c.hsBuf = appendBytes(c.hsBuf, chunk);
        if (c.hsBuf.length < 2) return;
        const len = readU16LE(c.hsBuf, 0);
        if (c.hsBuf.length < 2 + len) return;
        const m1 = c.hsBuf.subarray(2, 2 + len);
        c.hsBuf = c.hsBuf.subarray(2 + len);
        c.nx.readMessage1(m1);
        const cert = encodeCertificate(this.opts.cert);
        const m2 = c.nx.writeMessage2(cert);
        const out = new Uint8Array(2 + m2.length);
        new DataView(out.buffer).setUint16(0, m2.length, true);
        out.set(m2, 2);
        c.socket.write(Buffer.from(out));
        const fin = c.nx.finishResponder();
        c.transport = new NoiseTransport(fin.sendCipher, fin.recvCipher);
        c.state = "SETUP_PENDING";
        if (c.hsBuf.length) {
            c.ct = appendBytes(c.ct, c.hsBuf);
            c.hsBuf = new Uint8Array(0);
            const { frames, consumed } = c.transport.decryptFrames(c.ct);
            c.ct = c.ct.subarray(consumed);
            for (const fr of frames) this.handlePlainBytes(c, fr);
        }
    }

    private handlePlainBytes(c: JdConn, plain: Uint8Array): void {
        c.plain = appendBytes(c.plain, plain);
        const { frames, consumed } = splitFrames(c.plain);
        c.plain = c.plain.subarray(consumed);
        for (const f of frames) void this.dispatch(c, f.header, f.payload);
    }

    private async dispatch(c: JdConn, header: ReturnType<typeof decodeHeader>, payload: Uint8Array): Promise<void> {
        if (c.state === "SETUP_PENDING") {
            if (header.msgType === MSG_SETUP_CONNECTION) {
                this.handleSetup(c, payload);
                return;
            }
            this.opts.log.warn({ id: c.id, msgType: header.msgType }, "jd: first frame not SetupConnection");
            c.socket.destroy();
            return;
        }
        if (c.state !== "READY") return;
        switch (header.msgType) {
            case MSG_ALLOCATE_JOB_TOKEN: await this.handleAllocate(c, payload); break;
            case MSG_DECLARE_MINING_JOB: await this.handleDeclare(c, payload); break;
            default: this.opts.log.debug({ id: c.id, msgType: header.msgType }, "jd unhandled");
        }
    }

    private handleSetup(c: JdConn, payload: Uint8Array): void {
        const m = decodeSetupConnection(payload);
        if (m.protocol !== SubProtocol.JobDeclaration) {
            this.send(c, encodeSetupConnectionError({ flags: 0, errorCode: "unsupported-protocol" }));
            c.socket.destroy();
            return;
        }
        c.userIdentity = m.deviceId || "jd-anon";
        this.send(c, encodeSetupConnectionSuccess({ usedVersion: 2, flags: 0 }));
        c.state = "READY";
        this.opts.log.info({ id: c.id, vendor: m.vendor, deviceId: m.deviceId }, "jd setup ok");
    }

    private async handleAllocate(c: JdConn, payload: Uint8Array): Promise<void> {
        const m = decodeAllocateMiningJobToken(payload);
        const tok = await this.tokens.issue({
            userIdentifier: m.userIdentifier || c.userIdentity,
            sessionId: null,
            coinbaseOutputMaxAdditionalSize: 100, // accommodate witness commitment
        });
        const expectedSpk = addressToScriptPubKey(config.rpc.payoutAddress);
        if (!expectedSpk) {
            this.opts.log.error("pool payout address invalid; cannot answer Allocate");
            return;
        }
        // Hand the JD client a *single* expected output the pool will demand
        // back inside the declared coinbase: 0 sats placeholder + the pool's
        // scriptPubKey. (The actual sat amount is the entire coinbasevalue,
        // which the JD client will see in NewTemplate and split as it wishes
        // — we only enforce the spk equality + min value at Declare time.)
        const value = new Uint8Array(8);
        const coinbaseOutput = concatBytes(value, varInt(expectedSpk.length), expectedSpk);
        this.send(c, encodeAllocateMiningJobTokenSuccess({
            requestId: m.requestId,
            miningJobToken: tok.bytes,
            coinbaseOutputMaxAdditionalSize: tok.coinbaseOutputMaxAdditionalSize,
            asyncMiningAllowed: true,
            coinbaseOutput,
        }));
        this.opts.log.info({
            id: c.id, user: tok.userIdentifier, requestId: m.requestId,
        }, "jd allocated mining_job_token");
    }

    private async handleDeclare(c: JdConn, payload: Uint8Array): Promise<void> {
        const m = decodeDeclareMiningJob(payload);
        const tok = await this.tokens.consume(m.miningJobToken, {
            version: m.version,
            coinbasePrefix: m.coinbasePrefix,
            coinbaseSuffix: m.coinbaseSuffix,
            txCount: m.txShortHashList.length,
        });
        if (!tok) {
            this.send(c, encodeDeclareMiningJobError({
                requestId: m.requestId, errorCode: "invalid-mining-job-token", errorDetails: new Uint8Array(0),
            }));
            return;
        }

        // Coinbase-pays-pool enforcement. We require at least 1 sat to the
        // pool's payout SPK; the operator's downstream PPLNS engine
        // determines the exact split via B3POOL_FEE_PERCENT. This is the
        // baseline check that prevents miners from declaring a job that
        // cuts the pool out entirely.
        const v = validateDeclaredCoinbase(m.coinbaseSuffix, 1n);
        if (!v.ok) {
            await this.tokens.reject(m.miningJobToken, v.reason ?? "rejected");
            this.send(c, encodeDeclareMiningJobError({
                requestId: m.requestId, errorCode: v.reason ?? "rejected",
                errorDetails: new Uint8Array(0),
            }));
            this.opts.log.warn({ id: c.id, reason: v.reason }, "jd declare rejected");
            return;
        }

        const delivery: CustomJobDelivery = {
            requestId: m.requestId,
            miningJobToken: m.miningJobToken,
            version: m.version,
            coinbasePrefix: m.coinbasePrefix,
            coinbaseSuffix: m.coinbaseSuffix,
            poolValueSat: v.poolValueSat ?? 0n,
        };
        const r = await this.opts.deliverCustomJob(delivery, tok.userIdentifier);
        if (!r.ok) {
            await this.tokens.reject(m.miningJobToken, r.reason ?? "delivery-failed");
            this.send(c, encodeDeclareMiningJobError({
                requestId: m.requestId, errorCode: r.reason ?? "delivery-failed",
                errorDetails: new Uint8Array(0),
            }));
            return;
        }
        // Re-use the same token bytes as the new_mining_job_token so the
        // miner can correlate (per spec the pool may issue a fresh one).
        this.send(c, encodeDeclareMiningJobSuccess({
            requestId: m.requestId, newMiningJobToken: m.miningJobToken,
        }));
        this.opts.log.info({
            id: c.id, user: tok.userIdentifier, requestId: m.requestId,
            poolValueSat: v.poolValueSat?.toString(),
        }, "jd declared custom job");
    }

    private send(c: JdConn, plainFrame: Uint8Array): void {
        if (!c.transport) return;
        if (plainFrame.length < SV2_HEADER_LEN) return;
        const ct = c.transport.encryptFrame(plainFrame);
        c.socket.write(Buffer.from(ct));
    }
}

function appendBytes(a: Uint8Array, b: Uint8Array | Buffer): Uint8Array<ArrayBuffer> {
    const out = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    if (b instanceof Buffer) {
        for (let i = 0; i < b.length; i++) out[a.length + i] = b[i]!;
    } else {
        out.set(b, a.length);
    }
    return out;
}

function readU16LE(b: Uint8Array, off: number): number {
    return new DataView(b.buffer, b.byteOffset + off, 2).getUint16(0, true);
}
