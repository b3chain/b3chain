// Stratum V2 Mining Protocol pool server.
//
// One TCP listener; per-connection state machine:
//
//   HANDSHAKE_M1   waiting for the initiator's "e" (Noise NX message 1)
//   HANDSHAKE_DONE m2 sent, waiting for first encrypted SV2 frame
//   SETUP_PENDING  Noise transport up, expecting SetupConnection
//   READY          channels can be opened and shares submitted
//
// Every Noise handshake message is wire-prefixed with a u16 LE length so
// we don't have to depend on TCP framing. After the handshake, all SV2
// frames travel as Noise transport messages (NoiseTransport handles its
// own segment framing internally).

import { EventEmitter } from "events";
import * as net from "net";
import { Logger } from "../../lib/logger";
import { JobManager, StratumJob } from "../../stratum/job-manager";
import { networkDifficultyFromBits } from "../../lib/difficulty-math";
import { ShareEvent } from "../../lib/ipc";
import {
    NoiseNX, NoiseTransport,
} from "../lib/noise";
import {
    encodeCertificate, type Sv2Certificate,
} from "../lib/cert";
import {
    decodeHeader, splitFrames, SV2_HEADER_LEN,
} from "../lib/codec";
import {
    decodeSetupConnection, encodeSetupConnectionSuccess, encodeSetupConnectionError,
    SubProtocol,
    MSG_SETUP_CONNECTION,
} from "../lib/messages/common";
import {
    MSG_OPEN_STD_CHANNEL, MSG_OPEN_EXT_CHANNEL,
    MSG_SUBMIT_SHARES_STANDARD, MSG_SUBMIT_SHARES_EXTENDED,
    MSG_CLOSE_CHANNEL, MSG_UPDATE_CHANNEL,
    MSG_OPEN_STD_CHANNEL_ERROR, MSG_OPEN_EXT_CHANNEL_ERROR,
    decodeOpenStandardMiningChannel, decodeOpenExtendedMiningChannel,
    decodeSubmitSharesStandard, decodeSubmitSharesExtended,
    decodeUpdateChannel,
    encodeOpenStandardMiningChannelSuccess,
    encodeOpenExtendedMiningChannelSuccess,
    encodeOpenChannelError,
    encodeSubmitSharesError, encodeSubmitSharesSuccess,
    encodeSetCustomMiningJob,
} from "../lib/messages/mining";
import {
    ChannelTable, maxTargetU256BE, SV2_EXTRANONCE_TOTAL,
} from "./channel";
import {
    buildNewExtendedJob, buildNewStandardJob,
    buildSetNewPrevHash, buildSetTarget, nextSv2JobId,
} from "./jobs";
import { processSubmit } from "./submit";

interface StaticKey { priv: Uint8Array; pub: Uint8Array }

export interface Sv2ServerOptions {
    bind: string;
    port: number;
    staticKey: StaticKey;
    /** Pre-encoded SignedCertificate that travels in Noise message 2 payload. */
    cert: Sv2Certificate;
    defaultDifficulty: number;
    log: Logger;
    jobs: JobManager;
    onShare: (event: ShareEvent) => void;
}

interface PendingHs {
    phase: "M1" | "M2_SENT";
    nx: NoiseNX;
    buf: Uint8Array;
}

interface Conn {
    id: number;
    socket: net.Socket;
    state: "HANDSHAKE_M1" | "HANDSHAKE_DONE" | "SETUP_PENDING" | "READY" | "DEAD";
    hs?: PendingHs;
    transport?: NoiseTransport;
    // post-handshake plaintext frame buffer
    plain: Uint8Array;
    channels: ChannelTable;
    setup?: { protocol: SubProtocol; usedVersion: number; flags: number };
    // ciphertext byte buffer prior to transport.decryptFrames
    ct: Uint8Array;
    seenJob: Set<string>; // V1 job ids we already pushed
}

let nextConnId = 1;

export class Sv2MiningServer extends EventEmitter {
    private server: net.Server | null = null;
    private conns = new Set<Conn>();

    constructor(private opts: Sv2ServerOptions) { super(); }

