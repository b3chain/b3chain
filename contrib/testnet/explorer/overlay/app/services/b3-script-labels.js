"use strict";

// Labels for binary script pushes the block page otherwise prints as UTF-8.
// Coinbase height follows BIP34 (CScriptNum). The witness commitment is the
// BIP141 marker aa21a9ed plus a 32-byte hash.

function readBip34Height(buf) {
	if (!buf || buf.length === 0) return null;
	const op = buf[0];
	if (op === 0x00) return { height: 0, rest: buf.subarray(1) };
	if (op >= 0x51 && op <= 0x60) return { height: op - 0x50, rest: buf.subarray(1) };
	if (op < 1 || op > 5 || buf.length < 1 + op) return null;

	const pushed = buf.subarray(1, 1 + op);
	if (pushed[pushed.length - 1] & 0x80) return null;
	if (pushed.length > 1 && pushed[pushed.length - 1] === 0x00 && (pushed[pushed.length - 2] & 0x80) === 0) {
		return null;
	}

	let height = 0;
	let mul = 1;
	for (let i = 0; i < pushed.length; i++) {
		height += pushed[i] * mul;
		mul *= 256;
	}
	if (!Number.isSafeInteger(height)) return null;
	return { height, rest: buf.subarray(1 + op) };
}

function longestAsciiTag(buf) {
	let best = "";
	let cur = "";
	for (const b of buf) {
		if (b >= 0x20 && b <= 0x7e) {
			cur += String.fromCharCode(b);
		} else {
			if (cur.length > best.length) best = cur;
			cur = "";
		}
	}
	if (cur.length > best.length) best = cur;
	return best.length >= 4 ? best : "";
}

function coinbaseScriptSummary(hex, blockHeight) {
	const expected = Number(blockHeight);
	if (!Number.isInteger(expected) || expected < 0) return null;
	if (typeof hex !== "string") return null;
	const clean = hex.trim().toLowerCase();
	if (clean.length < 2 || clean.length % 2 !== 0 || !/^[0-9a-f]+$/.test(clean)) return null;

	const parsed = readBip34Height(Buffer.from(clean, "hex"));
	if (!parsed || parsed.height !== expected) return null;
	return { height: parsed.height, tag: longestAsciiTag(parsed.rest) };
}

function witnessCommitmentHash(payloadHex) {
	if (typeof payloadHex !== "string") return null;
	const hex = payloadHex.trim().toLowerCase().replace(/\s+/g, "");
	if (!hex.startsWith("aa21a9ed")) return null;
	const hash = hex.slice(8, 72);
	if (!/^[0-9a-f]{64}$/.test(hash)) return null;
	return hash;
}

module.exports = {
	coinbaseScriptSummary,
	witnessCommitmentHash,
};
