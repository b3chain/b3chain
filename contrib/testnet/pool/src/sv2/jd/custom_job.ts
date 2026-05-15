// Validate that a miner-declared coinbase pays the pool's payout address
// for the agreed value, then convert the DeclareMiningJob into a
// SetCustomMiningJob frame the pool can deliver over a Mining channel.
//
// The miner's coinbase is reconstructed as
//   coinbase = coinbasePrefix || extranonce_prefix || extranonce
//              || coinbaseSuffix
// We don't see the per-share extranonce here; we only need to confirm
// that the *outputs* of the coinbase pay the pool. Outputs live entirely
// in `coinbaseSuffix` (everything after the scriptSig), so we parse it
// as a plain Bitcoin tx tail and assert at least one TxOut sends value
// to the pool's expected scriptPubKey.

import { config } from "../../config";
import { addressToScriptPubKey } from "../../lib/address";
import { ReadBuf } from "../lib/types";

export interface CoinbaseValidationResult {
    ok: boolean;
    reason?: string;
    poolValueSat?: bigint;
}

/**
 * Parse a coinbase tx tail (everything from sequence(4) onward, i.e. the
 * portion that DeclareMiningJob.coinbaseSuffix carries) and verify the
 * pool's scriptPubKey gets at least `minValue` satoshis.
 */
export function validateDeclaredCoinbase(
    coinbaseSuffix: Uint8Array,
    minValue: bigint,
): CoinbaseValidationResult {
    const expectedSpk = addressToScriptPubKey(config.rpc.payoutAddress);
    if (!expectedSpk) return { ok: false, reason: "pool-payout-address-invalid" };

    // coinbaseSuffix layout:
    //   sequence(4) || out_count(varInt) || outs[..] || locktime(4)
    const r = new ReadBuf(coinbaseSuffix);
    try {
        r.bytesRaw(4); // sequence
        const outCount = readVarInt(r);
        let total = 0n;
        let paidPool = 0n;
        for (let i = 0; i < outCount; i++) {
            const value = r.u64();
            const spkLen = readVarInt(r);
            const spk = r.bytesRaw(spkLen);
            total += value;
            if (bytesEqual(spk, expectedSpk)) paidPool += value;
        }
        // 4 trailing bytes for locktime; tolerate trailing junk.
        if (paidPool < minValue) {
            return {
                ok: false,
                reason: "coinbase-does-not-pay-pool",
                poolValueSat: paidPool,
            };
        }
        return { ok: true, poolValueSat: paidPool };
    } catch (e) {
        return { ok: false, reason: `coinbase-parse-error: ${(e as Error).message}` };
    }
}

function readVarInt(r: ReadBuf): number {
    const first = r.u8();
    if (first < 0xfd) return first;
    if (first === 0xfd) return r.u16();
    if (first === 0xfe) return r.u32();
    // 0xff -> u64
    const big = r.u64();
    if (big > BigInt(Number.MAX_SAFE_INTEGER)) {
        throw new Error("varInt larger than MAX_SAFE_INTEGER");
    }
    return Number(big);
}

function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
}
