// B3Chain address validator.
//
// The supported HRPs are:
//   b3   — mainnet  (Bech32 / Bech32m segwit-style)
//   tb3  — public testnet
//   b3rt — regtest
//
// We perform Bech32/Bech32m structural validation only (HRP + checksum +
// length); we do not enforce script-version / program-length policy here
// because that is the job of `b3chaind validateaddress`. Operators should
// re-validate against the daemon before persisting to user accounts.

const CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";

const REVERSE: Record<string, number> = {};
for (let i = 0; i < CHARSET.length; i++) REVERSE[CHARSET[i]!] = i;

const ENCODING_BECH32 = 1;
const ENCODING_BECH32M = 0x2bc830a3;

function polymod(values: number[]): number {
    const GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
    let chk = 1;
    for (const v of values) {
        const top = chk >> 25;
        chk = ((chk & 0x1ffffff) << 5) ^ v;
        for (let i = 0; i < 5; i++) {
            if ((top >> i) & 1) chk ^= GEN[i]!;
        }
    }
    return chk;
}

function hrpExpand(hrp: string): number[] {
    const out: number[] = [];
    for (let i = 0; i < hrp.length; i++) out.push(hrp.charCodeAt(i) >> 5);
    out.push(0);
    for (let i = 0; i < hrp.length; i++) out.push(hrp.charCodeAt(i) & 31);
    return out;
}

function verifyChecksum(hrp: string, data: number[]): number | null {
    const v = polymod(hrpExpand(hrp).concat(data));
    if (v === ENCODING_BECH32) return ENCODING_BECH32;
    if (v === ENCODING_BECH32M) return ENCODING_BECH32M;
    return null;
}

export type AddressInfo = {
    network: "mainnet" | "testnet" | "regtest";
    hrp: string;
    encoding: "bech32" | "bech32m";
};

export function parseB3Address(addr: string): AddressInfo | null {
    if (typeof addr !== "string") return null;
    const lower = addr.toLowerCase();
    const upper = addr.toUpperCase();
    if (addr !== lower && addr !== upper) return null;
    const a = lower;
    if (a.length < 8 || a.length > 90) return null;

    const sepPos = a.lastIndexOf("1");
    if (sepPos < 1 || sepPos + 7 > a.length) return null;

    const hrp = a.substring(0, sepPos);
    const dataPart = a.substring(sepPos + 1);
    let network: AddressInfo["network"];
    if (hrp === "b3") network = "mainnet";
    else if (hrp === "tb3") network = "testnet";
    else if (hrp === "b3rt") network = "regtest";
    else return null;

    const data: number[] = [];
    for (const ch of dataPart) {
        const v = REVERSE[ch];
        if (v === undefined) return null;
        data.push(v);
    }
    const enc = verifyChecksum(hrp, data);
    if (enc === null) return null;
    return {
        network,
        hrp,
        encoding: enc === ENCODING_BECH32M ? "bech32m" : "bech32",
    };
}

export function isValidB3AddressForNetwork(
    addr: string,
    network: "mainnet" | "testnet" | "regtest"
): boolean {
    const info = parseB3Address(addr);
    return info !== null && info.network === network;
}
