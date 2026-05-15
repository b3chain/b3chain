// Stratum V2 SignedCertificate — used to attest the pool's X25519 static
// key with the long-lived Ed25519 authority key.
//
// Wire layout (matches the SRI implementation):
//   u16 LE   version             (currently 0)
//   u32 LE   valid_from          (unix seconds)
//   u32 LE   not_valid_after     (unix seconds)
//   PUBKEY   public_key          (32 bytes — the X25519 static key)
//   SIG      signature           (64 bytes — Ed25519 over the preceding 42 bytes)
//
// Total length: 106 bytes. The signature covers the version || validity
// window || certified public key, exactly as ordered above.

import { ReadBuf, WriteBuf } from "./types";
import { ed25519Sign, ed25519Verify, type Ed25519Key } from "./keys";
import * as fs from "fs";

export const SV2_CERT_VERSION = 0;
export const SV2_CERT_LEN = 2 + 4 + 4 + 32 + 64;
export const SV2_CERT_DEFAULT_VALIDITY_S = 90 * 24 * 60 * 60; // 90 days

export interface Sv2Certificate {
    version: number;
    validFrom: number;
    notValidAfter: number;
    publicKey: Uint8Array; // X25519 static pub
    signature: Uint8Array; // Ed25519
}

function signatureMessage(version: number, validFrom: number, notValidAfter: number, pub: Uint8Array): Uint8Array {
    const w = new WriteBuf();
    w.u16(version).u32(validFrom).u32(notValidAfter).pubkey(pub);
    return w.finish();
}

export function signCertificate(
    authority: Ed25519Key,
    staticPub: Uint8Array,
    validFrom: number,
    notValidAfter: number,
): Sv2Certificate {
    const msg = signatureMessage(SV2_CERT_VERSION, validFrom, notValidAfter, staticPub);
    const sig = ed25519Sign(authority.priv, msg);
    return { version: SV2_CERT_VERSION, validFrom, notValidAfter, publicKey: staticPub, signature: sig };
}

export function encodeCertificate(c: Sv2Certificate): Uint8Array {
    const w = new WriteBuf();
    w.u16(c.version).u32(c.validFrom).u32(c.notValidAfter).pubkey(c.publicKey).signature(c.signature);
    return w.finish();
}

export function decodeCertificate(buf: Uint8Array): Sv2Certificate {
    if (buf.length < SV2_CERT_LEN) throw new Error(`SV2 cert too short: ${buf.length}`);
    const r = new ReadBuf(buf);
    const version = r.u16();
    const validFrom = r.u32();
    const notValidAfter = r.u32();
    const publicKey = r.pubkey();
    const signature = r.signature();
    return { version, validFrom, notValidAfter, publicKey, signature };
}

export interface CertVerifyResult {
    ok: boolean;
    reason?: string;
}

export function verifyCertificate(
    cert: Sv2Certificate,
    authorityPub: Uint8Array,
    nowSeconds = Math.floor(Date.now() / 1000),
): CertVerifyResult {
    if (cert.version !== SV2_CERT_VERSION) return { ok: false, reason: `unknown cert version ${cert.version}` };
    if (nowSeconds < cert.validFrom) return { ok: false, reason: "cert not yet valid" };
    if (nowSeconds >= cert.notValidAfter) return { ok: false, reason: "cert expired" };
    const msg = signatureMessage(cert.version, cert.validFrom, cert.notValidAfter, cert.publicKey);
    if (!ed25519Verify(authorityPub, msg, cert.signature)) return { ok: false, reason: "bad signature" };
    return { ok: true };
}

export function loadOrIssueCertificate(
    path: string,
    authority: Ed25519Key,
    staticPub: Uint8Array,
    validitySeconds = SV2_CERT_DEFAULT_VALIDITY_S,
    nowSeconds = Math.floor(Date.now() / 1000),
): Sv2Certificate {
    if (fs.existsSync(path)) {
        const buf = fs.readFileSync(path);
        const cert = decodeCertificate(new Uint8Array(buf));
        // Reissue if it's expired, expires within 7 days, or the embedded
        // static-pub doesn't match the loaded static key (e.g. operator
        // rotated keys).
        const sevenDays = 7 * 24 * 60 * 60;
        const stillFresh = cert.notValidAfter > nowSeconds + sevenDays;
        const samePub = Buffer.compare(cert.publicKey, staticPub) === 0;
        const verified = verifyCertificate(cert, authority.pub, nowSeconds).ok;
        if (stillFresh && samePub && verified) return cert;
    }
    const cert = signCertificate(authority, staticPub, nowSeconds, nowSeconds + validitySeconds);
    fs.writeFileSync(path, encodeCertificate(cert), { mode: 0o644 });
    return cert;
}
