// Stratum V1 TCP listener.
//
// Accepts mining.subscribe, mining.authorize, mining.submit; pushes
// mining.set_difficulty + mining.notify on new jobs and on vardiff retunes.
// Forwards every accepted share to the pool daemon over the IPC socket.

import * as crypto from "crypto";
import * as net from "net";
import { StratumClient, RpcCall } from "./client";
import { JobManager, StratumJob } from "./job-manager";
import { validateShare } from "./share-validator";
import { Logger, makeLogger } from "../lib/logger";
import { config } from "../config";
import { IpcClient, RejectEvent, ShareAttest, ShareEvent, ShareSigEvent } from "../lib/ipc";
import { normalizeRejectReason } from "../lib/reject-reason";
import { submitBlock } from "../lib/rpc";
import { networkDifficultyFromBits } from "../lib/difficulty-math";
import { verifyP256Digest } from "../lib/p256";
import { MemoryPassportStore, PassportStore } from "../lib/passports";
import { nonceHex, shareDigest } from "../lib/share-digest";

export class StratumServer {
    private server: net.Server;
    private clients = new Map<number, StratumClient>();
    public readonly log: Logger;
    private retuneTimer: NodeJS.Timeout | null = null;
    private readonly heldSlots = new Set<number>();
    public readonly signatureLog: ShareSigEvent[] = [];

    constructor(
        private jobs: JobManager,
        private ipc: IpcClient,
        log?: Logger,
        private passports: PassportStore = new MemoryPassportStore(),
        private recordSignatures = false,
    ) {
        this.log = log ?? makeLogger("stratum");
        this.server = net.createServer((s) => this.onConnection(s));
        this.jobs.on("job", (j: StratumJob) => this.broadcastJob(j));
    }

    listen(port = config.stratum.port): Promise<void> {
        return new Promise((res, rej) => {
            this.server.once("error", rej);
            this.server.listen(port, config.stratum.bind, () => {
                this.server.removeListener("error", rej);
                const addr = this.server.address();
                const bound = typeof addr === "object" && addr ? addr.port : port;
                this.log.info({ bind: config.stratum.bind, port: bound }, "stratum listening");
                this.startVardiffLoop();
                res();
            });
        });
    }

    boundPort(): number {
        const addr = this.server.address();
        return typeof addr === "object" && addr ? addr.port : 0;
    }

    close(): Promise<void> {
        if (this.retuneTimer) clearInterval(this.retuneTimer);
        for (const c of this.clients.values()) c.sock.destroy();
        return new Promise((res) => this.server.close(() => res()));
    }

    public clientCount(): number {
        return this.clients.size;
    }

    public connectionStats(): Array<{
        user: string;
        worker: string;
        difficulty: number;
        accepted: number;
        rejected: number;
        lastShareAt: number | null;
        pubkey: string | null;
        attest: "pending" | "valid" | "invalid" | null;
    }> {
        const out = [];
        for (const c of this.clients.values()) {
            if (c.state !== "authorized" || !c.username) continue;
            const [user, worker] = splitUserName(c.username);
            out.push({
                user,
                worker,
                difficulty: c.lastNotifiedDiff ?? c.vardiff.diff,
                accepted: c.sharesAccepted,
                rejected: c.sharesRejected,
                lastShareAt: c.lastShareAt > 0 ? c.lastShareAt : null,
                pubkey: c.pubkey,
                attest: c.attest === "" ? null : c.attest,
            });
        }
        return out;
    }

    private sendReject(c: StratumClient, reason: string): void {
        if (!c.username) return;
        const [user, worker] = splitUserName(c.username);
        const evt: RejectEvent = {
            type: "reject",
            user,
            workerName: worker,
            reason: normalizeRejectReason(reason),
            diff: c.vardiff.diff,
            timestampMs: Date.now(),
        };
        this.ipc.send(evt);
    }

    public estimatedHashrate(): number {
        // Sum of (currentDiff / vardiff.targetSeconds) * 2^32 across connections.
        let totalDiffPerSecond = 0;
        const now = Date.now();
        for (const c of this.clients.values()) {
            if (now - c.connectedAt < 30_000) continue;
            const d = c.vardiff.diff;
            // Connections converge to "1 share / vardiff.targetSeconds" by design.
            totalDiffPerSecond += d / c.vardiff.params.targetSeconds;
        }
        return totalDiffPerSecond * 4_294_967_296;
    }

