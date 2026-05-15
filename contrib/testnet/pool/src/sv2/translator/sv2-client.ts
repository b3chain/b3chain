// SV2 client used by the translator service to talk *upstream* to our own
// SV2 mining pool. Exposes a tiny event-driven API:
//
//   const c = new Sv2UpstreamClient(...);
//   await c.connect();                              // Noise NX initiator -> setup -> open extended channel
//   c.on("job",        (j) => ...);                 // NewExtendedMiningJob
//   c.on("prevhash",   (p) => ...);                 // SetNewPrevHash
//   c.on("target",     (t) => ...);                 // SetTarget
//   c.on("success",    (s) => ...);                 // SubmitShares.Success
//   c.on("error",      (e) => ...);                 // SubmitShares.Error
//   c.submitExtendedShare({ ... });                 // V1 -> SV2 share

import { EventEmitter } from "events";
import * as net from "net";
import { NoiseNX, NoiseTransport } from "../lib/noise";
import { decodeCertificate, verifyCertificate } from "../lib/cert";
import { splitFrames, decodeHeader, SV2_HEADER_LEN } from "../lib/codec";
import {
    encodeSetupConnection, decodeSetupConnectionSuccess,
    decodeSetupConnectionError, SubProtocol,
    MSG_SETUP_CONNECTION_SUCCESS, MSG_SETUP_CONNECTION_ERROR,
} from "../lib/messages/common";
import {
    encodeOpenExtendedMiningChannel, encodeSubmitSharesExtended,
    decodeOpenExtendedMiningChannelSuccess,
    decodeNewExtendedMiningJob, decodeSetNewPrevHash, decodeSetTarget,
    decodeSubmitSharesSuccess,
    MSG_NEW_EXT_MINING_JOB, MSG_SET_NEW_PREV_HASH, MSG_SET_TARGET,
    MSG_OPEN_EXT_CHANNEL_SUCCESS, MSG_OPEN_EXT_CHANNEL_ERROR,
    MSG_SUBMIT_SHARES_SUCCESS, MSG_SUBMIT_SHARES_ERROR,
    NewExtendedMiningJob, SetNewPrevHash, SetTarget,
} from "../lib/messages/mining";

export interface Sv2UpstreamOptions {
    host: string;
    port: number;
    /** Trusted authority pubkey (32 bytes) used to verify the cert in m2. */
    authorityPub: Uint8Array;
    /** User identity to use when opening the channel (forwarded from V1 auth). */
    userIdentity: string;
    nominalHashRate?: number;
    minExtranonceSize?: number;
}

interface PendingSubmit {
    sequenceNumber: number;
    resolve: (r: { ok: boolean; reason?: string }) => void;
}

export class Sv2UpstreamClient extends EventEmitter {
    private socket: net.Socket | null = null;
    private nx: NoiseNX | null = null;
    private hsBuf = new Uint8Array(0);
    private state: "INIT" | "HANDSHAKE_M2" | "SETUP_PENDING" | "CHANNEL_PENDING" | "READY" | "DEAD" = "INIT";
    private transport: NoiseTransport | null = null;
    private ct = new Uint8Array(0);
    private plain = new Uint8Array(0);
    private nextSeq = 1;
    private channelId = 0;
    public extranoncePrefix: Uint8Array = new Uint8Array(0);
    public extranonceSize = 4;
    private connectResolve: (() => void) | null = null;
    private connectReject: ((e: Error) => void) | null = null;
    private pendingSubmits = new Map<number, PendingSubmit>();

    constructor(public readonly opts: Sv2UpstreamOptions) { super(); }

    async connect(): Promise<void> {
        return new Promise<void>((res, rej) => {
            this.connectResolve = res;
            this.connectReject = rej;
            const sock = net.createConnection({ host: this.opts.host, port: this.opts.port }, () => {
                this.startHandshake();
            });
            sock.on("data", (chunk) => this.onData(chunk));
            sock.on("error", (e) => { this.fail(e); });
            sock.on("close", () => {
                this.state = "DEAD";
                this.emit("close");
            });
            this.socket = sock;
        });
    }

    close(): void {
        if (this.socket) this.socket.destroy();
    }

    private startHandshake(): void {
        this.nx = new NoiseNX("initiator");
        const m1 = this.nx.writeMessage1();
        const out = new Uint8Array(2 + m1.length);
        new DataView(out.buffer).setUint16(0, m1.length, true);
        out.set(m1, 2);
        this.socket!.write(Buffer.from(out));
        this.state = "HANDSHAKE_M2";
    }

    private onData(chunk: Buffer): void {
        if (this.state === "DEAD") return;
        if (this.state === "HANDSHAKE_M2") {
            this.hsBuf = appendBytes(this.hsBuf, chunk);
            if (this.hsBuf.length < 2) return;
            const len = readU16LE(this.hsBuf, 0);
            if (this.hsBuf.length < 2 + len) return;
            const m2 = this.hsBuf.subarray(2, 2 + len);
            const trailing = this.hsBuf.subarray(2 + len);
            this.hsBuf = new Uint8Array(0);
            try {
                const fin = this.nx!.readMessage2(m2);
                this.transport = new NoiseTransport(fin.sendCipher, fin.recvCipher);
                if (fin.responderPayload && fin.responderPayload.length) {
                    const cert = decodeCertificate(fin.responderPayload);
                    const v = verifyCertificate(cert, this.opts.authorityPub);
                    if (!v.ok) throw new Error(`pool cert rejected: ${v.reason}`);
                    if (Buffer.compare(cert.publicKey, fin.remoteStaticPub!) !== 0) {
                        throw new Error("pool cert publicKey != noise static");
                    }
                }
            } catch (e) {
                this.fail(e as Error);
                return;
            }
            this.sendSetupConnection();
            this.state = "SETUP_PENDING";
            if (trailing.length) this.processCipher(trailing);
            return;
        }
        this.processCipher(chunk);
    }

