// On a successful share that mined a block (the stratum service tells us
// via IPC), insert a row into `blocks` with the coinbase reward so that
// the BlockConfirmer can later credit it.

import { query } from "../lib/db";
import { ShareEvent } from "../lib/ipc";
import { getBlock, rpc } from "../lib/rpc";
import { Logger } from "../lib/logger";

export async function recordFoundBlock(s: ShareEvent, log: Logger): Promise<void> {
    if (!s.isBlock || !s.blockHash) return;

    // Skip if already recorded (idempotent re-entry on restart).
    const existing = await query<{ id: string }>(
        "SELECT id FROM blocks WHERE hash = $1 LIMIT 1",
        [s.blockHash]
    );
    if (existing.length > 0) return;

    let height = s.blockHeight ?? 0;
    let reward = 0;
    try {
        const info = await getBlock(s.blockHash);
        if (info && typeof info.height === "number") height = info.height;
        const firstTxId = info && Array.isArray(info.tx) ? info.tx[0] : undefined;
        if (firstTxId) {
            try {
                const cb = await rpc<{ vout?: { value?: number }[] }>(
                    "getrawtransaction",
                    [firstTxId, true, s.blockHash]
                );
                for (const o of cb.vout ?? []) reward += Number(o.value ?? 0);
            } catch {
                // Skip — we can backfill reward later from a periodic sweep.
            }
        }
    } catch (e) {
        log.warn({ err: (e as Error).message, hash: s.blockHash }, "could not fetch block info");
    }

    const finder = await query<{ id: string }>(
        "SELECT id FROM users WHERE email = $1 LIMIT 1",
        [s.user]
    );
    const finderId = finder.length > 0 ? parseInt(finder[0]!.id, 10) : null;
    let workerId: number | null = null;
    if (finderId !== null) {
        const w = await query<{ id: string }>(
            "SELECT id FROM workers WHERE user_id = $1 AND name = $2 LIMIT 1",
            [finderId, s.workerName]
        );
        if (w.length > 0) workerId = parseInt(w[0]!.id, 10);
    }
    await query(
        `INSERT INTO blocks(height, hash, finder_user_id, finder_worker_id,
                            reward_b3c, pool_fee_b3c, confirmations,
                            is_confirmed, is_orphan, found_at)
         VALUES ($1, $2, $3, $4, $5, 0, 0, FALSE, FALSE, to_timestamp($6 / 1000.0))`,
        [height, s.blockHash, finderId, workerId, reward.toFixed(8), s.timestampMs]
    );
    log.info(
        { hash: s.blockHash, height, reward, finder: s.user },
        "block recorded for confirmation tracking"
    );
}