    async listen(): Promise<void> {
        await new Promise<void>((res, rej) => {
            const s = net.createServer((sock) => this.accept(sock));
            s.on("error", rej);
            s.listen(this.opts.port, this.opts.bind, () => {
                s.removeListener("error", rej);
                this.server = s;
                this.opts.log.info({ bind: this.opts.bind, port: this.opts.port }, "sv2 mining server listening");
                res();
            });
        });
        this.opts.jobs.on("job", (job: StratumJob) => this.broadcastJob(job));
    }

    async close(): Promise<void> {
        for (const c of this.conns) c.socket.destroy();
        if (this.server) await new Promise<void>((res) => this.server!.close(() => res()));
    }

    // ---------------- JD bridge ----------------
    //
    // Pushes a SetCustomMiningJob to the first open Extended channel that
    // matches `userIdentity`. Used by the in-process JD server to honour a
    // miner's DeclareMiningJob. The returned promise resolves once the
    // frame has been written to the wire.
    public async pushCustomJob(userIdentity: string, args: {
        requestId: number;
        miningJobToken: Uint8Array;
        version: number;
        coinbasePrefix: Uint8Array;
        coinbaseSuffix: Uint8Array;
    }): Promise<{ ok: boolean; reason?: string }> {
        for (const conn of this.conns) {
            if (conn.state !== "READY") continue;
            const ch = conn.channels.all().find(
                (c) => c.userIdentity === userIdentity && c.kind === "extended",
            );
            if (!ch) continue;
            const job = this.opts.jobs.getCurrent();
            if (!job) return { ok: false, reason: "no-current-template" };
            const customJobId = nextSv2JobId();
            const customJob: import("../lib/messages/mining").SetCustomMiningJob = {
                channelId: ch.id,
                requestId: args.requestId,
                miningJobToken: args.miningJobToken,
                version: args.version,
                prevHash: hexToReversedBytes(job.prevHashHexBE),
                minNtime: job.ntimeMin,
                nbits: job.bits,
                coinbaseTxVersion: 1,
                coinbasePrefix: args.coinbasePrefix,
                coinbaseTxInputNSequence: 0xffffffff,
                coinbaseTxValueRemaining: 0n,
                coinbaseTxOutputs: args.coinbaseSuffix,
                coinbaseTxLocktime: 0,
                merklePath: [],
            };
            this.send(conn, encodeSetCustomMiningJob(customJob));
            ch.lastJobId = customJobId;
            this.opts.log.info({
                connId: conn.id, channelId: ch.id, user: userIdentity, customJobId,
            }, "sv2 custom mining job pushed");
            return { ok: true };
        }
        return { ok: false, reason: "no-open-extended-channel-for-user" };
    }

    // ---------------- per-connection ----------------

    private accept(socket: net.Socket): void {
        const conn: Conn = {
            id: nextConnId++,
            socket,
            state: "HANDSHAKE_M1",
            hs: { phase: "M1", nx: new NoiseNX("responder", this.opts.staticKey), buf: new Uint8Array(0) },
            plain: new Uint8Array(0),
            ct: new Uint8Array(0),
            channels: new ChannelTable(),
            seenJob: new Set(),
        };
        this.conns.add(conn);
        socket.on("data", (chunk) => this.onData(conn, chunk));
        socket.on("error", (e) => this.opts.log.warn({ err: e.message, id: conn.id }, "sv2 conn error"));
        socket.on("close", () => { conn.state = "DEAD"; this.conns.delete(conn); });
        this.opts.log.info({ id: conn.id, peer: socket.remoteAddress }, "sv2 conn accepted");
    }

    private onData(conn: Conn, chunk: Buffer): void {
        if (conn.state === "DEAD") return;
        try {
            if (conn.state === "HANDSHAKE_M1") {
                this.handleHandshake(conn, chunk);
                return;
            }
            // Once transport is up, append to ct buffer and decrypt frames.
            conn.ct = appendBytes(conn.ct, chunk);
            if (!conn.transport) return;
            const { frames, consumed } = conn.transport.decryptFrames(conn.ct);
            conn.ct = conn.ct.subarray(consumed);
            for (const fr of frames) this.handlePlainBytes(conn, fr);
        } catch (e) {
            this.opts.log.warn({ err: (e as Error).message, id: conn.id }, "sv2 onData failed");
            conn.socket.destroy();
        }
    }

