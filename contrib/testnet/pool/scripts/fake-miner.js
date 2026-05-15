#!/usr/bin/env node
// A trivial Stratum V1 miner that connects, subscribes, authorizes, and
// then submits brute-force shares for the most recent job. Used by the
// e2e test (tests/e2e/mine-and-pay.test.ts).
//
// Not optimised — single threaded, no SIMD, nonce loop in JS — but
// sufficient for regtest where the difficulty is 1.

"use strict";
const net = require("net");
const { blake3 } = require("@noble/hashes/blake3");
const { sha256 } = require("@noble/hashes/sha2");

const username = process.argv[2] || "anon@example.com.dev";
const host = process.env.STRATUM_HOST || "127.0.0.1";
const port = parseInt(process.env.STRATUM_PORT || "3333", 10);

function blake3d(b) { return blake3(blake3(b)); }
function sha256d(b) { return sha256(sha256(b)); }
function fromHex(h) { return Buffer.from(h, "hex"); }
function reverseBytes(b) { const out = Buffer.alloc(b.length); for (let i = 0; i < b.length; i++) out[i] = b[b.length - 1 - i]; return out; }

let extranonce1 = "";
let diff = 1;
let job = null;
let id = 100;

function send(sock, obj) { sock.write(JSON.stringify(obj) + "\n"); }

const sock = net.createConnection({ host, port }, () => {
    send(sock, { id: id++, method: "mining.subscribe", params: ["fake-miner/1.0"] });
});
let buf = "";
sock.on("data", (chunk) => {
    buf += chunk.toString();
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line) continue;
        let m;
        try { m = JSON.parse(line); } catch { continue; }
        if (m.id != null && Array.isArray(m.result) && typeof m.result[1] === "string") {
            extranonce1 = m.result[1];
            send(sock, { id: id++, method: "mining.authorize", params: [username, "x"] });
        } else if (m.method === "mining.set_difficulty") {
            diff = Number(m.params[0] || 1);
        } else if (m.method === "mining.notify") {
            const [jobId, prev, coinb1, coinb2, branches, version, bits, ntime] = m.params;
            job = { jobId, prev, coinb1, coinb2, branches, version: parseInt(version, 16), bits: parseInt(bits, 16), ntime: parseInt(ntime, 16) };
        }
    }
});

const POOL_DIFF1 = (BigInt("0xffff") << 208n);
function targetForDiff(d) {
    const scale = 1_000_000n;
    return (POOL_DIFF1 * scale) / BigInt(Math.floor(d * Number(scale)));
}
function bigFromLE(b) { let n = 0n; for (let i = b.length - 1; i >= 0; i--) n = (n << 8n) | BigInt(b[i]); return n; }
function buildHeader(j, en1, en2, ntime, nonce) {
    const cb = Buffer.concat([fromHex(j.coinb1), fromHex(en1), fromHex(en2), fromHex(j.coinb2)]);
    const cbid = sha256d(cb);
    let merkle = Buffer.from(cbid);
    for (const br of j.branches) {
        const sib = reverseBytes(fromHex(br));
        merkle = Buffer.from(sha256d(Buffer.concat([merkle, sib])));
    }
    const h = Buffer.alloc(80);
    h.writeInt32LE(j.version, 0);
    reverseBytes(fromHex(j.prev)).copy(h, 4);
    merkle.copy(h, 36);
    h.writeUInt32LE(ntime, 68);
    h.writeUInt32LE(j.bits, 72);
    h.writeUInt32LE(nonce >>> 0, 76);
    return h;
}

let nonce = 0;
let en2c = 0;
setInterval(() => {
    if (!job) return;
    const en2 = (en2c++ % 0xffffffff).toString(16).padStart(8, "0");
    const target = targetForDiff(diff);
    for (let n = 0; n < 5000; n++, nonce++) {
        const h = buildHeader(job, extranonce1, en2, job.ntime, nonce);
        const pow = blake3d(h);
        if (bigFromLE(pow) <= target) {
            send(sock, {
                id: id++,
                method: "mining.submit",
                params: [username, job.jobId, en2, job.ntime.toString(16).padStart(8, "0"), nonce.toString(16).padStart(8, "0")],
            });
            nonce++;
            return;
        }
    }
}, 50);

process.on("SIGTERM", () => { try { sock.destroy(); } catch (e) {} process.exit(0); });
