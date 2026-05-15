// Stratum V2 Noise NX handshake + transport.
//
// Cipher suite:
//   DH        : X25519
//   Hash      : BLAKE2s (32-byte digest)
//   AEAD      : ChaCha20-Poly1305
//
// Pattern Noise_NX_25519_ChaChaPoly_BLAKE2s:
//   ->  e
//   <-  e, ee, s, es
//
// After the second message the channel is in transport mode; both sides
// derive a pair of cipher keys from `Split()` and then encrypt every
// SV2 frame as a Noise transport message (max 65 535 bytes plaintext per
// segment, +16-byte AEAD tag per segment).
//
// The static key carried by the responder (the pool) is wrapped in our
// own SignedCertificate envelope (see cert.ts). The responder appends it
// to the s payload of message 2 so the initiator (the miner) can verify
// the static key against a published authority Ed25519 key.

import { x25519 } from "@noble/curves/ed25519";
import { chacha20poly1305 } from "@noble/ciphers/chacha";
import { blake2s } from "@noble/hashes/blake2s";
import { hmac } from "@noble/hashes/hmac";
import { randomBytes } from "node:crypto";

const PROTOCOL_NAME = "Noise_NX_25519_ChaChaPoly_BLAKE2s";
const HASH_LEN = 32;
const KEY_LEN = 32;
const TAG_LEN = 16;
const MAX_NONCE = 2n ** 64n - 1n;

// ---------- low-level primitives ----------

function dh(priv: Uint8Array, pub: Uint8Array): Uint8Array {
    return x25519.getSharedSecret(priv, pub);
}

function hash(d: Uint8Array): Uint8Array {
    return blake2s(d, { dkLen: HASH_LEN });
}

function hashConcat(a: Uint8Array, b: Uint8Array): Uint8Array {
    const out = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    out.set(b, a.length);
    return hash(out);
}

// HKDF over BLAKE2s as defined by the Noise spec.
function hkdf(chainingKey: Uint8Array, ikm: Uint8Array, n: 2 | 3): Uint8Array[] {
    const tempKey = hmac(blake2s, chainingKey, ikm);
    const out1 = hmac(blake2s, tempKey, Uint8Array.from([0x01]));
    const out2 = hmac(blake2s, tempKey, concat(out1, Uint8Array.from([0x02])));
    if (n === 2) return [out1, out2];
    const out3 = hmac(blake2s, tempKey, concat(out2, Uint8Array.from([0x03])));
    return [out1, out2, out3];
}

function concat(...arrs: Uint8Array[]): Uint8Array {
    let total = 0;
    for (const a of arrs) total += a.length;
    const out = new Uint8Array(total);
    let off = 0;
    for (const a of arrs) { out.set(a, off); off += a.length; }
    return out;
}

function nonceBytes(n: bigint): Uint8Array {
    if (n > MAX_NONCE) throw new Error("noise nonce overflow");
    // ChaCha20-Poly1305 12-byte nonce: 4 zero bytes || u64 LE counter
    const out = new Uint8Array(12);
    new DataView(out.buffer).setBigUint64(4, n, true);
    return out;
}

// ---------- CipherState ----------

class CipherState {
    private k: Uint8Array | null;
    private n: bigint;

    constructor(key?: Uint8Array) {
        this.k = key ?? null;
        this.n = 0n;
    }

    hasKey(): boolean { return this.k !== null; }

    encryptWithAd(ad: Uint8Array, plaintext: Uint8Array): Uint8Array {
        if (!this.k) return plaintext;
        const out = chacha20poly1305(this.k, nonceBytes(this.n), ad).encrypt(plaintext);
        this.n++;
        return out;
    }

    decryptWithAd(ad: Uint8Array, ciphertext: Uint8Array): Uint8Array {
        if (!this.k) return ciphertext;
        const out = chacha20poly1305(this.k, nonceBytes(this.n), ad).decrypt(ciphertext);
        this.n++;
        return out;
    }
}

// ---------- SymmetricState ----------

class SymmetricState {
    public h: Uint8Array;
    private ck: Uint8Array;
    private cipher: CipherState;

    constructor() {
        const nameBytes = new TextEncoder().encode(PROTOCOL_NAME);
        if (nameBytes.length <= HASH_LEN) {
            const padded = new Uint8Array(HASH_LEN);
            padded.set(nameBytes, 0);
            this.h = padded;
        } else {
            this.h = hash(nameBytes);
        }
        this.ck = this.h.slice();
        this.cipher = new CipherState();
    }