    private startVardiffLoop(): void {
        this.retuneTimer = setInterval(() => {
            const now = Date.now();
            for (const c of this.clients.values()) {
                if (!config.stratum.vardiffEnabled) continue;
                const next = c.vardiff.maybeRetune(now);
                if (next !== null) {
                    c.pushDifficulty(c.wireShareDifficulty(next));
                    // New difficulty applies to the next notify, not shares
                    // already stamped on the current job id.
                }
            }
        }, 5_000);
    }

    private onConnection(sock: net.Socket): void {
        const c = new StratumClient(sock, this.log);
        this.clients.set(c.connId, c);
        this.log.info({ connId: c.connId, ip: c.ip }, "connection opened");
        c.on("close", () => {
            if (c.reservedSlotId !== null) {
                this.heldSlots.delete(c.reservedSlotId);
                c.reservedSlotId = null;
            }
            this.clients.delete(c.connId);
            this.log.info({ connId: c.connId, ip: c.ip }, "connection closed");
        });
        c.on("rpc", (msg: RpcCall) => this.handleRpc(c, msg));

        // Idle disconnect: 3 minutes without subscribe.
        setTimeout(() => {
            if (c.state === "new") c.fail("subscribe timeout");
        }, 180_000);
    }

    private broadcastJob(job: StratumJob): void {
        for (const c of this.clients.values()) {
            if (c.state !== "authorized") continue;
            c.pushJob(job);
        }
    }

    private async handleRpc(c: StratumClient, msg: RpcCall): Promise<void> {
        try {
            switch (msg.method) {
                case "mining.subscribe":
                    this.onSubscribe(c, msg);
                    break;
                case "mining.authorize":
                    await this.onAuthorize(c, msg);
                    break;
                case "mining.pubkey":
                    await this.onPubkey(c, msg);
                    break;
                case "mining.attest":
                    await this.onAttest(c, msg);
                    break;
                case "mining.submit":
                    await this.onSubmit(c, msg);
                    break;
                case "mining.extranonce.subscribe":
                    c.sendResult(msg.id ?? null, true);
                    break;
                case "mining.suggest_difficulty": {
                    const want = Number((msg.params as unknown[])[0] ?? 0);
                    try {
                        const applied = c.vardiff.setDiff(want);
                        c.pushDifficulty(c.wireShareDifficulty(applied));
                        c.sendResult(msg.id ?? null, true);
                    } catch (e) {
                        c.sendError(msg.id ?? null, 23, (e as Error).message);
                    }
                    break;
                }
                case "mining.suggest_target":
                    c.sendError(msg.id ?? null, 23, "use mining.suggest_difficulty");
                    break;
                default:
                    c.sendError(msg.id ?? null, -3, `unknown method ${msg.method}`);
            }
        } catch (e) {
            this.log.error({ connId: c.connId, method: msg.method, err: (e as Error).message }, "rpc handler error");
            c.sendError(msg.id ?? null, -32603, "internal error");
        }
    }

    private onSubscribe(c: StratumClient, msg: RpcCall): void {
        const params = (msg.params as unknown[]) ?? [];
        c.userAgent = String(params[0] ?? "");
        c.state = "subscribed";
        const subId = `b3chain-${c.connId.toString(16)}`;
        c.sendResult(msg.id ?? null, [
            [
                ["mining.set_difficulty", subId],
                ["mining.notify", subId],
            ],
            c.extranonce1Hex,
            c.extranonce2Size,
        ]);
        this.log.info({ connId: c.connId, ua: c.userAgent }, "subscribed");
    }

    private async onAuthorize(c: StratumClient, msg: RpcCall): Promise<void> {
        const params = (msg.params as unknown[]) ?? [];
        const username = String(params[0] ?? "").trim();
        if (!username) {
            c.sendResult(msg.id ?? null, false);
            return;
        }
        c.username = username;
        c.state = "authorized";
        c.authorizedAt = Date.now();
        const [email] = splitUserName(username);
        try {
            c.userId = await this.passports.findUserId(email);
        } catch (e) {
            this.log.warn({ err: (e as Error).message }, "device slot user lookup failed");
            c.userId = null;
        }
        const pinned = config.stratum.workerDifficulty.get(username);
        if (pinned !== undefined) {
            c.vardiff.setDiff(pinned);
        }
        c.sendResult(msg.id ?? null, true);

        const job = this.jobs.getCurrent();
        if (job) c.pushJob(job);
        this.log.info({ connId: c.connId, user: username }, "authorized");
    }

