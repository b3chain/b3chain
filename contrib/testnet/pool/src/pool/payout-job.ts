// Hourly payout job: for every user whose ledger balance is at or above
// their `minimum_payout_b3c` AND who has a valid payout_address, accumulate
// into a single sendmany call from the pool-payouts wallet.

import { query, tx } from "../lib/db";
import { config } from "../config";
import { sendMany, getWalletBalance } from "../lib/rpc";
import { Logger } from "../lib/logger";
import { isValidB3AddressForNetwork } from "../lib/address";

export class PayoutJob {
    private timer: NodeJS.Timeout | null = null;
    private running = false;

    constructor(private log: Logger) {}

    start(): void {
        // Run shortly after startup, then on a fixed interval.
        setTimeout(() => void this.tick(), 30_000);
        this.timer = setInterval(() => void this.tick(), config.pool.payoutIntervalMs);
    }

    stop(): void {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
    }

    async tick(): Promise<void> {
        if (this.running) return;
        this.running = true;
        try {
            await this.doPayouts();
        } catch (e) {
            this.log.error({ err: (e as Error).message }, "payout tick failed");
        } finally {
            this.running = false;
        }
    }

    private async doPayouts(): Promise<void> {
        const candidates = await query<{
            id: string;
            email: string;
            payout_address: string;
            minimum_payout_b3c: string;
            balance: string;
        }>(
            `SELECT u.id, u.email, u.payout_address, u.minimum_payout_b3c,
                    COALESCE((SELECT SUM(delta_b3c) FROM balance_entries
                               WHERE user_id = u.id), 0) AS balance
               FROM users u
              WHERE u.email_verified
                AND u.payout_address IS NOT NULL
              ORDER BY u.id ASC`
        );

        const targets: Record<string, number> = {};
        const debitPlan: { userId: number; amount: number; address: string }[] = [];
        let total = 0;
        for (const c of candidates) {
            const balance = parseFloat(c.balance);
            const min = parseFloat(c.minimum_payout_b3c);
            if (balance < min || balance <= 0) continue;
            if (!isValidB3AddressForNetwork(c.payout_address, config.network)) {
                this.log.warn({ userId: c.id, addr: c.payout_address }, "invalid address — skipping");
                continue;
            }
            const amount = Number(balance.toFixed(8));
            // sendmany aggregates duplicate addresses — be safe.
            targets[c.payout_address] = (targets[c.payout_address] ?? 0) + amount;
            debitPlan.push({ userId: parseInt(c.id, 10), amount, address: c.payout_address });
            total += amount;
        }

        if (debitPlan.length === 0) {
            this.log.info("no payouts due");
            return;
        }

        let walletBal = 0;
        try {
            walletBal = await getWalletBalance();
        } catch (e) {
            this.log.error({ err: (e as Error).message }, "could not read wallet balance");
            return;
        }
        if (walletBal < total) {
            this.log.error(
                { needed: total, have: walletBal },
                "insufficient pool wallet balance for payout — skipping"
            );
            return;
        }

        let txid: string;
        try {
            txid = await sendMany(
                "",
                Object.fromEntries(Object.entries(targets).map(([a, v]) => [a, Number(v.toFixed(8))])),
                "b3chain-pool payout"
            );
        } catch (e) {
            this.log.error({ err: (e as Error).message }, "sendmany failed");
            return;
        }

        await tx(async (c) => {
            const ins = await c.query<{ id: string }>(
                `INSERT INTO payouts(txid, confirmed, total_b3c, sent_at)
                 VALUES ($1, FALSE, $2, NOW())
                 RETURNING id`,
                [txid, total.toFixed(8)]
            );
            const payoutId = parseInt(ins.rows[0]!.id, 10);
            for (const d of debitPlan) {
                await c.query(
                    `INSERT INTO payout_recipients(payout_id, user_id, address, amount_b3c)
                     VALUES ($1, $2, $3, $4)`,
                    [payoutId, d.userId, d.address, d.amount.toFixed(8)]
                );
                await c.query(
                    `INSERT INTO balance_entries(user_id, payout_id, delta_b3c, kind, description)
                     VALUES ($1, $2, $3, 'debit', $4)`,
                    [d.userId, payoutId, (-d.amount).toFixed(8), `Payout ${txid}`]
                );
            }
        });
        this.log.info({ txid, total, recipients: debitPlan.length }, "payout sent");
    }
}
