// Polls b3chaind for confirmation status of every recently-found block
// in `blocks` that is not yet confirmed/orphaned.
//
// On `confirmations >= B3POOL_BLOCK_CONFIRMATIONS`: mark confirmed, then
// the PPLNS module credits balances. On `getblock` returning null
// (or a different block at the same height in the active chain): orphan.

import { query } from "../lib/db";
import { getBlock } from "../lib/rpc";
import { config } from "../config";
import { Logger } from "../lib/logger";
import { creditPplns } from "./pplns";

export class BlockConfirmer {
    private timer: NodeJS.Timeout | null = null;

    constructor(private log: Logger) {}

    start(): void {
        this.timer = setInterval(() => void this.tick(), 30_000);
        // run once after a short delay to populate quickly
        setTimeout(() => void this.tick(), 5_000);
    }

    stop(): void {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
    }

    public async tick(): Promise<void> {
        const rows = await query<{ id: string; height: string; hash: string }>(
            `SELECT id, height, hash FROM blocks
              WHERE NOT is_confirmed AND NOT is_orphan
              ORDER BY id ASC
              LIMIT 200`
        );
        for (const b of rows) {
            try {
                await this.checkOne(parseInt(b.id, 10), parseInt(b.height, 10), b.hash);
            } catch (e) {
                this.log.warn({ err: (e as Error).message, hash: b.hash }, "confirmer error");
            }
        }
    }

    private async checkOne(id: number, height: number, hash: string): Promise<void> {
        const info = await getBlock(hash);
        if (!info) {
            await query(
                `UPDATE blocks SET is_orphan = TRUE, confirmations = 0 WHERE id = $1`,
                [id]
            );
            this.log.warn({ id, hash, height }, "block orphaned (not in chain)");
            return;
        }
        if (info.confirmations < 0) {
            // negative confirmations means the block is no longer on the active chain
            await query(
                `UPDATE blocks SET is_orphan = TRUE, confirmations = $1 WHERE id = $2`,
                [info.confirmations, id]
            );
            this.log.warn({ id, hash, height }, "block orphaned (negative confirmations)");
            return;
        }
        await query(
            `UPDATE blocks SET confirmations = $1 WHERE id = $2`,
            [info.confirmations, id]
        );
        if (info.confirmations >= config.pool.blockConfirmations) {
            await query(
                `UPDATE blocks SET is_confirmed = TRUE, confirmed_at = NOW() WHERE id = $1`,
                [id]
            );
            this.log.info({ id, hash, height, confirmations: info.confirmations }, "block confirmed");
            await creditPplns(id, this.log);
        }
    }
}
