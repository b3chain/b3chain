// Pay Per Last N Shares — credit a confirmed block's reward to users in
// proportion to their share-difficulty contribution to the most recent
// N shares submitted at or before the block's `found_at` timestamp.

import { query, tx } from "../lib/db";
import { config } from "../config";
import { Logger } from "../lib/logger";

export async function creditPplns(blockId: number, log: Logger): Promise<void> {
    const blocks = await query<{
        id: string;
        reward_b3c: string;
        pool_fee_b3c: string;
        found_at: string;
        pplns_credited: boolean;
    }>(
        `SELECT id, reward_b3c, pool_fee_b3c, found_at, pplns_credited
           FROM blocks
          WHERE id = $1
            AND is_confirmed = TRUE
            AND is_orphan = FALSE
          LIMIT 1`,
        [blockId]
    );
    if (blocks.length === 0) return;
    const b = blocks[0]!;
    if (b.pplns_credited) return;

    const reward = parseFloat(b.reward_b3c);
    const feeFraction = config.pool.feePercent / 100;
    const grossFee = reward * feeFraction;
    const distributable = reward - grossFee;
    const N = config.pool.pplnsNShares;

    // Pull the last N shares submitted at or before the block was found.
    const shares = await query<{ user_id: string; diff: string }>(
        `SELECT user_id, diff
           FROM shares
          WHERE submitted_at <= $1::timestamptz
          ORDER BY submitted_at DESC, id DESC
          LIMIT $2`,
        [b.found_at, N]
    );

    if (shares.length === 0) {
        log.warn({ blockId }, "no shares in PPLNS window — block reward goes to pool fee");
        await tx(async (c) => {
            await c.query(
                `UPDATE blocks SET pplns_credited = TRUE, pool_fee_b3c = $1 WHERE id = $2`,
                [reward.toFixed(8), blockId]
            );
        });
        return;
    }

    const totals = new Map<number, number>();
    let sumDiff = 0;
    for (const s of shares) {
        const uid = parseInt(s.user_id, 10);
        const d = parseFloat(s.diff);
        totals.set(uid, (totals.get(uid) ?? 0) + d);
        sumDiff += d;
    }

    await tx(async (c) => {
        // Pool-fee bookkeeping entry (no user, kept implicit via blocks.pool_fee_b3c).
        for (const [uid, diff] of totals) {
            const share = (diff / sumDiff) * distributable;
            const rounded = Number(share.toFixed(8));
            if (rounded <= 0) continue;
            await c.query(
                `INSERT INTO balance_entries(user_id, block_id, delta_b3c, kind, description)
                 VALUES ($1, $2, $3, 'credit', $4)`,
                [
                    uid,
                    blockId,
                    rounded.toFixed(8),
                    `PPLNS credit for block ${blockId} (diff ${diff.toFixed(2)} of ${sumDiff.toFixed(2)})`,
                ]
            );
        }
        await c.query(
            `UPDATE blocks SET pplns_credited = TRUE, pool_fee_b3c = $1 WHERE id = $2`,
            [grossFee.toFixed(8), blockId]
        );
    });

    log.info(
        {
            blockId,
            reward,
            grossFee,
            distributable,
            distinctUsers: totals.size,
            sharesUsed: shares.length,
        },
        "PPLNS credited"
    );
}

// Return the per-user share contribution and projected payout if a block
// were to be found right now. Useful for the dashboard "pending" tile.
export async function projectedPplns(now = new Date()): Promise<Map<number, { diff: number; share: number }>> {
    const N = config.pool.pplnsNShares;
    const shares = await query<{ user_id: string; diff: string }>(
        `SELECT user_id, diff
           FROM shares
          WHERE submitted_at <= $1::timestamptz
          ORDER BY submitted_at DESC, id DESC
          LIMIT $2`,
        [now.toISOString(), N]
    );
    let sum = 0;
    const totals = new Map<number, number>();
    for (const s of shares) {
        const uid = parseInt(s.user_id, 10);
        const d = parseFloat(s.diff);
        totals.set(uid, (totals.get(uid) ?? 0) + d);
        sum += d;
    }
    const out = new Map<number, { diff: number; share: number }>();
    if (sum === 0) return out;
    for (const [uid, d] of totals) out.set(uid, { diff: d, share: d / sum });
    return out;
}
