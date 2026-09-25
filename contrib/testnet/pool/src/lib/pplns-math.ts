/** Read-only PPLNS amount for one user. Does not write the ledger. */
export function userCreditFromShares(
    shares: { userId: number; diff: number }[],
    userId: number,
    reward: number,
    feePercent: number
): number {
    if (!Number.isFinite(reward) || reward <= 0) return 0;
    let sum = 0;
    let mine = 0;
    for (const s of shares) {
        if (!Number.isFinite(s.diff) || s.diff <= 0) continue;
        sum += s.diff;
        if (s.userId === userId) mine += s.diff;
    }
    if (sum <= 0 || mine <= 0) return 0;
    const distributable = reward - reward * (feePercent / 100);
    const amount = (mine / sum) * distributable;
    if (!Number.isFinite(amount) || amount <= 0) return 0;
    return Number(amount.toFixed(8));
}