    private processCipher(chunk: Buffer | Uint8Array): void {
        if (!this.transport) return;
        this.ct = appendBytes(this.ct, chunk);
        const { frames, consumed } = this.transport.decryptFrames(this.ct);
        this.ct = this.ct.subarray(consumed);
        for (const fr of frames) this.handlePlainBytes(fr);
    }

    private handlePlainBytes(plain: Uint8Array): void {
        this.plain = appendBytes(this.plain, plain);
        const { frames, consumed } = splitFrames(this.plain);
        this.plain = this.plain.subarray(consumed);
        for (const f of frames) this.dispatch(f.header, f.payload);
    }

    private dispatch(header: ReturnType<typeof decodeHeader>, payload: Uint8Array): void {
        switch (header.msgType) {
            case MSG_SETUP_CONNECTION_SUCCESS: {
                decodeSetupConnectionSuccess(payload);
                this.sendOpenExtendedChannel();
                this.state = "CHANNEL_PENDING";
                break;
            }
            case MSG_SETUP_CONNECTION_ERROR: {
                const e = decodeSetupConnectionError(payload);
                this.fail(new Error(`upstream SetupConnection.Error: ${e.errorCode}`));
                break;
            }
            case MSG_OPEN_EXT_CHANNEL_SUCCESS: {
                const m = decodeOpenExtendedMiningChannelSuccess(payload);
                this.channelId = m.channelId;
                this.extranoncePrefix = m.extranoncePrefix;
                this.extranonceSize = m.extranonceSize;
                this.state = "READY";
                if (this.connectResolve) { this.connectResolve(); this.connectResolve = null; this.connectReject = null; }
                this.emit("channel-open", m);
                break;
            }
            case MSG_OPEN_EXT_CHANNEL_ERROR: {
                this.fail(new Error("upstream OpenExtendedMiningChannel.Error"));
                break;
            }
            case MSG_NEW_EXT_MINING_JOB: {
                const j: NewExtendedMiningJob = decodeNewExtendedMiningJob(payload);
                this.emit("job", j);
                break;
            }
            case MSG_SET_NEW_PREV_HASH: {
                const p: SetNewPrevHash = decodeSetNewPrevHash(payload);
                this.emit("prevhash", p);
                break;
            }
            case MSG_SET_TARGET: {
                const t: SetTarget = decodeSetTarget(payload);
                this.emit("target", t);
                break;
            }
            case MSG_SUBMIT_SHARES_SUCCESS: {
                const s = decodeSubmitSharesSuccess(payload);
                const p = this.pendingSubmits.get(s.lastSequenceNumber);
                if (p) { p.resolve({ ok: true }); this.pendingSubmits.delete(s.lastSequenceNumber); }
                break;
            }
            case MSG_SUBMIT_SHARES_ERROR: {
                // payload: channel_id u32 || sequence_number u32 || error_code STR
                if (payload.length >= 8) {
                    const seq = new DataView(payload.buffer, payload.byteOffset + 4, 4).getUint32(0, true);
                    const p = this.pendingSubmits.get(seq);
                    if (p) { p.resolve({ ok: false, reason: "rejected" }); this.pendingSubmits.delete(seq); }
                }
                break;
            }
        }
    }

    private sendSetupConnection(): void {
        const wire = encodeSetupConnection({
            protocol: SubProtocol.Mining,
            minVersion: 2, maxVersion: 2, flags: 0,
            endpointHost: this.opts.host, endpointPort: this.opts.port,
            vendor: "b3chain-pool-translator",
            hardwareVersion: "1",
            firmware: "node",
            deviceId: this.opts.userIdentity,
        });
        this.write(wire);
    }

    private sendOpenExtendedChannel(): void {
        const max = new Uint8Array(32).fill(0xff);
        const wire = encodeOpenExtendedMiningChannel({
            requestId: 1,
            userIdentity: this.opts.userIdentity,
            nominalHashRate: this.opts.nominalHashRate ?? 1e6,
            maxTarget: max,
            minExtranonceSize: this.opts.minExtranonceSize ?? 4,
        });
        this.write(wire);
    }

    submitExtendedShare(args: {
        nonce: number; ntime: number; version: number; extranonce: Uint8Array; jobId: number;
    }): Promise<{ ok: boolean; reason?: string }> {
        return new Promise<{ ok: boolean; reason?: string }>((resolve) => {
            const seq = this.nextSeq++;
            this.pendingSubmits.set(seq, { sequenceNumber: seq, resolve });
            const wire = encodeSubmitSharesExtended({
                channelId: this.channelId,
                sequenceNumber: seq,
                jobId: args.jobId,
                nonce: args.nonce,
                ntime: args.ntime,
                version: args.version,
                extranonce: args.extranonce,
            });
            this.write(wire);
            // Translator-side fail-safe: if upstream forgets to ACK, free the slot after 30s.
            setTimeout(() => {
                if (this.pendingSubmits.has(seq)) {
                    this.pendingSubmits.delete(seq);
                    resolve({ ok: false, reason: "upstream-timeout" });
                }
            }, 30_000).unref?.();
        });
    }

    private write(plainFrame: Uint8Array): void {
        if (!this.transport || !this.socket) return;
        const ct = this.transport.encryptFrame(plainFrame);
        this.socket.write(Buffer.from(ct));
    }

    private fail(e: Error): void {
        this.state = "DEAD";
        if (this.connectReject) { this.connectReject(e); this.connectResolve = null; this.connectReject = null; }
        if (this.socket) this.socket.destroy();
        this.emit("error", e);
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