    mixKey(ikm: Uint8Array): void {
        const [ck, tempK] = hkdf(this.ck, ikm, 2);
        this.ck = ck!;
        this.cipher = new CipherState(tempK!);
    }

    mixHash(data: Uint8Array): void {
        this.h = hashConcat(this.h, data);
    }

    encryptAndHash(plaintext: Uint8Array): Uint8Array {
        const ct = this.cipher.encryptWithAd(this.h, plaintext);
        this.mixHash(ct);
        return ct;
    }

    decryptAndHash(ciphertext: Uint8Array): Uint8Array {
        const pt = this.cipher.decryptWithAd(this.h, ciphertext);
        this.mixHash(ciphertext);
        return pt;
    }

    split(): [CipherState, CipherState] {
        const [k1, k2] = hkdf(this.ck, new Uint8Array(0), 2);
        return [new CipherState(k1!), new CipherState(k2!)];
    }
}

// ---------- HandshakeState (NX, both sides) ----------

export type Role = "initiator" | "responder";

export interface HandshakeResult {
    sendCipher: CipherState;
    recvCipher: CipherState;
    handshakeHash: Uint8Array;
    /** Responder static public key as seen by the initiator (after step 2). */
    remoteStaticPub?: Uint8Array;
    /** Optional payload field carried in message 2 (we use it for the cert). */
    responderPayload?: Uint8Array;
}

export class NoiseNX {
    private sym = new SymmetricState();
    private e: { priv: Uint8Array; pub: Uint8Array } | null = null;
    private re: Uint8Array | null = null;
    private rs: Uint8Array | null = null;

    constructor(
        public readonly role: Role,
        // Responder MUST provide its static keypair. Initiator may omit it.
        private staticKey?: { priv: Uint8Array; pub: Uint8Array },
    ) {
        if (role === "responder" && !staticKey) {
            throw new Error("responder requires a static key");
        }
    }

    /** Initiator -> message 1: e */
    writeMessage1(): Uint8Array {
        if (this.role !== "initiator") throw new Error("writeMessage1: wrong role");
        const ePriv = randomBytes(32);
        const ePub = x25519.getPublicKey(ePriv);
        this.e = { priv: ePriv, pub: ePub };
        this.sym.mixHash(ePub);
        // No payload in NX message 1.
        return ePub;
    }

    /** Responder reads message 1, extracts re. */
    readMessage1(msg: Uint8Array): void {
        if (this.role !== "responder") throw new Error("readMessage1: wrong role");
        if (msg.length < 32) throw new Error("noise msg1 too short");
        this.re = msg.slice(0, 32);
        this.sym.mixHash(this.re);
    }

    /**
     * Responder -> message 2: e, ee, s, es, plus optional payload.
     * Returns the wire bytes (e || enc(s) || enc(payload)).
     */
    writeMessage2(payload: Uint8Array): Uint8Array {
        if (this.role !== "responder") throw new Error("writeMessage2: wrong role");
        if (!this.staticKey || !this.re) throw new Error("noise: state");
        const ePriv = randomBytes(32);
        const ePub = x25519.getPublicKey(ePriv);
        this.e = { priv: ePriv, pub: ePub };
        this.sym.mixHash(ePub);
        // ee
        this.sym.mixKey(dh(ePriv, this.re));
        // s (encrypted)
        const encS = this.sym.encryptAndHash(this.staticKey.pub);
        // es
        this.sym.mixKey(dh(this.staticKey.priv, this.re));
        // payload (encrypted)
        const encPayload = this.sym.encryptAndHash(payload);
        return concat(ePub, encS, encPayload);
    }

    /**
     * Initiator reads message 2 and finalizes the handshake.
     * Returns split cipher states + the responder's static public key + the
     * (decrypted) payload that travelled in the s slot.
     */
    readMessage2(msg: Uint8Array): HandshakeResult {
        if (this.role !== "initiator") throw new Error("readMessage2: wrong role");
        if (!this.e) throw new Error("noise: missing e");
        if (msg.length < 32 + (32 + TAG_LEN)) throw new Error("noise msg2 too short");
        let off = 0;
        const re = msg.slice(off, off + 32); off += 32;
        this.re = re;
        this.sym.mixHash(re);
        // ee
        this.sym.mixKey(dh(this.e.priv, re));
        // decrypt s
        const encS = msg.slice(off, off + 32 + TAG_LEN); off += 32 + TAG_LEN;
        const rs = this.sym.decryptAndHash(encS);
        this.rs = rs;
        // es
        this.sym.mixKey(dh(this.e.priv, rs));
        // decrypt payload
        const encPayload = msg.slice(off);
        const payload = this.sym.decryptAndHash(encPayload);
        const [c1, c2] = this.sym.split();
        // initiator: c1 -> send, c2 -> recv
        return {
            sendCipher: c1,
            recvCipher: c2,
            handshakeHash: this.sym.h,
            remoteStaticPub: rs,
            responderPayload: payload,
        };
    }

