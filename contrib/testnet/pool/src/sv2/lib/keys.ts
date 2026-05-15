// Stratum V2 key material: Ed25519 authority + X25519 static.
//
// The authority key is the long-lived root that signs every pool-static
// certificate. Operators publish its public bytes (hex / bech32m) so
// miners can pin it. The static key is the X25519 keypair the pool
// presents during the Noise NX handshake. We rotate the static key by
// re-signing a fresh cert; the authority key stays stable across rotations.

import * as fs from "fs";
import { ed25519, x25519 } from "@noble/curves/ed25519";
import { randomBytes } from "node:crypto";

export interface Ed25519Key {
    priv: Uint8Array; // 32 bytes
    pub: Uint8Array;  // 32 bytes
}

export interface X25519Key {
    priv: Uint8Array; // 32 bytes
    pub: Uint8Array;  // 32 bytes
}

export function generateAuthorityKey(): Ed25519Key {
    const priv = ed25519.utils.randomPrivateKey();
    const pub = ed25519.getPublicKey(priv);
    return { priv, pub };
}

export function generateStaticKey(): X25519Key {
    const priv = randomBytes(32);
    const pub = x25519.getPublicKey(priv);
    return { priv, pub };
}

// On-disk format: 64 raw bytes = priv (32) || pub (32). Mode 0600.
function writeKeyFile(path: string, k: { priv: Uint8Array; pub: Uint8Array }): void {
    if (k.priv.length !== 32 || k.pub.length !== 32) throw new Error("key must be 32+32 bytes");
    const buf = new Uint8Array(64);
    buf.set(k.priv, 0);
    buf.set(k.pub, 32);
    fs.writeFileSync(path, buf, { mode: 0o600 });
}

function readKeyFile(path: string): { priv: Uint8Array; pub: Uint8Array } {
    const buf = fs.readFileSync(path);
    if (buf.length !== 64) throw new Error(`${path}: expected 64 bytes, got ${buf.length}`);
    return { priv: new Uint8Array(buf.subarray(0, 32)), pub: new Uint8Array(buf.subarray(32, 64)) };
}

export function loadOrCreateAuthorityKey(path: string): Ed25519Key {
    if (fs.existsSync(path)) {
        const k = readKeyFile(path);
        // Re-derive pub to defend against on-disk tampering.
        const pub = ed25519.getPublicKey(k.priv);
        if (Buffer.compare(pub, k.pub) !== 0) {
            throw new Error(`${path}: priv/pub mismatch`);
        }
        return { priv: k.priv, pub };
    }
    const k = generateAuthorityKey();
    writeKeyFile(path, k);
    return k;
}

export function loadOrCreateStaticKey(path: string): X25519Key {
    if (fs.existsSync(path)) {
        const k = readKeyFile(path);
        const pub = x25519.getPublicKey(k.priv);
        if (Buffer.compare(pub, k.pub) !== 0) {
            throw new Error(`${path}: priv/pub mismatch`);
        }
        return { priv: k.priv, pub };
    }
    const k = generateStaticKey();
    writeKeyFile(path, k);
    return k;
}

export function ed25519Sign(priv: Uint8Array, msg: Uint8Array): Uint8Array {
    return ed25519.sign(msg, priv);
}

export function ed25519Verify(pub: Uint8Array, msg: Uint8Array, sig: Uint8Array): boolean {
    try { return ed25519.verify(sig, msg, pub); }
    catch { return false; }
}
