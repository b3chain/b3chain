// Stratum V1 TCP listener.
//
// Accepts mining.subscribe, mining.authorize, mining.submit; pushes
// mining.set_difficulty + mining.notify on new jobs and on vardiff retunes.
// Forwards every accepted share to the pool daemon over the IPC socket.

import * as net from "net";
import { StratumClient, RpcCall } from "./client";
import { JobManager, StratumJob } from "./job-manager";
import { validateShare } from "./share-validator";
import { Logger, makeLogger } from "../lib/logger";
import { config } from "../config";
import { IpcClient, ShareEvent } from "../lib/ipc";
import { submitBlock } from "../lib/rpc";
import { networkDifficultyFromBits } from "../lib/difficulty-math";

export class StratumServer {
    private server: net.Server;
    private clients = new Map<number, StratumClient>();
    public readonly log: Logger;
    private retuneTimer: NodeJS.Timeout | null = null;

    constructor(
        private jobs: JobManager,
        private ipc: IpcClient,
        log?: Logger
    ) {
        this.log = log ?? makeLogger("stratum");
        this.server = net.createServer((s) => this.onConnection(s));
        this.jobs.on("job", (j: StratumJob) => this.broadcastJob(j));
    }

    listen(): Promise<void> {
        return new Promise((res, rej) => {
            this.server.once("error", rej);
            this.server.listen(config.stratum.port, config.stratum.bind, () => {
                this.server.removeListener("error", rej);
                this.log.info({ bind: config.stratum.bind, port: config.stratum.port }, "stratum listening");
                this.startVardiffLoop();
                res();
            });
        });
    }

    close(): Promise<void> {
        if (this.retuneTimer) clearInterval(this.retuneTimer);
        for (const c of this.clients.values()) c.sock.destroy();
        return new Promise((res) => this.server.close(() => res()));
    }

    public clientCount(): number {
        return this.clients.size;
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
                const next = c.vardiff.maybeRetune(now);
                if (next !== null) {
                    c.pushDifficulty(next);
                    if (c.lastJob) c.pushJob({ ...c.lastJob, cleanJobs: false });
                }
            }
        }, 5_000);
    }

    private onConnection(sock: net.Socket): void {
        const c = new StratumClient(sock, this.log);
        this.clients.set(c.connId, c);
        this.log.info({ connId: c.connId, ip: c.ip }, "connection opened");
        c.on("close", () => {
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
                    this.onAuthorize(c, msg);
                    break;
                case "mining.submit":
                    await this.onSubmit(c, msg);
                    break;
                case "mining.extranonce.subscribe":
                    c.sendResult(msg.id ?? null, true);
                    break;
                case "mining.suggest_difficulty": {
                    const want = Number((msg.params as unknown[])[0] ?? 0);
                    if (want > 0) {
                        const clamped = Math.min(
                            Math.max(want, c.vardiff.params.minDiff),
                            c.vardiff.params.maxDiff
                        );
                        c.pushDifficulty(clamped);
                        // No retune for explicit suggestion; vardiff still adapts.
                    }
                    c.sendResult(msg.id ?? null, true);
                    break;
                }
                case "mining.suggest_target":
                    c.sendResult(msg.id ?? null, true);
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

    private onAuthorize(c: StratumClient, msg: RpcCall): void {
        const params = (msg.params as unknown[]) ?? [];
        const username = String(params[0] ?? "").trim();
        if (!username) {
            c.sendResult(msg.id ?? null, false);
            return;
        }
        c.username = username;
        c.state = "authorized";
        c.sendResult(msg.id ?? null, true);

        // Push initial difficulty + current job.
        c.pushDifficulty(c.vardiff.diff);
        const job = this.jobs.getCurrent();
        if (job) c.pushJob(job);
        this.log.info({ connId: c.connId, user: username }, "authorized");
    }

    private async onSubmit(c: StratumClient, msg: RpcCall): Promise<void> {
        if (c.state !== "authorized") {
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
            c.sendError(msg.id ?? null, 23, "Invalid params");
            return;
        }
        const job = this.jobs.getById(jobId);
        if (!job) {
            c.sendResult(msg.id ?? null, false);
            return;
        }
        const dedupKey = `${jobId}:${en2}:${ntime}:${nonce}`;
        if (c.seenShares.has(dedupKey)) {
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

        const check = validateShare({
            job,
            extranonce1Hex: c.extranonce1Hex,
            extranonce2Hex: en2,
            ntime,
            nonce,
            shareDifficulty: c.vardiff.diff,
        });
        if (!check.ok) {
            c.sharesRejected++;
            c.sendError(msg.id ?? null, 23, `low difficulty: ${check.reason}`);
            return;
        }

        c.sharesAccepted++;
        c.lastShareAt = Date.now();
        c.vardiff.onShareAccepted();
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
            diff: c.vardiff.diff,
            isBlock: !!blockHash,
            blockHash,
            blockHeight,
            networkDifficulty,
            timestampMs: Date.now(),
        };
        this.ipc.send(evt);
    }
}

function splitUserName(s: string): [string, string] {
    const dot = s.indexOf(".");
    if (dot < 0) return [s, "default"];
    return [s.slice(0, dot), s.slice(dot + 1)];
}
