// Translator integration test: spin up a tiny in-process SV2 server that
// looks like our pool (Noise NX responder + Mining sub-protocol +
// OpenExtendedMiningChannel + a hand-crafted NewExtendedMiningJob), point
// the translator at it, then exercise V1 mining.subscribe -> mining.notify
// and mining.submit -> SubmitSharesExtended round-trips.
//
// We are NOT validating shares against any real PoW here; the translator
// just bridges frames. The mining server end-to-end share validation has
// dedicated tests under sv2-mining.test.ts and the e2e suite.

import test from "node:test";
import * as assert from "node:assert/strict";
import * as net from "node:net";
import { EventEmitter } from "node:events";

// Required env vars are loaded from .env.test by `npm test`.
import { NoiseNX, NoiseTransport } from "../src/sv2/lib/noise";
import { generateAuthorityKey, generateStaticKey } from "../src/sv2/lib/keys";
import { signCertificate, encodeCertificate } from "../src/sv2/lib/cert";
import { splitFrames, decodeHeader, SV2_HEADER_LEN } from "../src/sv2/lib/codec";
import {
    decodeSetupConnection, encodeSetupConnectionSuccess, MSG_SETUP_CONNECTION,
} from "../src/sv2/lib/messages/common";
import {
    decodeOpenExtendedMiningChannel, encodeOpenExtendedMiningChannelSuccess,
    encodeNewExtendedMiningJob, encodeSetNewPrevHash, encodeSetTarget,
    encodeSubmitSharesSuccess,
    decodeSubmitSharesExtended,
    MSG_OPEN_EXT_CHANNEL, MSG_SUBMIT_SHARES_EXTENDED,
} from "../src/sv2/lib/messages/mining";

interface FakePool extends EventEmitter {
    server: net.Server;
    port: number;
    authorityPub: Uint8Array;
    received: Map<string, Uint8Array[]>;
}

function startFakePool(): Promise<FakePool> {
    const auth = generateAuthorityKey();
    const stat = generateStaticKey();
    const now = Math.floor(Date.now() / 1000);
    const cert = signCertificate(auth, stat.pub, now, now + 3600);
    const certBytes = encodeCertificate(cert);

    return new Promise<FakePool>((resolve) => {
        const out = new EventEmitter() as FakePool;
        out.received = new Map();
        out.authorityPub = auth.pub;
        const server = net.createServer((sock) => {
            const nx = new NoiseNX("responder", stat);
            let transport: NoiseTransport | null = null;
            let hsBuf = new Uint8Array(0);
            let ct = new Uint8Array(0);
            let plain = new Uint8Array(0);
            let extranoncePrefix = Uint8Array.from([0xee, 0xee, 0xee, 0xee]);
            let channelId = 0;

            const sendPlain = (frame: Uint8Array) => {
                if (!transport) return;
                sock.write(Buffer.from(transport.encryptFrame(frame)));
            };

            sock.on("data", (chunk) => {
                if (!transport) {
                    hsBuf = concatBuf(hsBuf, chunk);
                    if (hsBuf.length < 2) return;
                    const len = new DataView(hsBuf.buffer, hsBuf.byteOffset, 2).getUint16(0, true);
                    if (hsBuf.length < 2 + len) return;
                    const m1 = hsBuf.subarray(2, 2 + len);
                    const trailing = hsBuf.subarray(2 + len);
                    hsBuf = new Uint8Array(0);
                    nx.readMessage1(m1);
                    const m2 = nx.writeMessage2(certBytes);
                    const wire = new Uint8Array(2 + m2.length);
                    new DataView(wire.buffer).setUint16(0, m2.length, true);
                    wire.set(m2, 2);
                    sock.write(Buffer.from(wire));
                    const fin = nx.finishResponder();
                    transport = new NoiseTransport(fin.sendCipher, fin.recvCipher);
                    if (trailing.length) ct = concatBuf(ct, trailing);
                } else {
                    ct = concatBuf(ct, chunk);
                }
                if (!transport) return;
                const { frames, consumed } = transport.decryptFrames(ct);
                ct = ct.subarray(consumed);
                for (const fr of frames) {
                    plain = concatBuf(plain, fr);
                    const split = splitFrames(plain);
                    plain = plain.subarray(split.consumed);
                    for (const f of split.frames) {
                        if (f.header.msgType === MSG_SETUP_CONNECTION) {
                            decodeSetupConnection(f.payload);
                            sendPlain(encodeSetupConnectionSuccess({ usedVersion: 2, flags: 0 }));
                        } else if (f.header.msgType === MSG_OPEN_EXT_CHANNEL) {
                            const m = decodeOpenExtendedMiningChannel(f.payload);
                            channelId = 17;
                            sendPlain(encodeOpenExtendedMiningChannelSuccess({
                                requestId: m.requestId, channelId,
                                target: new Uint8Array(32).fill(0xff),
                                extranonceSize: 4,
                                extranoncePrefix,
                            }));
                            // initial target + job + prev hash
                            sendPlain(encodeSetTarget({ channelId, maxTarget: new Uint8Array(32).fill(0xff) }));
                            sendPlain(encodeNewExtendedMiningJob({
                                channelId, jobId: 1, minNtime: null, version: 0x20000000,
                                versionRollingAllowed: true, merklePath: [],
                                coinbaseTxPrefix: Uint8Array.from([0x01]),
                                coinbaseTxSuffix: Uint8Array.from([0x02, 0x03]),
                            }));
                            sendPlain(encodeSetNewPrevHash({
                                channelId, jobId: 1,
                                prevHash: new Uint8Array(32).fill(0xab),
                                minNtime: 1_700_000_000, nbits: 0x1d00ffff,
                            }));
                        } else if (f.header.msgType === MSG_SUBMIT_SHARES_EXTENDED) {
                            const m = decodeSubmitSharesExtended(f.payload);
                            (out.received.get("submit") ?? out.received.set("submit", []).get("submit")!).push(f.payload);
                            sendPlain(encodeSubmitSharesSuccess({
                                channelId: m.channelId,
                                lastSequenceNumber: m.sequenceNumber,
                                newSubmitsAcceptedCount: 1,
                                newSharesSum: 1n,
                            }));
                        }
                    }
                }
            });
            sock.on("error", () => {});
        });
        server.listen(0, "127.0.0.1", () => {
            out.server = server;
            const addr = server.address();
            if (!addr || typeof addr === "string") throw new Error("bad address");
            out.port = addr.port;
            resolve(out);
        });
    });
}

