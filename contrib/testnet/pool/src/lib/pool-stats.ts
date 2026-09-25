// Share-based hashrate. One share at difficulty D represents D * 2^32 hashes
// on average. An empty or non-positive window is 0 H/s.

export function shareHashrateHps(totalDiff: number, windowSeconds: number): number {
    if (!Number.isFinite(totalDiff) || totalDiff <= 0) return 0;
    if (!Number.isFinite(windowSeconds) || windowSeconds <= 0) return 0;
    return (totalDiff * 4_294_967_296) / windowSeconds;
}

export const SHARE_HASHRATE_WINDOW_SECONDS = 300;
