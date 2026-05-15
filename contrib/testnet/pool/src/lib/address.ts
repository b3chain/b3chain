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

// --- bech32 → witness program decoding ---------------------------------
// Decodes the address into the witness version + raw witness program.
// Returns null on any structural / checksum failure. This is the same
// algorithm Bitcoin Core uses (BIP173/BIP350); the only B3Chain-specific
// part is the HRP whitelist enforced by parseB3Address().

export type WitnessDecoded = {
    network: AddressInfo["network"];
    witnessVersion: number;        // 0 (P2WPKH/P2WSH) | 1 (P2TR) | ...
    witnessProgram: Uint8Array;    // 20 bytes for P2WPKH, 32 for P2WSH/P2TR
    encoding: "bech32" | "bech32m";
};

function convertBits(
    src: number[],
    fromBits: number,
    toBits: number,
    pad: boolean
): number[] | null {
    let acc = 0;
    let bits = 0;
    const ret: number[] = [];
    const maxv = (1 << toBits) - 1;
    const maxAcc = (1 << (fromBits + toBits - 1)) - 1;
    for (const v of src) {
        if (v < 0 || v >> fromBits !== 0) return null;
        acc = ((acc << fromBits) | v) & maxAcc;
        bits += fromBits;
        while (bits >= toBits) {
            bits -= toBits;
            ret.push((acc >> bits) & maxv);
        }
    }
    if (pad) {
        if (bits > 0) ret.push((acc << (toBits - bits)) & maxv);
    } else if (bits >= fromBits || ((acc << (toBits - bits)) & maxv)) {
        return null;
    }
    return ret;
}

export function decodeWitnessAddress(addr: string): WitnessDecoded | null {
    const info = parseB3Address(addr);
    if (!info) return null;

    const lower = addr.toLowerCase();
    const sepPos = lower.lastIndexOf("1");
    const dataPart = lower.substring(sepPos + 1);

    const data: number[] = [];
    for (const ch of dataPart) {
        const v = REVERSE[ch];
        if (v === undefined) return null;
        data.push(v);
    }
    if (data.length < 7) return null; // 6 checksum + at least 1 program byte

    const witnessVersion = data[0]!;
    if (witnessVersion < 0 || witnessVersion > 16) return null;

    // Enforce the right encoding: bech32 for v0, bech32m for v1+.
    if (witnessVersion === 0 && info.encoding !== "bech32") return null;
    if (witnessVersion >= 1 && info.encoding !== "bech32m") return null;

    const dataNoChecksum = data.slice(1, data.length - 6);
    const program = convertBits(dataNoChecksum, 5, 8, false);
    if (program === null) return null;
    if (program.length < 2 || program.length > 40) return null;
    if (witnessVersion === 0 && program.length !== 20 && program.length !== 32) return null;

    return {
        network: info.network,
        witnessVersion,
        witnessProgram: Uint8Array.from(program),
        encoding: info.encoding,
    };
}

// Returns the full Bitcoin-style scriptPubKey for a B3Chain bech32
// address. For v0 (P2WPKH/P2WSH): 0x00 || pushdata(program). For v1+
// (P2TR + future): OP_<v+0x50> || pushdata(program).
export function addressToScriptPubKey(addr: string): Uint8Array | null {
    const w = decodeWitnessAddress(addr);
    if (!w) return null;
    const opVersion = w.witnessVersion === 0 ? 0x00 : 0x50 + w.witnessVersion;
    const out = new Uint8Array(2 + w.witnessProgram.length);
    out[0] = opVersion;
    out[1] = w.witnessProgram.length;
    out.set(w.witnessProgram, 2);
    return out;
}