    async slotAdded(userId: number): Promise<void> {
        const pending = [...this.clients.values()]
            .filter((c) => c.state === "authorized" && c.attest === "pending" && c.pubkey && c.userId === userId)
            .sort((a, b) => a.authorizedAt - b.authorizedAt);
        const c = pending[0];
        if (!c || !c.pubkey) return;
        const slot = await this.passports.reserveEmpty(userId, this.heldSlots);
        if (!slot) return;
        c.reservedSlotId = slot.id;
        c.attest = "";
        this.sendChallenge(c);
    }

    private sendChallenge(c: StratumClient): void {
        c.challenge = crypto.randomBytes(32);
        c.sendNotify("mining.challenge", [c.challenge.toString("hex")]);
    }

    private noteSignature(evt: ShareSigEvent): void {
        this.ipc.send(evt);
        if (this.recordSignatures) this.signatureLog.push(evt);
    }

    private async onPubkey(c: StratumClient, msg: RpcCall): Promise<void> {
        if (c.state !== "authorized" || !c.username) {
            c.sendError(msg.id ?? null, 24, "Unauthorized worker");
            return;
        }
        const hex = String((msg.params as unknown[])?.[0] ?? "").toLowerCase();
        if (!/^[0-9a-f]{128}$/.test(hex)) {
            c.sendError(msg.id ?? null, 23, "bad public key");
            return;
        }
        c.pubkey = hex;
        if (c.userId === null) {
            c.attest = "pending";
            c.sendResult(msg.id ?? null, true);
            return;
        }
        const existing = await this.passports.findSlotByPubkey(hex);
        if (existing && existing.userId !== c.userId) {
            c.attest = "invalid";
            c.sendResult(msg.id ?? null, true);
            return;
        }
        if (existing && existing.userId === c.userId) {
            c.attest = "";
            c.sendResult(msg.id ?? null, true);
            this.sendChallenge(c);
            return;
        }
        const empty = await this.passports.reserveEmpty(c.userId, this.heldSlots);
        if (!empty) {
            c.attest = "pending";
            c.sendResult(msg.id ?? null, true);
            return;
        }
        c.reservedSlotId = empty.id;
        c.attest = "";
        c.sendResult(msg.id ?? null, true);
        this.sendChallenge(c);
    }

    private async onAttest(c: StratumClient, msg: RpcCall): Promise<void> {
        const sigHex = String((msg.params as unknown[])?.[0] ?? "").toLowerCase();
        const challenge = c.challenge;
        c.challenge = null;
        const ok = !!challenge && !!c.pubkey && verifyP256Digest(c.pubkey, challenge, sigHex);
        if (!ok) {
            if (c.reservedSlotId !== null) {
                this.heldSlots.delete(c.reservedSlotId);
                c.reservedSlotId = null;
            }
            c.attest = "invalid";
            c.sendResult(msg.id ?? null, false);
            return;
        }
        if (c.reservedSlotId !== null) {
            const slotId = c.reservedSlotId;
            const locked = await this.passports.lock(slotId, c.pubkey!);
            this.heldSlots.delete(slotId);
            c.reservedSlotId = null;
            if (!locked) {
                c.attest = "invalid";
                c.sendResult(msg.id ?? null, false);
                return;
            }
        }
        c.attest = "valid";
        c.sendResult(msg.id ?? null, true);
    }