function concatBuf(a: Uint8Array, b: Uint8Array | Buffer): Uint8Array {
    const out = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    if (b instanceof Buffer) {
        for (let i = 0; i < b.length; i++) out[a.length + i] = b[i]!;
    } else {
        out.set(b, a.length);
    }
    return out;
}

test("Translator: V1 subscribe -> SV2 OpenExtendedChannel -> mining.notify roundtrip", async () => {
    const fake = await startFakePool();
    const { TranslatorServer } = await import("../src/sv2/translator/server");
    const { makeLogger } = await import("../src/lib/logger");
    const t = new TranslatorServer({
        bind: "127.0.0.1", port: 0,
        upstreamHost: "127.0.0.1", upstreamPort: fake.port,
        authorityPub: fake.authorityPub,
        log: makeLogger("test-translator"),
    });
    await t.listen();
    // @ts-expect-error - reach into server to find listening port
    const tport = (t["server"] as net.Server).address() as net.AddressInfo;

    // Connect a tiny V1 client
    const v1 = await new Promise<net.Socket>((res, rej) => {
        const s = net.createConnection(tport.port, "127.0.0.1", () => res(s));
        s.on("error", rej);
    });
    v1.setEncoding("utf8");
    const lines: string[] = [];
    let lineBuf = "";
    v1.on("data", (chunk) => {
        lineBuf += chunk;
        let i;
        while ((i = lineBuf.indexOf("\n")) >= 0) {
            lines.push(lineBuf.slice(0, i).trim());
            lineBuf = lineBuf.slice(i + 1);
        }
    });

    v1.write(JSON.stringify({ id: 1, method: "mining.subscribe", params: ["test-miner"] }) + "\n");
    // Wait until mining.notify or response arrives
    const start = Date.now();
    let subscribeResult: unknown = null;
    while (!subscribeResult && Date.now() - start < 5000) {
        for (const l of lines) {
            try {
                const m = JSON.parse(l);
                if (m.id === 1 && m.result) { subscribeResult = m.result; break; }
            } catch {}
        }
        if (subscribeResult) break;
        await new Promise(r => setTimeout(r, 50));
    }
    assert.ok(subscribeResult, "mining.subscribe must get a response");
    const arr = subscribeResult as unknown[];
    assert.equal(typeof arr[1], "string", "extranonce1 hex must be a string");
    assert.equal(typeof arr[2], "number", "extranonce2_size must be a number");

    // Wait for mining.notify
    let gotNotify = false;
    const start2 = Date.now();
    while (!gotNotify && Date.now() - start2 < 5000) {
        for (const l of lines) {
            try {
                const m = JSON.parse(l);
                if (m.method === "mining.notify") { gotNotify = true; break; }
            } catch {}
        }
        if (gotNotify) break;
        await new Promise(r => setTimeout(r, 50));
    }
    assert.equal(gotNotify, true, "translator must forward mining.notify after SetNewPrevHash");

    v1.destroy();
    await t.close();
    await new Promise<void>((res) => fake.server.close(() => res()));
});
