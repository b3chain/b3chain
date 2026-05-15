// Unit tests for the Noise NX state machine + transport, and for the
// SignedCertificate envelope.

import test from "node:test";
import * as assert from "node:assert/strict";
import { NoiseNX, NoiseTransport } from "../src/sv2/lib/noise";
import {
    generateAuthorityKey, generateStaticKey,
    ed25519Sign, ed25519Verify,
} from "../src/sv2/lib/keys";
import {
    signCertificate, encodeCertificate, decodeCertificate,
    verifyCertificate, SV2_CERT_LEN,
} from "../src/sv2/lib/cert";

function runHandshake(payload: Uint8Array) {
    const stat = generateStaticKey();
    const responder = new NoiseNX("responder", stat);
    const initiator = new NoiseNX("initiator");
    const m1 = initiator.writeMessage1();
    responder.readMessage1(m1);
    const m2 = responder.writeMessage2(payload);
    const initFinal = initiator.readMessage2(m2);
    const respFinal = responder.finishResponder();
    return { stat, initFinal, respFinal };
}

test("Noise NX completes and yields matching transcripts + remote static", () => {
    const cert = new TextEncoder().encode("hello cert payload");
    const { stat, initFinal, respFinal } = runHandshake(cert);
    assert.deepEqual(initFinal.handshakeHash, respFinal.handshakeHash);
    assert.deepEqual(initFinal.remoteStaticPub, stat.pub);
    assert.deepEqual(initFinal.responderPayload, cert);
});

test("Noise NX bidirectional transport encrypt/decrypt", () => {
    const { initFinal, respFinal } = runHandshake(new Uint8Array(0));
    const initTransport = new NoiseTransport(initFinal.sendCipher, initFinal.recvCipher);
    const respTransport = new NoiseTransport(respFinal.sendCipher, respFinal.recvCipher);

    const m1 = new TextEncoder().encode("hello pool, this is a miner");
    const ct = initTransport.encryptFrame(m1);
    const got = respTransport.decryptFrames(ct);
    assert.equal(got.frames.length, 1);
    assert.deepEqual(got.frames[0], m1);

    const m2 = new TextEncoder().encode("welcome miner");
    const ct2 = respTransport.encryptFrame(m2);
    const got2 = initTransport.decryptFrames(ct2);
    assert.equal(got2.frames.length, 1);
    assert.deepEqual(got2.frames[0], m2);
});

test("Noise NX rejects tampered ciphertext", () => {
    const { initFinal, respFinal } = runHandshake(new Uint8Array(0));
    const initTransport = new NoiseTransport(initFinal.sendCipher, initFinal.recvCipher);
    const respTransport = new NoiseTransport(respFinal.sendCipher, respFinal.recvCipher);
    const ct = initTransport.encryptFrame(new TextEncoder().encode("aaa"));
    // Flip a byte after the 2-byte length prefix.
    ct[3] ^= 0x01;
    assert.throws(() => respTransport.decryptFrames(ct));
});

test("SignedCertificate signs + verifies, length is 106", () => {
    const auth = generateAuthorityKey();
    const stat = generateStaticKey();
    const now = Math.floor(Date.now() / 1000);
    const cert = signCertificate(auth, stat.pub, now, now + 7 * 24 * 60 * 60);
    const enc = encodeCertificate(cert);
    assert.equal(enc.length, SV2_CERT_LEN);
    const dec = decodeCertificate(enc);
    assert.deepEqual(dec.publicKey, stat.pub);
    assert.equal(verifyCertificate(dec, auth.pub, now + 60).ok, true);
});

test("SignedCertificate rejects expired / wrong-authority / bad sig", () => {
    const auth = generateAuthorityKey();
    const auth2 = generateAuthorityKey();
    const stat = generateStaticKey();
    const now = 1_700_000_000;
    const cert = signCertificate(auth, stat.pub, now, now + 100);

    // expired
    assert.equal(verifyCertificate(cert, auth.pub, now + 1000).ok, false);
    // wrong authority
    assert.equal(verifyCertificate(cert, auth2.pub, now + 50).ok, false);
    // tampered signature
    const tampered = { ...cert, signature: new Uint8Array(cert.signature) };
    tampered.signature[0] ^= 0xff;
    assert.equal(verifyCertificate(tampered, auth.pub, now + 50).ok, false);
});

test("Ed25519 sign + verify smoke", () => {
    const k = generateAuthorityKey();
    const msg = new TextEncoder().encode("the network is the computer");
    const sig = ed25519Sign(k.priv, msg);
    assert.equal(ed25519Verify(k.pub, msg, sig), true);
    msg[0] ^= 0x01;
    assert.equal(ed25519Verify(k.pub, msg, sig), false);
});