    private handleHandshake(conn: Conn, chunk: Buffer): void {
        if (!conn.hs) throw new Error("hs missing");
        conn.hs.buf = appendBytes(conn.hs.buf, chunk);
        if (conn.hs.phase === "M1") {
            // message 1 = u16 LE length || ephemeral pub (32 bytes)
            if (conn.hs.buf.length < 2) return;
            const len = readU16LE(conn.hs.buf, 0);
            if (conn.hs.buf.length < 2 + len) return;
            const m1 = conn.hs.buf.subarray(2, 2 + len);
            conn.hs.buf = conn.hs.buf.subarray(2 + len);
            conn.hs.nx.readMessage1(m1);
            const certBytes = encodeCertificate(this.opts.cert);
            const m2 = conn.hs.nx.writeMessage2(certBytes);
            // wire: u16 LE length || m2
            const out = new Uint8Array(2 + m2.length);
            new DataView(out.buffer).setUint16(0, m2.length, true);
            out.set(m2, 2);
            conn.socket.write(Buffer.from(out));
            const fin = conn.hs.nx.finishResponder();
            conn.transport = new NoiseTransport(fin.sendCipher, fin.recvCipher);
            conn.state = "SETUP_PENDING";
            conn.hs.phase = "M2_SENT";
            // any leftover bytes from this chunk are ciphertext
            if (conn.hs.buf.length) {
                conn.ct = appendBytes(conn.ct, conn.hs.buf);
                conn.hs.buf = new Uint8Array(0);
                const { frames, consumed } = conn.transport.decryptFrames(conn.ct);
                conn.ct = conn.ct.subarray(consumed);
                for (const fr of frames) this.handlePlainBytes(conn, fr);
            }
        }
    }

    private handlePlainBytes(conn: Conn, plain: Uint8Array): void {
        // A single Noise transport frame typically contains exactly one SV2
        // frame, but we use splitFrames to be tolerant of senders that
        // batch multiple frames into one segment.
        conn.plain = appendBytes(conn.plain, plain);
        const { frames, consumed } = splitFrames(conn.plain);
        conn.plain = conn.plain.subarray(consumed);
        for (const f of frames) this.dispatch(conn, f.header, f.payload);
    }

    private dispatch(conn: Conn, header: ReturnType<typeof decodeHeader>, payload: Uint8Array): void {
        if (conn.state === "SETUP_PENDING") {
            if (header.extensionType === 0 && header.msgType === MSG_SETUP_CONNECTION) {
                this.handleSetup(conn, payload);
                return;
            }
            this.opts.log.warn({ id: conn.id, msgType: header.msgType }, "first frame is not SetupConnection; closing");
            conn.socket.destroy();
            return;
        }
        if (conn.state !== "READY") return;
        switch (header.msgType) {
            case MSG_OPEN_STD_CHANNEL: this.handleOpenStandard(conn, payload); break;
            case MSG_OPEN_EXT_CHANNEL: this.handleOpenExtended(conn, payload); break;
            case MSG_SUBMIT_SHARES_STANDARD: this.handleSubmitStd(conn, payload); break;
            case MSG_SUBMIT_SHARES_EXTENDED: this.handleSubmitExt(conn, payload); break;
            case MSG_UPDATE_CHANNEL: this.handleUpdate(conn, payload); break;
            case MSG_CLOSE_CHANNEL: this.handleClose(conn, payload); break;
            default:
                this.opts.log.debug({ id: conn.id, msgType: header.msgType }, "unhandled sv2 frame");
        }
    }

    private handleSetup(conn: Conn, payload: Uint8Array): void {
        const m = decodeSetupConnection(payload);
        if (m.protocol !== SubProtocol.Mining) {
            const wire = encodeSetupConnectionError({ flags: 0, errorCode: "unsupported-protocol" });
            this.send(conn, wire);
            conn.socket.destroy();
            return;
        }
        const used = Math.min(m.maxVersion, 2);
        if (used < m.minVersion) {
            const wire = encodeSetupConnectionError({ flags: 0, errorCode: "protocol-version-mismatch" });
            this.send(conn, wire);
            conn.socket.destroy();
            return;
        }
        conn.setup = { protocol: m.protocol, usedVersion: used, flags: m.flags };
        this.send(conn, encodeSetupConnectionSuccess({ usedVersion: used, flags: 0 }));
        conn.state = "READY";
        this.opts.log.info({ id: conn.id, vendor: m.vendor, firmware: m.firmware }, "sv2 setup ok");
    }

