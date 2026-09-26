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

/** Smallest share difficulty the 1e6 fixed-point conversion can represent. */
export const MIN_SHARE_DIFFICULTY = 0.000001;

export function targetFromShareDifficulty(shareDiff: number): bigint {
    if (!Number.isFinite(shareDiff) || shareDiff <= 0) {
        throw new Error("share diff must be a finite number > 0");
    }
    if (shareDiff < MIN_SHARE_DIFFICULTY) {
        throw new Error(
            `share diff ${shareDiff} is below ${MIN_SHARE_DIFFICULTY}; ` +
            "the 1e6 scale would collapse it to an all-accepting target"
        );
    }
    // shareTarget = floor(POOL_DIFF1_TARGET * scale / round(shareDiff * scale))
    const scale = 1_000_000n;
    const scaledDiff = BigInt(Math.round(shareDiff * Number(scale)));
    if (scaledDiff <= 0n) {
        throw new Error(`share diff ${shareDiff} failed fixed-point conversion`);
    }
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

/** Share difficulty actually given to a miner: never harder than the job network target. */
export function assignedShareDifficulty(configured: number, network: number | null): number {
    if (network == null || !Number.isFinite(network) || network <= 0) return configured;
    if (!Number.isFinite(configured) || configured <= 0) return network;
    return Math.min(configured, network);
}

export function formatDifficulty(d: number): string {
    if (!Number.isFinite(d)) return "unavailable";
    if (d >= 100) return String(Math.round(d));
    const text = d.toPrecision(6);
    return text.replace(/\.?0+$/, "");
}

// Hashrate (H/s) estimated from total weighted-share difficulty over a window.
export function hashrateFromShares(totalDiff: number, windowSeconds: number): number {
    if (windowSeconds <= 0) return 0;
    // Each share at diff D == on average (D * 2^32) hashes.
    return (totalDiff * 4_294_967_296) / windowSeconds;
}
