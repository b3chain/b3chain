import { createPublicKey, verify, type KeyObject } from "crypto";

/** Verify an ATECC R||S signature over a 32-byte digest. The digest is not hashed again. */
export function verifyP256Digest(pubHex: string, digest: Buffer, sigHex: string): boolean {
    if (!/^[0-9a-f]{128}$/.test(pubHex) || !/^[0-9a-f]{128}$/.test(sigHex) || digest.length !== 32) {
        return false;
    }
    try {
        const key = publicKeyFromXY(pubHex);
        return verify(null, digest, { key, dsaEncoding: "ieee-p1363" }, Buffer.from(sigHex, "hex"));
    } catch {
        return false;
    }
}

export function publicKeyFromXY(pubHex: string): KeyObject {
    const raw = Buffer.from(pubHex, "hex");
    return createPublicKey({
        key: {
            kty: "EC",
            crv: "P-256",
            x: raw.subarray(0, 32).toString("base64url"),
            y: raw.subarray(32, 64).toString("base64url"),
        },
        format: "jwk",
    });
}
