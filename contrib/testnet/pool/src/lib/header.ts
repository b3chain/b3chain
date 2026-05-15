// 80-byte block header serialization matches Bitcoin's exactly:
//   int32 version | uint256 prevHash (LE) | uint256 merkleRoot (LE)
//   | uint32 ntime | uint32 bits | uint32 nonce
//
// All "hex" inputs follow Stratum/Bitcoin convention where
// uint256s are sent BIG-ENDIAN ("display") and must be reversed
// to little-endian on the wire.

import { sha256 } from "@noble/hashes/sha2";

export function hexToBytes(hex: string): Uint8Array {
    const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
    if (clean.length % 2 !== 0) throw new Error("odd-length hex");
    const out = new Uint8Array(clean.length / 2);
    for (let i = 0; i < out.length; i++) {
        out[i] = parseInt(clean.substr(i * 2, 2), 16);
    }
    return out;
}

export function bytesToHex(bytes: Uint8Array): string {
    const hex: string[] = [];
    for (const b of bytes) hex.push(b.toString(16).padStart(2, "0"));
    return hex.join("");
}

export function reverseBytes(b: Uint8Array): Uint8Array {
    const out = new Uint8Array(b.length);
    for (let i = 0; i < b.length; i++) out[i] = b[b.length - 1 - i]!;
    return out;
}

export function uint32LE(n: number): Uint8Array {
    const out = new Uint8Array(4);
    new DataView(out.buffer).setUint32(0, n >>> 0, true);
    return out;
}

export function int32LE(n: number): Uint8Array {
    const out = new Uint8Array(4);
    new DataView(out.buffer).setInt32(0, n | 0, true);
    return out;
}

export function uint32FromLEHex(h: string): number {
    return new DataView(hexToBytes(h).buffer).getUint32(0, true);
}

export interface HeaderInput {
    version: number;
    prevHashHexBE: string;
    merkleRootHexBE: string;
    ntime: number;
    bits: number;
    nonce: number;
}

export function serializeHeader(h: HeaderInput): Uint8Array {
    const prev = reverseBytes(hexToBytes(h.prevHashHexBE));
    const merkle = reverseBytes(hexToBytes(h.merkleRootHexBE));
    if (prev.length !== 32) throw new Error("prevHash must be 32 bytes");
    if (merkle.length !== 32) throw new Error("merkleRoot must be 32 bytes");

    const out = new Uint8Array(80);
    out.set(int32LE(h.version), 0);
    out.set(prev, 4);
    out.set(merkle, 36);
    out.set(uint32LE(h.ntime), 68);
    out.set(uint32LE(h.bits), 72);
    out.set(uint32LE(h.nonce), 76);
    return out;
}

export function doubleSha256(b: Uint8Array): Uint8Array {
    return sha256(sha256(b));
}

// Compute a coinbase txid (SHA-256d of full coinbase transaction bytes).
export function coinbaseTxId(coinbase: Uint8Array): Uint8Array {
    return doubleSha256(coinbase);
}

// Reduce coinbase txid + merkleBranches into the block header's merkle root.
// `branches` are SHA-256d hex strings (BIG-endian); they are interpreted as
// little-endian byte sequences when concatenated, matching getblocktemplate
// and standard Stratum semantics.
export function computeMerkleRoot(coinbaseTxIdLE: Uint8Array, branchesHexBE: string[]): Uint8Array {
    let cur = coinbaseTxIdLE;
    for (const br of branchesHexBE) {
        const brLE = reverseBytes(hexToBytes(br));
        const combined = new Uint8Array(64);
        combined.set(cur, 0);
        combined.set(brLE, 32);
        cur = doubleSha256(combined);
    }
    return cur;
}

export function varInt(n: number): Uint8Array {
    if (n < 0xfd) return new Uint8Array([n]);
    if (n <= 0xffff) {
        const out = new Uint8Array(3);
        out[0] = 0xfd;
        new DataView(out.buffer).setUint16(1, n, true);
        return out;
    }
    if (n <= 0xffffffff) {
        const out = new Uint8Array(5);
        out[0] = 0xfe;
        new DataView(out.buffer).setUint32(1, n, true);
        return out;
    }
    const out = new Uint8Array(9);
    out[0] = 0xff;
    new DataView(out.buffer).setBigUint64(1, BigInt(n), true);
    return out;
}

export function concatBytes(...arrs: Uint8Array[]): Uint8Array {
    let total = 0;
    for (const a of arrs) total += a.length;
    const out = new Uint8Array(total);
    let off = 0;
    for (const a of arrs) {
        out.set(a, off);
        off += a.length;
    }
    return out;
}