    private handleOpenStandard(conn: Conn, payload: Uint8Array): void {
        const m = decodeOpenStandardMiningChannel(payload);
        const ch = conn.channels.open({
            kind: "standard", requestId: m.requestId, userIdentity: m.userIdentity,
            nominalHashRate: m.nominalHashRate, defaultDifficulty: this.opts.defaultDifficulty,
        });
        this.send(conn, encodeOpenStandardMiningChannelSuccess({
            requestId: m.requestId, channelId: ch.id,
            target: ch.targetBE, extranoncePrefix: ch.extranoncePrefix,
            groupChannelId: ch.groupChannelId,
        }));
        this.send(conn, buildSetTarget(ch).bytes);
        const job = this.opts.jobs.getCurrent();
        if (job) this.pushJobToChannel(conn, ch.id, job);
    }

    private handleOpenExtended(conn: Conn, payload: Uint8Array): void {
        const m = decodeOpenExtendedMiningChannel(payload);
        const prefixLen = Math.min(Math.max(SV2_EXTRANONCE_TOTAL - m.minExtranonceSize, 1), SV2_EXTRANONCE_TOTAL - 1);
        if (m.minExtranonceSize > SV2_EXTRANONCE_TOTAL - 1) {
            this.send(conn, encodeOpenChannelError(MSG_OPEN_EXT_CHANNEL_ERROR, {
                requestId: m.requestId, errorCode: "min-extranonce-size-too-large",
            }));
            return;
        }
        const ch = conn.channels.open({
            kind: "extended", requestId: m.requestId, userIdentity: m.userIdentity,
            nominalHashRate: m.nominalHashRate, defaultDifficulty: this.opts.defaultDifficulty,
            prefixLen,
        });
        this.send(conn, encodeOpenExtendedMiningChannelSuccess({
            requestId: m.requestId, channelId: ch.id,
            target: ch.targetBE, extranonceSize: ch.extranonceSize,
            extranoncePrefix: ch.extranoncePrefix,
        }));
        this.send(conn, buildSetTarget(ch).bytes);
        const job = this.opts.jobs.getCurrent();
        if (job) this.pushJobToChannel(conn, ch.id, job);
        this.opts.log.info({
            id: conn.id, channelId: ch.id, prefixLen, extranonceSize: ch.extranonceSize,
            user: ch.userIdentity,
        }, "sv2 extended channel opened");
    }

    private handleUpdate(conn: Conn, payload: Uint8Array): void {
        const m = decodeUpdateChannel(payload);
        // Respect miner-supplied nominal_hash_rate by adjusting share difficulty
        // toward the configured retune target. Out of scope for the MVP; just log.
        this.opts.log.debug({ id: conn.id, channelId: m.channelId, hr: m.nominalHashRate }, "update channel");
    }

    private handleClose(conn: Conn, payload: Uint8Array): void {
        // payload starts with channel_id (u32 LE)
        if (payload.length < 4) return;
        const channelId = readU32LE(payload, 0);
        conn.channels.delete(channelId);
        this.opts.log.info({ id: conn.id, channelId }, "sv2 channel closed by miner");
    }

    // ---------------- shares ----------------

    private async handleSubmitStd(conn: Conn, payload: Uint8Array): Promise<void> {
        const m = decodeSubmitSharesStandard(payload);
        const ch = conn.channels.get(m.channelId);
        if (!ch) {
            this.send(conn, encodeSubmitSharesError({
                channelId: m.channelId, sequenceNumber: m.sequenceNumber, errorCode: "no-such-channel",
            }));
            return;
        }
        const job = this.lookupJob(m.jobId);
        if (!job) {
            this.send(conn, encodeSubmitSharesError({
                channelId: m.channelId, sequenceNumber: m.sequenceNumber, errorCode: "stale-job",
            }));
            return;
        }
        const result = await processSubmit({
            channel: ch, job, sequenceNumber: m.sequenceNumber,
            nonce: m.nonce, ntime: m.ntime, version: m.version,
            extranonce: new Uint8Array(0),
            blockHeight: job.height,
            networkDifficulty: networkDifficultyFromBits(job.bits),
        }, this.opts.log);
        this.replySubmit(conn, ch.id, m.sequenceNumber, result);
    }

