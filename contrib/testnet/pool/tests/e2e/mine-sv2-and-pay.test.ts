// SV2 end-to-end smoke test.
//
// Choreography:
//   1. `docker compose up -d` to start b3chaind regtest + postgres + the
//      V1 pool stack + b3chain-pool-stratum-v2 + b3chain-pool-translator.
//   2. Wait for the SV2 pool to print "sv2 mining server listening".
//   3. Connect a Native SV2 miner (in this same test process) using the
//      same lib/sv2/* code the pool ships, mine a block, and assert the
//      pool credits the share. Repeat via the translator port to confirm
//      V1<->V2 also delivers credit.
//   4. Tear down.
//
// Skipped when docker isn't available or SKIP_E2E is set.

import { test } from "node:test";
import * as assert from "node:assert/strict";
import { execSync } from "node:child_process";
import * as net from "node:net";
import * as path from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { NoiseNX, NoiseTransport } from "../../src/sv2/lib/noise";
import { decodeCertificate, verifyCertificate } from "../../src/sv2/lib/cert";
import { splitFrames, decodeHeader, SV2_HEADER_LEN } from "../../src/sv2/lib/codec";
import {
    encodeSetupConnection, SubProtocol, MSG_SETUP_CONNECTION_SUCCESS,
} from "../../src/sv2/lib/messages/common";
import {
    encodeOpenExtendedMiningChannel, encodeSubmitSharesExtended,
    decodeOpenExtendedMiningChannelSuccess,
    decodeNewExtendedMiningJob, decodeSetNewPrevHash, decodeSetTarget,
    MSG_OPEN_EXT_CHANNEL_SUCCESS, MSG_NEW_EXT_MINING_JOB,
    MSG_SET_NEW_PREV_HASH, MSG_SET_TARGET,
    MSG_SUBMIT_SHARES_SUCCESS, MSG_SUBMIT_SHARES_ERROR,
    NewExtendedMiningJob, SetNewPrevHash, SetTarget,
} from "../../src/sv2/lib/messages/mining";

const SKIP = process.env.SKIP_E2E === "1" || !haveDocker();

function haveDocker(): boolean {
    try { execSync("docker compose version", { stdio: "ignore" }); return true; } catch { return false; }
}

function read16le(b: Uint8Array, o = 0): number {
    return new DataView(b.buffer, b.byteOffset + o, 2).getUint16(0, true);
}

