import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, sign } from "crypto";
import { verifyP256Digest } from "../src/lib/p256";
import { shareDigest } from "../src/lib/share-digest";

function keypair() {
    const { publicKey, privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
    const jwk = publicKey.export({ format: "jwk" }) as { x: string; y: string };
    const pub = Buffer.concat([
        Buffer.from(jwk.x, "base64url"),
        Buffer.from(jwk.y, "base64url"),
    ]).toString("hex");
    return { privateKey, pub };
}

function signDigest(privateKey: ReturnType<typeof generateKeyPairSync>["privateKey"], digest: Buffer): string {
    return sign(null, digest, { key: privateKey, dsaEncoding: "ieee-p1363" }).toString("hex");
}

test("p256 verify accepts the digest and rejects a different one", () => {
    const { privateKey, pub } = keypair();
    const digest = createHash("sha256").update("challenge").digest();
    const sig = signDigest(privateKey, digest);
    assert.equal(verifyP256Digest(pub, digest, sig), true);
    const other = Buffer.from(digest);
    other[0] ^= 0xff;
    assert.equal(verifyP256Digest(pub, other, sig), false);
});

test("share digest binds the nonce", () => {
    const { privateKey, pub } = keypair();
    const digest = shareDigest("0000001", "00000000", 0x60ffffff, 0x10);
    const sig = signDigest(privateKey, digest);
    assert.equal(verifyP256Digest(pub, digest, sig), true);
    assert.equal(verifyP256Digest(pub, shareDigest("0000001", "00000000", 0x60ffffff, 0x11), sig), false);
});