    private async handleSubmitExt(conn: Conn, payload: Uint8Array): Promise<void> {
        const m = decodeSubmitSharesExtended(payload);
        const ch = conn.channels.get(m.channelId);
        if (!ch) {
            this.send(conn, encodeSubmitSharesError({
                channelId: m.channelId, sequenceNumber: m.sequenceNumber, errorCode: "no-such-channel",
            }));
            return;
        }
        const job = this.lookupJob(m.jobId);
        if (!job) {
            this.send(conn, encodeSubmitSharesError({
                channelId: m.channelId, sequenceNumber: m.sequenceNumber, errorCode: "stale-job",
            }));
            return;
        }
        const result = await processSubmit({
            channel: ch, job, sequenceNumber: m.sequenceNumber,
            nonce: m.nonce, ntime: m.ntime, version: m.version,
            extranonce: m.extranonce,
            blockHeight: job.height,
            networkDifficulty: networkDifficultyFromBits(job.bits),
        }, this.opts.log);
        this.replySubmit(conn, ch.id, m.sequenceNumber, result);
    }

    private replySubmit(conn: Conn, channelId: number, seq: number, r: Awaited<ReturnType<typeof processSubmit>>): void {
        if (!r.ok) {
            this.send(conn, encodeSubmitSharesError({
                channelId, sequenceNumber: seq, errorCode: r.reason,
            }));
            return;
        }
        const ch = conn.channels.get(channelId);
        if (ch) ch.lastAcceptedSequence = seq;
        this.send(conn, encodeSubmitSharesSuccess({
            channelId, lastSequenceNumber: seq,
            newSubmitsAcceptedCount: 1,
            newSharesSum: BigInt(Math.max(1, Math.floor((ch?.shareDifficulty ?? 1)))),
        }));
        this.opts.onShare(r.event);
    }

    // ---------------- broadcast ----------------

    private broadcastJob(job: StratumJob): void {
        for (const conn of this.conns) {
            if (conn.state !== "READY") continue;
            for (const ch of conn.channels.all()) this.pushJobToChannel(conn, ch.id, job);
        }
    }

    private pushJobToChannel(conn: Conn, channelId: number, job: StratumJob): void {
        const ch = conn.channels.get(channelId);
        if (!ch) return;
        const sv2JobId = nextSv2JobId();
        if (ch.kind === "standard") {
            const { bytes } = buildNewStandardJob(ch, job, sv2JobId);
            this.send(conn, bytes);
        } else {
            const { bytes } = buildNewExtendedJob(ch, job, sv2JobId);
            this.send(conn, bytes);
        }
        this.send(conn, buildSetNewPrevHash(ch, job, sv2JobId).bytes);
        ch.lastJobId = sv2JobId;
        this.jobsBySv2Id.set(sv2JobId, job);
        // Trim cache so it doesn't grow unbounded.
        if (this.jobsBySv2Id.size > 4096) {
            const oldest = this.jobsBySv2Id.keys().next().value;
            if (oldest !== undefined) this.jobsBySv2Id.delete(oldest);
        }
    }

    // SV2 job_id -> V1 StratumJob lookup so SubmitShares.jobId can find the
    // exact context the miner mined against (per-channel jobs share the same
    // sv2_job_id since the payload is identical apart from channel_id).
    private jobsBySv2Id = new Map<number, StratumJob>();

    private lookupJob(sv2JobId: number): StratumJob | undefined {
        return this.jobsBySv2Id.get(sv2JobId);
    }

    // ---------------- transport send ----------------

    private send(conn: Conn, plainFrame: Uint8Array): void {
        if (!conn.transport) return;
        // sanity: every plainFrame must include the SV2 header; inspect length
        if (plainFrame.length < SV2_HEADER_LEN) {
            this.opts.log.warn({ id: conn.id, len: plainFrame.length }, "send: short frame");
            return;
        }
        const ct = conn.transport.encryptFrame(plainFrame);
        conn.socket.write(Buffer.from(ct));
    }
}

// ---- byte helpers ----

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

function readU32LE(b: Uint8Array, off: number): number {
    return new DataView(b.buffer, b.byteOffset + off, 4).getUint32(0, true);
}

function hexToReversedBytes(hex: string): Uint8Array {
    const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
    if (clean.length % 2 !== 0) throw new Error("odd-length hex");
    const out = new Uint8Array(clean.length / 2);
    for (let i = 0; i < out.length; i++) {
        out[out.length - 1 - i] = parseInt(clean.substr(i * 2, 2), 16);
    }
    return out;
}