    /**
     * Responder finalizes after sending message 2. Returns split ciphers in
     * the responder direction (c1 -> recv, c2 -> send).
     */
    finishResponder(): HandshakeResult {
        if (this.role !== "responder") throw new Error("finishResponder: wrong role");
        const [c1, c2] = this.sym.split();
        return {
            sendCipher: c2,
            recvCipher: c1,
            handshakeHash: this.sym.h,
        };
    }
}

// ---------- transport wrapping ----------
//
// Each plaintext frame is split into <= 65 519-byte segments (so the
// segment + 16-byte AEAD tag fits in 65 535 bytes); each segment becomes a
// length-prefixed (u16 LE) Noise transport message of `ciphertext || tag`.
// The reader peels the same segments back off.
//
// SV2 uses one segment per message in practice; we still support the
// general case so messages above 64 KiB (think large block templates over
// the TP channel) keep working.

export const NOISE_MAX_SEGMENT = 65535;
export const NOISE_MAX_PLAINTEXT = NOISE_MAX_SEGMENT - TAG_LEN;

export class NoiseTransport {
    constructor(
        public readonly send: CipherState,
        public readonly recv: CipherState,
    ) {}

    /** Encrypt a plaintext frame -> wire bytes (one or more segments). */
    encryptFrame(plaintext: Uint8Array): Uint8Array {
        const segments: Uint8Array[] = [];
        let off = 0;
        while (off < plaintext.length) {
            const end = Math.min(off + NOISE_MAX_PLAINTEXT, plaintext.length);
            const ct = this.send.encryptWithAd(new Uint8Array(0), plaintext.slice(off, end));
            const lenPrefix = new Uint8Array(2);
            new DataView(lenPrefix.buffer).setUint16(0, ct.length, true);
            segments.push(lenPrefix, ct);
            off = end;
        }
        // Mark end-of-frame with a zero-length segment so the reader knows
        // the logical frame ends here and not on a 65 519-byte boundary.
        segments.push(Uint8Array.from([0, 0]));
        return concat(...segments);
    }

    /**
     * Try to peel as many complete frames as possible out of `buf`.
     * Returns the decrypted frames and the byte count consumed.
     * Throws on AEAD failure (caller should drop the connection).
     */
    decryptFrames(buf: Uint8Array): { frames: Uint8Array[]; consumed: number } {
        const out: Uint8Array[] = [];
        let off = 0;
        let cur: Uint8Array[] = [];
        while (off + 2 <= buf.length) {
            const segLen = new DataView(buf.buffer, buf.byteOffset + off, 2).getUint16(0, true);
            if (off + 2 + segLen > buf.length) break;
            off += 2;
            if (segLen === 0) {
                // end of frame
                out.push(concat(...cur));
                cur = [];
                continue;
            }
            const segCt = buf.slice(off, off + segLen);
            off += segLen;
            const pt = this.recv.decryptWithAd(new Uint8Array(0), segCt);
            cur.push(pt);
        }
        // If the last partial frame wasn't terminated, rewind so we re-read it
        // when more bytes arrive.
        const pendingStart = pendingFrameStart(buf, out.length);
        return { frames: out, consumed: pendingStart };
    }
}

// Helper to find where the unfinished frame starts (used to set the new
// read-cursor so we don't drop ciphertext mid-frame).
function pendingFrameStart(buf: Uint8Array, completedFrames: number): number {
    let off = 0;
    let frameStart = 0;
    let completed = 0;
    while (off + 2 <= buf.length) {
        const segLen = new DataView(buf.buffer, buf.byteOffset + off, 2).getUint16(0, true);
        if (off + 2 + segLen > buf.length) return frameStart;
        off += 2 + segLen;
        if (segLen === 0) {
            completed++;
            frameStart = off;
            if (completed === completedFrames) return off;
        }
    }
    return frameStart;
}
