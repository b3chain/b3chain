// Compact-bits / target / difficulty conversion for B3Chain.
//
//   bits       <-> target (256-bit big int)
//   shareDiff  <-> shareTarget = (DIFF1_TARGET / shareDiff)
//
// DIFF1_TARGET is the standard "diff 1" target used by Bitcoin-derived
// pools: 0x00000000ffff_0000_0000_0000_0000_0000_0000_0000_0000_0000_0000_0000.

export const MAX_UINT256 =
    (1n << 256n) - 1n;

// "Pool diff 1" target — same as Bitcoin/Litecoin pools. Share at diff D has
// hash <= POOL_DIFF1_TARGET / D.
export const POOL_DIFF1_TARGET =
    0x00000000ffff0000000000000000000000000000000000000000000000000000n;

export function targetFromBits(bits: number): bigint {
    const exp = (bits >> 24) & 0xff;
    let mant = BigInt(bits & 0x007fffff);
    if (exp <= 3) {
        mant >>= BigInt(8 * (3 - exp));
    } else {
        mant <<= BigInt(8 * (exp - 3));
    }
    return mant;
}

export function bigIntFromBytesLE(b: Uint8Array): bigint {
    let n = 0n;
    for (let i = b.length - 1; i >= 0; i--) {
        n = (n << 8n) | BigInt(b[i]!);
    }
    return n;
}

export function bigIntFromBytesBE(b: Uint8Array): bigint {
    let n = 0n;
    for (const x of b) n = (n << 8n) | BigInt(x);
    return n;
}

export function targetFromShareDifficulty(shareDiff: number): bigint {
    if (shareDiff <= 0) throw new Error("share diff must be > 0");
    // shareTarget = floor(POOL_DIFF1_TARGET / shareDiff)
    // Use string conversion to keep precision for fractional difficulties.
    const scale = 1_000_000n;
    const scaledDiff = BigInt(Math.floor(shareDiff * Number(scale)));
    if (scaledDiff === 0n) return MAX_UINT256;
    return (POOL_DIFF1_TARGET * scale) / scaledDiff;
}

export function shareDifficultyFromTarget(target: bigint): number {
    if (target <= 0n) return Number.MAX_SAFE_INTEGER;
    const scale = 1_000_000n;
    return Number((POOL_DIFF1_TARGET * scale) / target) / Number(scale);
}

export function networkDifficultyFromBits(bits: number): number {
    const target = targetFromBits(bits);
    if (target <= 0n) return Number.MAX_SAFE_INTEGER;
    const scale = 10_000_000n;
    return Number((POOL_DIFF1_TARGET * scale) / target) / Number(scale);
}

// Hashrate (H/s) estimated from total weighted-share difficulty over a window.
export function hashrateFromShares(totalDiff: number, windowSeconds: number): number {
    if (windowSeconds <= 0) return 0;
    // Each share at diff D == on average (D * 2^32) hashes.
    return (totalDiff * 4_294_967_296) / windowSeconds;
}