    private async onSubmit(c: StratumClient, msg: RpcCall): Promise<void> {
        if (c.state !== "authorized") {
            c.sharesRejected++;
            this.sendReject(c, "other");
            c.sendError(msg.id ?? null, 24, "Unauthorized worker");
            return;
        }
        const p = (msg.params as unknown[]) ?? [];
        const [, jobIdAny, en2Any, ntimeAny, nonceAny] = p;
        const jobId = String(jobIdAny ?? "");
        const en2 = String(en2Any ?? "").toLowerCase();
        const ntime = parseInt(String(ntimeAny ?? ""), 16);
        const nonce = parseInt(String(nonceAny ?? ""), 16);
        if (!jobId || en2.length !== c.extranonce2Size * 2 || !Number.isFinite(ntime) || !Number.isFinite(nonce)) {
            c.sharesRejected++;
            this.sendReject(c, "other");
            c.sendError(msg.id ?? null, 23, "Invalid params");
            return;
        }
        const job = this.jobs.getById(jobId);
        if (!job) {
            c.sharesRejected++;
            this.sendReject(c, "other");
            c.sendResult(msg.id ?? null, false);
            return;
        }
        const attest = this.shareAttest(c, jobId, en2, ntime, nonce, p[5]);
        if (attest.result !== "valid") {
            this.recordUncredited(c, attest);
            c.sharesRejected++;
            this.sendReject(c, "invalid");
            c.sendError(msg.id ?? null, 23, attest.result === "missing" ? "signature required" : "bad signature");
            return;
        }
        const dedupKey = `${jobId}:${en2}:${ntime}:${nonce}`;
        if (c.seenShares.has(dedupKey)) {
            this.recordUncredited(c, attest);
            c.sharesRejected++;
            this.sendReject(c, "duplicate");
            c.sendError(msg.id ?? null, 22, "Duplicate share");
            return;
        }
        c.seenShares.add(dedupKey);
        if (c.seenShares.size > 50_000) {
            const it = c.seenShares.values();
            for (let i = 0; i < 10_000; i++) {
                const next = it.next();
                if (next.done) break;
                c.seenShares.delete(next.value);
            }
        }

        const assigned = c.jobShareDiff.get(jobId) ?? c.vardiff.diff;
        const check = validateShare({
            job,
            extranonce1Hex: c.extranonce1Hex,
            extranonce2Hex: en2,
            ntime,
            nonce,
            shareDifficulty: assigned,
        });
        if (!check.ok) {
            this.recordUncredited(c, attest);
            c.sharesRejected++;
            this.sendReject(c, check.reason);
            c.sendError(msg.id ?? null, 23, `low difficulty: ${check.reason}`);
            return;
        }

        if (check.meetsShare) {
            c.sharesAccepted++;
            c.vardiff.onShareAccepted();
        }
        c.lastShareAt = Date.now();
        c.sendResult(msg.id ?? null, true);

        const [emailPart, workerPart] = splitUserName(c.username);
        const networkDifficulty = networkDifficultyFromBits(job.bits);
        let blockHash: string | undefined;
        let blockHeight: number | undefined;

        if (check.isBlock && check.serializedBlockHex) {
            try {
                const result = await submitBlock(check.serializedBlockHex);
                if (result === null || result === "") {
                    blockHash = check.blockHashHexBE;
                    blockHeight = job.height;
                    this.log.warn(
                        { user: c.username, height: job.height, hash: blockHash },
                        "BLOCK FOUND and accepted"
                    );
                } else {
                    this.log.error({ result, user: c.username }, "submitblock rejected");
                }
            } catch (e) {
                this.log.error({ err: (e as Error).message, user: c.username }, "submitblock failed");
            }
        }

        const evt: ShareEvent = {
            type: "share",
            user: emailPart,
            workerName: workerPart,
            diff: check.meetsShare ? assigned : networkDifficulty,
            isBlock: !!blockHash,
            blockHash,
            blockHeight,
            networkDifficulty,
            timestampMs: Date.now(),
            attest,
        };
        this.ipc.send(evt);
    }

    private shareAttest(
        c: StratumClient,
        jobId: string,
        en2: string,
        ntime: number,
        nonce: number,
        sigAny: unknown,
    ): ShareAttest {
        const signature = sigAny === undefined || sigAny === null || sigAny === ""
            ? null
            : String(sigAny).toLowerCase();
        let result: ShareAttest["result"] = "missing";
        if (signature !== null) {
            const digest = shareDigest(jobId, en2, ntime, nonce);
            result = c.pubkey && verifyP256Digest(c.pubkey, digest, signature) ? "valid" : "invalid";
        }
        return { jobId, nonce: nonceHex(nonce), pubkey: c.pubkey, signature, result };
    }

    private recordUncredited(c: StratumClient, attest: ShareAttest): void {
        const [user, worker] = splitUserName(c.username);
        this.noteSignature({
            type: "share_sig",
            user,
            workerName: worker,
            timestampMs: Date.now(),
            attest,
        });
    }
}

export function splitUserName(s: string): [string, string] {
    const dot = s.lastIndexOf(".");
    if (dot <= 0 || dot === s.length - 1) return [s, "default"];
    return [s.slice(0, dot), s.slice(dot + 1)];
}
