import { test } from "node:test";
import assert from "node:assert/strict";
import { parseB3Address, isValidB3AddressForNetwork } from "../src/lib/address";
import { bech32, bech32m } from "@scure/base";

// We mint synthetic but structurally valid addresses for each HRP using the
// same bech32m library b3chaind itself uses, then verify our parser accepts
// them; gibberish & wrong-HRP cases are all rejected.

function mintBech32m(hrp: string, witnessVersion = 1): string {
    const program = new Uint8Array(32);
    for (let i = 0; i < 32; i++) program[i] = (i * 7 + 3) & 0xff;
    const data = [witnessVersion, ...bech32m.toWords(program)];
    return bech32m.encode(hrp, data, 200);
}

test("accepts valid mainnet bech32m address", () => {
    const a = mintBech32m("b3");
    const info = parseB3Address(a);
    assert.ok(info, "expected to parse");
    assert.equal(info?.network, "mainnet");
    assert.equal(info?.encoding, "bech32m");
    assert.ok(isValidB3AddressForNetwork(a, "mainnet"));
    assert.ok(!isValidB3AddressForNetwork(a, "testnet"));
});

test("accepts valid testnet (tb3) bech32m address", () => {
    const a = mintBech32m("tb3");
    assert.ok(isValidB3AddressForNetwork(a, "testnet"));
    assert.ok(!isValidB3AddressForNetwork(a, "mainnet"));
    assert.ok(!isValidB3AddressForNetwork(a, "regtest"));
});

test("accepts valid regtest (b3rt) bech32m address", () => {
    const a = mintBech32m("b3rt");
    assert.ok(isValidB3AddressForNetwork(a, "regtest"));
});

test("rejects non-b3 HRPs", () => {
    assert.equal(parseB3Address(mintBech32m("bc")), null, "bc (mainnet bitcoin) should reject");
    assert.equal(parseB3Address(mintBech32m("tb")), null, "tb (testnet bitcoin) should reject");
    assert.equal(parseB3Address(mintBech32m("ltc")), null, "ltc should reject");
});

test("rejects garbage", () => {
    assert.equal(parseB3Address(""), null);
    assert.equal(parseB3Address("not-an-address"), null);
    assert.equal(parseB3Address("b3"), null);
    assert.equal(parseB3Address("b31abcdef"), null, "checksum mismatch");
});

test("rejects mixed-case", () => {
    const a = mintBech32m("b3");
    const mixed = a.slice(0, 5) + a[5]!.toUpperCase() + a.slice(6);
    assert.equal(parseB3Address(mixed), null);
});
