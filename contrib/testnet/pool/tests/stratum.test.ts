// Stratum-protocol surface test: connect to the stratum server with a
// throwaway TCP client, exchange subscribe + authorize + a synthetic
// submit, and assert the wire shape (not block validity).
//
// We stub the JobManager by injecting a fixed job that the test client
// can't possibly submit a winning share for — but our share validator
// will reject with `low-diff` rather than crash, which is exactly what
// we want to assert.

import { test } from "node:test";
import assert from "node:assert/strict";
import * as net from "net";
import { StratumServer } from "../src/stratum/server";
import { JobManager, StratumJob } from "../src/stratum/job-manager";
import { IpcClient } from "../src/lib/ipc";
import { makeLogger } from "../src/lib/logger";

class FakeJobManager extends JobManager {
    private fakeJob: StratumJob;
    constructor(j: StratumJob) {
        super(makeLogger("test-jobs"));
        this.fakeJob = j;
    }
    override start(): void { /* no-op */ }
    override stop(): void { /* no-op */ }
    override getCurrent() { return this.fakeJob; }
    override getById(id: string) { return id === this.fakeJob.jobId ? this.fakeJob : undefined; }
}

function makeFakeJob(): StratumJob {
    return {
        jobId: "deadbee",
        coinb1Hex: "00".repeat(40),
        coinb2Hex: "00".repeat(40),
        merkleBranchesHexBE: [],
        version: 1,
        bits: 0x207fffff,
        prevHashHexBE: "00".repeat(32),
        networkTargetHexBE: "ff".repeat(32),
        txnsHex: [],
        height: 1,
        cleanJobs: true,
        ntimeMin: 1700000000,
        ntimeRoll: 1700000000,
    };
}

interface Reply { id?: number | string | null; result?: unknown; error?: unknown; method?: string; params?: unknown[] }

function client(port: number): { sock: net.Socket; lines: AsyncGenerator<Reply> } {
    const sock = net.createConnection({ host: "127.0.0.1", port });
    sock.setEncoding("utf8");
    let buf = "";
    let resolveOne: ((line: Reply) => void) | null = null;
    const queue: Reply[] = [];
    sock.on("data", (chunk) => {
        buf += chunk;
        let idx;
        while ((idx = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, idx).trim();
            buf = buf.slice(idx + 1);
            if (!line) continue;
            const obj = JSON.parse(line) as Reply;
            if (resolveOne) {
                const r = resolveOne;
                resolveOne = null;
                r(obj);
            } else queue.push(obj);
        }
    });
    async function* lines(): AsyncGenerator<Reply> {
        while (true) {
            if (queue.length > 0) yield queue.shift()!;
            else yield await new Promise<Reply>((res) => (resolveOne = res));
        }
    }
    return { sock, lines: lines() };
}

test("subscribe -> authorize -> low-diff submit roundtrip", async () => {
    process.env.B3POOL_RPC_HOST = process.env.B3POOL_RPC_HOST ?? "127.0.0.1";
    process.env.B3POOL_RPC_USER = process.env.B3POOL_RPC_USER ?? "x";
    process.env.B3POOL_RPC_PASSWORD = process.env.B3POOL_RPC_PASSWORD ?? "x";
    process.env.B3POOL_DB_URL = process.env.B3POOL_DB_URL ?? "postgres://x@127.0.0.1/x";
    process.env.B3POOL_COOKIE_SECRET = process.env.B3POOL_COOKIE_SECRET ?? "x".repeat(32);
    process.env.B3POOL_STRATUM_PORT = "13333";

    const job = makeFakeJob();
    const ipc = new IpcClient("/tmp/b3pool-test.sock");
    const jobs = new FakeJobManager(job);
    const server = new StratumServer(jobs, ipc, makeLogger("test-stratum"));
    await server.listen();

    try {
        const { sock, lines } = client(13333);

        sock.write(JSON.stringify({ id: 1, method: "mining.subscribe", params: ["test/1.0"] }) + "\n");
        const sub = await lines.next();
        assert.equal(sub.value!.id, 1);
        const result = sub.value!.result as unknown[];
        assert.ok(Array.isArray(result));
        assert.equal(typeof result[1], "string"); // extranonce1
        assert.equal(typeof result[2], "number"); // extranonce2_size

        sock.write(JSON.stringify({ id: 2, method: "mining.authorize", params: ["anon@example.com.t", "x"] }) + "\n");
        const auth = await lines.next();
        assert.equal(auth.value!.id, 2);
        assert.equal(auth.value!.result, true);

        // Should immediately get set_difficulty + notify.
        let sawDiff = false;
        let sawNotify = false;
        for (let i = 0; i < 4; i++) {
            const r = await lines.next();
            if (r.value!.method === "mining.set_difficulty") sawDiff = true;
            if (r.value!.method === "mining.notify") {
                sawNotify = true;
                break;
            }
        }
        assert.ok(sawDiff, "expected mining.set_difficulty");
        assert.ok(sawNotify, "expected mining.notify");

        // Submit a low-diff share using nonce 0 (vanishingly small chance of being valid).
        sock.write(
            JSON.stringify({
                id: 3,
                method: "mining.submit",
                params: ["anon@example.com.t", job.jobId, "00000000", "60ffffff", "00000000"],
            }) + "\n"
        );
        const sub2 = await lines.next();
        assert.equal(sub2.value!.id, 3);
        // Either accepted (almost impossible) or rejected with low-diff error.
        if (sub2.value!.result !== true) {
            assert.ok(sub2.value!.error, "expected error array");
        }
        sock.destroy();
    } finally {
        await server.close();
        ipc.stop();
    }
});
