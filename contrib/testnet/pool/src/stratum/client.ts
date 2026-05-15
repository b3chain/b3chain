// Per-connection state for a single Stratum V1 miner.

import * as net from "net";
import { EventEmitter } from "events";
import { Vardiff, VardiffParams } from "./difficulty";
import { Logger } from "../lib/logger";
import { config } from "../config";
import { StratumJob } from "./job-manager";

export interface RpcCall {
    id: number | string | null;
    method: string;
    params: unknown[];
}

export type ClientState = "new" | "subscribed" | "authorized";

let nextConnId = 1;
let nextExtranonce1 = 0;

function allocExtranonce1Hex(): string {
    nextExtranonce1 = (nextExtranonce1 + 1) & 0xffffffff;
    return nextExtranonce1.toString(16).padStart(8, "0");
}

export class StratumClient extends EventEmitter {
    public readonly connId: number;
    public state: ClientState = "new";
    public readonly extranonce1Hex = allocExtranonce1Hex();
    public readonly extranonce2Size = 4;
    public userAgent = "";
    public username = "";
    public lastShareAt = 0;
    public sharesAccepted = 0;
    public sharesRejected = 0;
    public connectedAt = Date.now();
    public lastJob: StratumJob | null = null;
    public ip: string;
    public seenShares = new Set<string>();
    private buf = "";
    public readonly vardiff: Vardiff;

    constructor(public readonly sock: net.Socket, public readonly log: Logger) {
        super();
        this.connId = nextConnId++;
        this.ip = sock.remoteAddress ?? "";
        const params: VardiffParams = {
            targetSeconds: config.stratum.vardiffTargetSeconds,
            retuneSeconds: config.stratum.vardiffRetuneSeconds,
            minDiff: 64,
            maxDiff: 16_000_000,
            initialDiff: config.stratum.defaultDifficulty,
            maxStep: 4,
        };
        this.vardiff = new Vardiff(params);

        sock.setEncoding("utf8");
        sock.setNoDelay(true);
        sock.on("data", (chunk) => this.onData(chunk as unknown as string));
        sock.on("close", () => this.emit("close"));
        sock.on("error", (e) => this.log.warn({ connId: this.connId, err: e.message }, "socket error"));
    }

    private onData(chunk: string): void {
        this.buf += chunk;
        if (this.buf.length > 1024 * 16) {
            this.fail("oversized line");
            return;
        }
        let idx;
        while ((idx = this.buf.indexOf("\n")) >= 0) {
            const line = this.buf.slice(0, idx).trim();
            this.buf = this.buf.slice(idx + 1);
            if (!line) continue;
            try {
                const m = JSON.parse(line) as RpcCall;
                this.emit("rpc", m);
            } catch (e) {
                this.log.warn({ connId: this.connId, err: (e as Error).message, line: line.slice(0, 200) }, "parse error");
            }
        }
    }

    write(obj: object): void {
        if (this.sock.destroyed) return;
        this.sock.write(JSON.stringify(obj) + "\n");
    }

    sendResult(id: number | string | null, result: unknown): void {
        this.write({ id, result, error: null });
    }

    sendError(id: number | string | null, code: number, message: string): void {
        this.write({ id, result: null, error: [code, message, null] });
    }

    sendNotify(method: string, params: unknown[]): void {
        this.write({ id: null, method, params });
    }

    fail(reason: string): void {
        this.log.warn({ connId: this.connId, reason }, "closing connection");
        this.sock.destroy();
    }

    pushDifficulty(d: number): void {
        this.sendNotify("mining.set_difficulty", [d]);
    }

    pushJob(job: StratumJob): void {
        this.lastJob = job;
        this.sendNotify("mining.notify", [
            job.jobId,
            job.prevHashHexBE,
            job.coinb1Hex,
            job.coinb2Hex,
            job.merkleBranchesHexBE,
            "0x" + job.version.toString(16).padStart(8, "0"),
            "0x" + job.bits.toString(16).padStart(8, "0"),
            "0x" + job.ntimeRoll.toString(16).padStart(8, "0"),
            job.cleanJobs,
        ]);
    }
}