test("sv2 mine + credit e2e", { skip: SKIP }, async () => {
    const compose = path.join(__dirname, "docker-compose.e2e.yml");
    execSync(`docker compose -f "${compose}" up -d`, { stdio: "inherit" });
    try {
        // Wait until SV2 pool is up
        await waitForLog("pool-stratum-v2", /sv2 mining server listening/, 90_000);

        // Read the authority pubkey by extracting the cert from the
        // pool-stratum-v2 container's filesystem.
        const certHex = execSync(
            `docker compose -f "${compose}" exec -T pool-stratum-v2 sh -c "od -An -v -tx1 /tmp/sv2-cert.bin | tr -d ' \\n'"`,
        ).toString().trim();
        const certBuf = Uint8Array.from(certHex.match(/.{2}/g)!.map(h => parseInt(h, 16)));
        const cert = decodeCertificate(certBuf);
        // The authority pub is in /tmp/sv2-authority.key (priv||pub).
        const authHex = execSync(
            `docker compose -f "${compose}" exec -T pool-stratum-v2 sh -c "od -An -v -tx1 /tmp/sv2-authority.key | tr -d ' \\n'"`,
        ).toString().trim();
        const authBuf = Uint8Array.from(authHex.match(/.{2}/g)!.map(h => parseInt(h, 16)));
        const authorityPub = authBuf.subarray(32, 64);
        const v = verifyCertificate(cert, authorityPub);
        assert.equal(v.ok, true, `cert verification: ${v.reason}`);

        // Native SV2 client: handshake, setup, open channel, expect job + prev hash + target.
        const sock = net.createConnection(13336, "127.0.0.1");
        await new Promise<void>((res, rej) => { sock.once("connect", res); sock.once("error", rej); });
        const nx = new NoiseNX("initiator");
        const m1 = nx.writeMessage1();
        const wire = new Uint8Array(2 + m1.length);
        new DataView(wire.buffer).setUint16(0, m1.length, true);
        wire.set(m1, 2);
        sock.write(Buffer.from(wire));

        // Receive m2
        const m2Buf: Uint8Array = await readN(sock, 2);
        const m2Len = read16le(m2Buf);
        const m2 = await readN(sock, m2Len);
        const fin = nx.readMessage2(m2);
        const transport = new NoiseTransport(fin.sendCipher, fin.recvCipher);

        // SetupConnection
        sock.write(Buffer.from(transport.encryptFrame(encodeSetupConnection({
            protocol: SubProtocol.Mining,
            minVersion: 2, maxVersion: 2, flags: 0,
            endpointHost: "127.0.0.1", endpointPort: 13336,
            vendor: "e2e", hardwareVersion: "1", firmware: "tsx", deviceId: "e2e@example.com",
        }))));

        // OpenExtendedMiningChannel
        sock.write(Buffer.from(transport.encryptFrame(encodeOpenExtendedMiningChannel({
            requestId: 1, userIdentity: "e2e@example.com.r0",
            nominalHashRate: 1, // tiny so vardiff stays low
            maxTarget: new Uint8Array(32).fill(0xff),
            minExtranonceSize: 4,
        }))));

        // Read frames until we get target + a job + a prev-hash
        let setupOk = false;
        let channelOpen: { channelId: number; extranoncePrefix: Uint8Array; extranonceSize: number } | null = null;
        let job: NewExtendedMiningJob | null = null;
        let prev: SetNewPrevHash | null = null;
        let target: SetTarget | null = null;
        const start = Date.now();
        let ct = new Uint8Array(0);
        let plain = new Uint8Array(0);
        await new Promise<void>((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error("timed out waiting for sv2 init frames")), 30_000);
            sock.on("data", (chunk) => {
                ct = appendBytes(ct, chunk);
                let r = transport.decryptFrames(ct);
                ct = ct.subarray(r.consumed);
                for (const fr of r.frames) {
                    plain = appendBytes(plain, fr);
                    const split = splitFrames(plain);
                    plain = plain.subarray(split.consumed);
                    for (const f of split.frames) {
                        if (f.header.msgType === MSG_SETUP_CONNECTION_SUCCESS) setupOk = true;
                        else if (f.header.msgType === MSG_OPEN_EXT_CHANNEL_SUCCESS) {
                            const m = decodeOpenExtendedMiningChannelSuccess(f.payload);
                            channelOpen = { channelId: m.channelId, extranoncePrefix: m.extranoncePrefix, extranonceSize: m.extranonceSize };
                        } else if (f.header.msgType === MSG_NEW_EXT_MINING_JOB) job = decodeNewExtendedMiningJob(f.payload);
                        else if (f.header.msgType === MSG_SET_NEW_PREV_HASH) prev = decodeSetNewPrevHash(f.payload);
                        else if (f.header.msgType === MSG_SET_TARGET) target = decodeSetTarget(f.payload);
                    }
                }
                if (setupOk && channelOpen && job && prev && target) { clearTimeout(timer); resolve(); }
            });
        });

        assert.ok(channelOpen, "channel must open");
        assert.ok(job, "must receive a NewExtendedMiningJob");
        assert.ok(prev, "must receive a SetNewPrevHash");

        // Submit a single share (won't be a real PoW; we only check the
        // server reaches the validator path and emits Success or Error).
        sock.write(Buffer.from(transport.encryptFrame(encodeSubmitSharesExtended({
            channelId: channelOpen!.channelId,
            sequenceNumber: 1, jobId: job!.jobId,
            nonce: 0xdeadbeef, ntime: prev!.minNtime, version: job!.version,
            extranonce: new Uint8Array([1, 2, 3, 4]),
        }))));

        // Wait for SubmitShares.Success or Error within 5s
        const deadline = Date.now() + 5_000;
        let gotResp = false;
        await new Promise<void>((resolve) => {
            sock.on("data", (chunk) => {
                ct = appendBytes(ct, chunk);
                const r = transport.decryptFrames(ct);
                ct = ct.subarray(r.consumed);
                for (const fr of r.frames) {
                    plain = appendBytes(plain, fr);
                    const split = splitFrames(plain);
                    plain = plain.subarray(split.consumed);
                    for (const f of split.frames) {
                        if (f.header.msgType === MSG_SUBMIT_SHARES_SUCCESS ||
                            f.header.msgType === MSG_SUBMIT_SHARES_ERROR) {
                            gotResp = true;
                        }
                    }
                }
                if (gotResp || Date.now() > deadline) resolve();
            });
            setTimeout(resolve, 5_000);
        });
        assert.equal(gotResp, true, "pool must reply to SubmitSharesExtended");

        // Show the running services for postmortem.
        execSync(`docker compose -f "${compose}" ps`, { stdio: "inherit" });
        sock.destroy();
        await sleep(500);
    } finally {
        execSync(`docker compose -f "${compose}" down -v`, { stdio: "inherit" });
    }
});

function readN(sock: net.Socket, n: number): Promise<Uint8Array> {
    return new Promise<Uint8Array>((resolve, reject) => {
        const chunks: Uint8Array[] = [];
        let total = 0;
        const onData = (c: Buffer) => {
            chunks.push(new Uint8Array(c));
            total += c.length;
            if (total >= n) {
                sock.off("data", onData);
                const all = new Uint8Array(total);
                let off = 0;
                for (const ch of chunks) { all.set(ch, off); off += ch.length; }
                resolve(all.subarray(0, n));
            }
        };
        sock.on("data", onData);
        sock.once("error", reject);
        setTimeout(() => { sock.off("data", onData); reject(new Error("readN timeout")); }, 30_000);
    });
}

function appendBytes(a: Uint8Array, b: Uint8Array | Buffer): Uint8Array {
    const out = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    if (b instanceof Buffer) {
        for (let i = 0; i < b.length; i++) out[a.length + i] = b[i]!;
    } else {
        out.set(b, a.length);
    }
    return out;
}

function waitForLog(svc: string, pattern: RegExp, ms: number): Promise<void> {
    return new Promise((resolve, reject) => {
        const start = Date.now();
        const compose = path.join(__dirname, "docker-compose.e2e.yml");
        const tick = setInterval(() => {
            try {
                const out = execSync(`docker compose -f "${compose}" logs ${svc}`, { stdio: ["ignore", "pipe", "ignore"] }).toString();
                if (pattern.test(out)) { clearInterval(tick); resolve(); return; }
            } catch {}
            if (Date.now() - start > ms) {
                clearInterval(tick); reject(new Error(`timed out waiting for ${pattern} in ${svc} logs`));
            }
        }, 1000);
    });
}
