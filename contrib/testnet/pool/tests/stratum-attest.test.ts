import { test } from "node:test";
import assert from "node:assert/strict";
import * as net from "net";
import { generateKeyPairSync, sign, type KeyObject } from "crypto";
import { StratumServer } from "../src/stratum/server";
import { JobManager, StratumJob } from "../src/stratum/job-manager";
import { IpcClient, ShareEvent, ShareSigEvent } from "../src/lib/ipc";
import { makeLogger } from "../src/lib/logger";
import { MemoryPassportStore } from "../src/lib/passports";
import { shareDigest } from "../src/lib/share-digest";

class FakeJobManager extends JobManager {
    constructor(private fakeJob: StratumJob) {
        super(makeLogger("test-jobs"));
    }
    override start(): void {}
    override stop(): void {}
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

function openClient(port: number): Promise<{ sock: net.Socket; next: () => Promise<Reply>; drain: (ms: number) => Promise<Reply[]> }> {
    const sock = net.createConnection({ host: "127.0.0.1", port });
    sock.setEncoding("utf8");
    let buf = "";
    const lines: Reply[] = [];
    sock.on("data", (chunk) => {
        buf += chunk;
        let idx;
        while ((idx = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, idx).trim();
            buf = buf.slice(idx + 1);
            if (!line) continue;
            lines.push(JSON.parse(line) as Reply);
        }
    });
    async function next(): Promise<Reply> {
        const start = Date.now();
        while (Date.now() - start < 1000) {
            const line = lines.shift();
            if (line) return line;
            await new Promise((r) => setTimeout(r, 5));
        }
        throw new Error("no stratum line");
    }
    async function drain(ms: number): Promise<Reply[]> {
        await new Promise((r) => setTimeout(r, ms));
        return lines.splice(0);
    }
    return new Promise((resolve, reject) => {
        sock.once("error", reject);
        sock.once("connect", () => resolve({ sock, next, drain }));
    });
}

function recorder(): IpcClient & { sent: Array<ShareEvent | ShareSigEvent> } {
    const sent: Array<ShareEvent | ShareSigEvent> = [];
    return {
        sent,
        send(msg: ShareEvent | ShareSigEvent) { sent.push(msg); },
        start() {},
        stop() {},
    } as IpcClient & { sent: Array<ShareEvent | ShareSigEvent> };
}

function deviceKey(): { pub: string; privateKey: KeyObject } {
    const { publicKey, privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
    const jwk = publicKey.export({ format: "jwk" }) as { x: string; y: string };
    const pub = Buffer.concat([
        Buffer.from(jwk.x, "base64url"),
        Buffer.from(jwk.y, "base64url"),
    ]).toString("hex");
    return { pub, privateKey };
}

async function authorize(port: number, user: string) {
    const client = await openClient(port);
    client.sock.write(JSON.stringify({ id: 1, method: "mining.subscribe", params: ["test/1.0"] }) + "\n");
    await client.next();
    client.sock.write(JSON.stringify({ id: 2, method: "mining.authorize", params: [user, "x"] }) + "\n");
    const auth = await client.next();
    assert.equal(auth.result, true);
    for (let i = 0; i < 4; i++) {
        const line = await client.next();
        if (line.method === "mining.notify") break;
    }
    return client;
}

test("empty slot then a valid challenge locks the passport", async () => {
    const store = new MemoryPassportStore();
    store.addUser("miner@example.com", 7);
    await store.addEmpty(7);
    const ipc = recorder();
    const server = new StratumServer(new FakeJobManager(makeFakeJob()), ipc, makeLogger("attest"), store, true);
    await server.listen(0);
    try {
        const { pub, privateKey } = deviceKey();
        const client = await authorize(server.boundPort(), "miner@example.com.rig1");
        client.sock.write(JSON.stringify({ id: 3, method: "mining.pubkey", params: [pub] }) + "\n");
        let challenge = "";
        for (let i = 0; i < 4; i++) {
            const line = await client.next();
            if (line.method === "mining.challenge") {
                challenge = String((line.params as string[])[0]);
                break;
            }
        }
        assert.equal(challenge.length, 64);
        const sig = sign(null, Buffer.from(challenge, "hex"), { key: privateKey, dsaEncoding: "ieee-p1363" }).toString("hex");
        client.sock.write(JSON.stringify({ id: 4, method: "mining.attest", params: [sig] }) + "\n");
        const attest = await client.next();
        assert.equal(attest.result, true);
        const row = server.connectionStats()[0];
        assert.equal(row?.pubkey, pub);
        assert.equal(row?.attest, "valid");
        assert.equal((await store.findSlotByPubkey(pub))?.slotNo, 1);
        client.sock.destroy();
    } finally {
        await server.close();
    }
});

test("a bad challenge signature leaves the slot empty", async () => {
    const store = new MemoryPassportStore();
    store.addUser("miner@example.com", 7);
    await store.addEmpty(7);
    const server = new StratumServer(new FakeJobManager(makeFakeJob()), recorder(), makeLogger("attest"), store, true);
    await server.listen(0);
    try {
        const { pub } = deviceKey();
        const client = await authorize(server.boundPort(), "miner@example.com.rig1");
        client.sock.write(JSON.stringify({ id: 3, method: "mining.pubkey", params: [pub] }) + "\n");
        for (let i = 0; i < 4; i++) {
            const line = await client.next();
            if (line.method === "mining.challenge") break;
        }
        client.sock.write(JSON.stringify({ id: 4, method: "mining.attest", params: ["ab".repeat(64)] }) + "\n");
        const attest = await client.next();
        assert.equal(attest.result, false);
        assert.equal(server.connectionStats()[0]?.attest, "invalid");
        assert.equal(await store.findSlotByPubkey(pub), null);
        assert.ok(await store.reserveEmpty(7, new Set()));
        client.sock.destroy();
    } finally {
        await server.close();
    }
});

test("no empty slot stays pending until a slot is added", async () => {
    const store = new MemoryPassportStore();
    store.addUser("miner@example.com", 7);
    const server = new StratumServer(new FakeJobManager(makeFakeJob()), recorder(), makeLogger("attest"), store, true);
    await server.listen(0);
    try {
        const first = deviceKey();
        const second = deviceKey();
        const a = await authorize(server.boundPort(), "miner@example.com.rig1");
        const b = await authorize(server.boundPort(), "miner@example.com.rig2");
        a.sock.write(JSON.stringify({ id: 3, method: "mining.pubkey", params: [first.pub] }) + "\n");
        b.sock.write(JSON.stringify({ id: 3, method: "mining.pubkey", params: [second.pub] }) + "\n");
        let stats = server.connectionStats();
        for (let i = 0; i < 50 && stats.filter((s) => s.attest === "pending").length < 2; i++) {
            await new Promise((r) => setTimeout(r, 10));
            stats = server.connectionStats();
        }
        stats = stats.sort((x, y) => x.worker.localeCompare(y.worker));
        assert.equal(stats[0]?.attest, "pending", JSON.stringify(stats));
        assert.equal(stats[1]?.attest, "pending");
        await store.addEmpty(7);
        await server.slotAdded(7);
        let challenge = "";
        for (let i = 0; i < 6; i++) {
            const line = await a.next();
            if (line.method === "mining.challenge") {
                challenge = String((line.params as string[])[0]);
                break;
            }
        }
        assert.equal(challenge.length, 64);
        const sig = sign(null, Buffer.from(challenge, "hex"), {
            key: first.privateKey,
            dsaEncoding: "ieee-p1363",
        }).toString("hex");
        a.sock.write(JSON.stringify({ id: 4, method: "mining.attest", params: [sig] }) + "\n");
        assert.equal((await a.next()).result, true);
        assert.equal((await store.findSlotByPubkey(first.pub))?.slotNo, 1);
        assert.equal(server.connectionStats().find((c) => c.worker === "rig2")?.attest, "pending");
        a.sock.destroy();
        b.sock.destroy();
    } finally {
        await server.close();
    }
});

test("a key locked on another account is not challenged", async () => {
    const store = new MemoryPassportStore();
    store.addUser("miner@example.com", 7);
    store.addUser("other@example.com", 8);
    const { pub } = deviceKey();
    const foreign = await store.addEmpty(8);
    await store.lock(foreign.id, pub);
    const empty = await store.addEmpty(7);
    const server = new StratumServer(new FakeJobManager(makeFakeJob()), recorder(), makeLogger("attest"), store, true);
    await server.listen(0);
    try {
        const client = await authorize(server.boundPort(), "miner@example.com.rig1");
        client.sock.write(JSON.stringify({ id: 3, method: "mining.pubkey", params: [pub] }) + "\n");
        let stats = server.connectionStats();
        for (let i = 0; i < 50 && stats[0]?.attest !== "invalid"; i++) {
            await new Promise((r) => setTimeout(r, 10));
            stats = server.connectionStats();
        }
        assert.equal(stats[0]?.attest, "invalid");
        const lines = await client.drain(40);
        assert.equal(lines.some((line) => line.method === "mining.challenge"), false);
        assert.equal((await store.findSlotByPubkey(pub))?.userId, 8);
        assert.equal((await store.reserveEmpty(7, new Set()))?.id, empty.id);
        client.sock.destroy();
    } finally {
        await server.close();
    }
});

test("a locked key is challenged again and does not take another slot", async () => {
    const store = new MemoryPassportStore();
    store.addUser("miner@example.com", 7);
    const { pub, privateKey } = deviceKey();
    const slot = await store.addEmpty(7);
    const hold = new Set<number>();
    await store.reserveEmpty(7, hold);
    await store.lock(slot.id, pub);
    hold.delete(slot.id);
    await store.addEmpty(7);
    const server = new StratumServer(new FakeJobManager(makeFakeJob()), recorder(), makeLogger("attest"), store, true);
    await server.listen(0);
    try {
        const client = await authorize(server.boundPort(), "miner@example.com.rig1");
        client.sock.write(JSON.stringify({ id: 3, method: "mining.pubkey", params: [pub] }) + "\n");
        let challenge = "";
        for (let i = 0; i < 4; i++) {
            const line = await client.next();
            if (line.method === "mining.challenge") {
                challenge = String((line.params as string[])[0]);
                break;
            }
        }
        const sig = sign(null, Buffer.from(challenge, "hex"), { key: privateKey, dsaEncoding: "ieee-p1363" }).toString("hex");
        client.sock.write(JSON.stringify({ id: 4, method: "mining.attest", params: [sig] }) + "\n");
        assert.equal((await client.next()).result, true);
        assert.equal(await store.reserveEmpty(7, new Set()) !== null, true);
        client.sock.destroy();
    } finally {
        await server.close();
    }
});

test("share credit requires a valid signature and stores the other results", async () => {
    const store = new MemoryPassportStore();
    store.addUser("miner@example.com", 7);
    const { pub, privateKey } = deviceKey();
    const ipc = recorder();
    const server = new StratumServer(new FakeJobManager(makeFakeJob()), ipc, makeLogger("attest"), store, true);
    await server.listen(0);
    const job = makeFakeJob();
    try {
        const client = await authorize(server.boundPort(), "miner@example.com.rig1");
        client.sock.write(JSON.stringify({
            id: 3,
            method: "mining.submit",
            params: ["miner@example.com.rig1", job.jobId, "00000000", "60ffffff", "00000001"],
        }) + "\n");
        const missing = await client.next();
        assert.ok(missing.error);
        assert.equal(ipc.sent.filter((m) => m.type === "share").length, 0);
        assert.equal(ipc.sent.filter((m) => m.type === "share_sig" && m.attest.result === "missing").length, 1);

        client.sock.write(JSON.stringify({ id: 5, method: "mining.pubkey", params: [pub] }) + "\n");
        await client.next();
        const digest = shareDigest(job.jobId, "00000000", 0x60ffffff, 2);
        const good = sign(null, digest, { key: privateKey, dsaEncoding: "ieee-p1363" }).toString("hex");
        const wrong = sign(null, shareDigest(job.jobId, "00000000", 0x60ffffff, 9), { key: privateKey, dsaEncoding: "ieee-p1363" }).toString("hex");
        client.sock.write(JSON.stringify({
            id: 6,
            method: "mining.submit",
            params: ["miner@example.com.rig1", job.jobId, "00000000", "60ffffff", "00000002", wrong],
        }) + "\n");
        const bad = await client.next();
        assert.ok(bad.error);
        assert.equal(ipc.sent.filter((m) => m.type === "share_sig" && m.attest.result === "invalid").length, 1);

        const beforeShares = ipc.sent.filter((m) => m.type === "share").length;
        client.sock.write(JSON.stringify({
            id: 7,
            method: "mining.submit",
            params: ["miner@example.com.rig1", job.jobId, "00000000", "60ffffff", "00000002", good],
        }) + "\n");
        const checked = await client.next();
        const start = Date.now();
        let credited = ipc.sent.filter((m) => m.type === "share");
        let validHist = ipc.sent.filter((m) => m.type === "share_sig" && m.attest.result === "valid");
        while (Date.now() - start < 1000 && credited.length === beforeShares && validHist.length === 0) {
            await new Promise((r) => setTimeout(r, 10));
            credited = ipc.sent.filter((m) => m.type === "share");
            validHist = ipc.sent.filter((m) => m.type === "share_sig" && m.attest.result === "valid");
        }
        if (checked.result === true) {
            assert.equal(credited.length, beforeShares + 1);
            assert.equal(credited.at(-1)?.attest?.result, "valid");
        } else {
            assert.equal(credited.length, beforeShares);
            assert.ok(validHist.length >= 1);
        }
        client.sock.destroy();
    } finally {
        await server.close();
    }
});
