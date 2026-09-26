// Batched writer that turns ShareEvent IPC messages into rows in
// `shares` and rolling rows in `hashrate_buckets` / `pool_hashrate_buckets`.
//
// Anonymous shares (Phase A) — i.e. shares whose `user` is not a known
// users.email — are still counted in pool_hashrate_buckets so the public
// landing page is meaningful, but skipped from per-user tables.

import { PoolClient } from "pg";
import { RejectEvent, ShareAttest, ShareEvent, ShareSigEvent } from "../lib/ipc";
import { query, tx } from "../lib/db";
import { hashrateFromShares } from "../lib/difficulty-math";
import { rejectColumn } from "../lib/reject-reason";
import { Logger } from "../lib/logger";

interface BufferedShare extends ShareEvent {
    userId: number | null;
    workerId: number | null;
}

export class ShareWriter {
    private buf: BufferedShare[] = [];
    private flushTimer: NodeJS.Timeout | null = null;
    private flushIntervalMs = 1000;

    // Caches to skip repeat lookups (user or worker created lazily).
    private userIdCache = new Map<string, number>();
    private workerIdCache = new Map<string, number>();
    public lastBucketAt: Date | null = null;
    /** Accepted shares with no user row, keyed by minute start (ms). */
    private anonByMinute = new Map<number, { diff: number; count: number }>();
    private rejectBuf: Array<RejectEvent & { userId: number; workerId: number }> = [];
    private sigBuf: Array<ShareSigEvent & { userId: number | null; workerId: number | null }> = [];

    constructor(private log: Logger) {}

    start(): void {
        if (this.flushTimer) return;
        this.flushTimer = setInterval(() => {
            void this.flush();
        }, this.flushIntervalMs);
        // Roll buckets at minute boundaries.
        setInterval(() => void this.rollBucket(), 30_000);
    }

    stop(): Promise<void> {
        if (this.flushTimer) clearInterval(this.flushTimer);
        this.flushTimer = null;
        return this.flush();
    }

    async accept(s: ShareEvent): Promise<void> {
        const userId = await this.resolveUserId(s.user);
        const workerId = userId !== null ? await this.resolveWorkerId(userId, s.workerName) : null;
        this.buf.push({ ...s, userId, workerId });
        if (this.buf.length > 500) await this.flush();
    }

    async acceptReject(s: RejectEvent): Promise<void> {
        const userId = await this.resolveUserId(s.user);
        if (userId === null) return;
        const workerId = await this.resolveWorkerId(userId, s.workerName);
        this.rejectBuf.push({ ...s, userId, workerId });
        if (this.rejectBuf.length > 500) await this.flush();
    }

    async acceptSig(s: ShareSigEvent): Promise<void> {
        const userId = await this.resolveUserId(s.user);
        const workerId = userId !== null ? await this.resolveWorkerId(userId, s.workerName) : null;
        this.sigBuf.push({ ...s, userId, workerId });
        if (this.sigBuf.length > 500) await this.flush();
    }

    private async resolveUserId(email: string): Promise<number | null> {
        if (!email || email.includes(":")) return null;
        const hit = this.userIdCache.get(email);
        if (hit !== undefined) return hit;
        const rows = await query<{ id: string }>(
            "SELECT id FROM users WHERE email = $1 LIMIT 1",
            [email]
        );
        if (rows.length === 0) return null;
        const id = parseInt(rows[0]!.id, 10);
        this.userIdCache.set(email, id);
        return id;
    }

    private async resolveWorkerId(userId: number, name: string): Promise<number> {
        const key = `${userId}|${name}`;
        const hit = this.workerIdCache.get(key);
        if (hit !== undefined) return hit;
        const ins = await query<{ id: string }>(
            `INSERT INTO workers(user_id, name, last_seen_at)
             VALUES ($1, $2, NOW())
             ON CONFLICT (user_id, name) DO UPDATE SET last_seen_at = NOW()
             RETURNING id`,
            [userId, name]
        );
        const id = parseInt(ins[0]!.id, 10);
        this.workerIdCache.set(key, id);
        return id;
    }

    private async flush(): Promise<void> {
        if (this.buf.length === 0 && this.rejectBuf.length === 0 && this.sigBuf.length === 0) return;
        const batch = this.buf.splice(0);
        const rejects = this.rejectBuf.splice(0);
        const sigs = this.sigBuf.splice(0);
        try {
            await tx(async (c) => {
                for (const s of batch) {
                    let shareId: number | null = null;
                    if (s.userId !== null && s.workerId !== null) {
                        const ins = await c.query(
                            `INSERT INTO shares(user_id, worker_id, diff, is_block, block_hash, submitted_at)
                             VALUES ($1, $2, $3, $4, $5, to_timestamp($6 / 1000.0))
                             RETURNING id`,
                            [s.userId, s.workerId, s.diff, s.isBlock, s.blockHash ?? null, s.timestampMs]
                        );
                        shareId = Number(ins.rows[0].id);
                        await c.query(
                            `UPDATE workers SET last_difficulty = $2, last_seen_at = to_timestamp($3 / 1000.0)
                              WHERE id = $1`,
                            [s.workerId, s.diff, s.timestampMs]
                        );
                    }
                    if (s.attest) {
                        await insertSignature(c, shareId, s.userId, s.workerId, s.attest, s.timestampMs);
                    }
                }
                for (const sig of sigs) {
                    await insertSignature(c, null, sig.userId, sig.workerId, sig.attest, sig.timestampMs);
                }
                for (const r of rejects) {
                    const column = rejectColumn(r.reason);
                    await c.query(
                        `UPDATE workers
                            SET ${column} = ${column} + 1,
                                last_reject_reason = $2,
                                last_reject_at = to_timestamp($3 / 1000.0),
                                last_seen_at = to_timestamp($3 / 1000.0)
                          WHERE id = $1`,
                        [r.workerId, r.reason, r.timestampMs]
                    );
                }
            });
            for (const s of batch) {
                if (s.userId !== null) continue;
                this.addAnon(s.timestampMs, s.diff);
            }
        } catch (e) {
            this.log.error({ err: (e as Error).message }, "share flush failed (re-queueing)");
            this.buf.unshift(...batch);
            this.rejectBuf.unshift(...rejects);
            this.sigBuf.unshift(...sigs);
        }
    }

    private addAnon(timestampMs: number, diff: number): void {
        const key = minuteStartMs(timestampMs);
        const cur = this.anonByMinute.get(key) ?? { diff: 0, count: 0 };
        cur.diff += diff;
        cur.count += 1;
        this.anonByMinute.set(key, cur);
    }

    private async rollBucket(): Promise<void> {
        const now = new Date();
        const minute = new Date(now);
        minute.setSeconds(0, 0);
        // Compute the just-completed minute (skip if we already rolled it).
        const target = new Date(minute.getTime() - 60_000);
        if (this.lastBucketAt && this.lastBucketAt.getTime() === target.getTime()) return;
        this.lastBucketAt = target;
        try {
            await tx(async (c) => {
                // Per-user
                await c.query(
                    `INSERT INTO hashrate_buckets(user_id, bucket_at, hashrate_hps, shares_count)
                     SELECT user_id, $1::timestamptz,
                            (SUM(diff) * 4294967296.0 / 60.0)::float8 AS h,
                            COUNT(*) AS n
                       FROM shares
                      WHERE submitted_at >= $1::timestamptz
                        AND submitted_at <  ($1::timestamptz + interval '1 minute')
                      GROUP BY user_id
                     ON CONFLICT (user_id, bucket_at) DO UPDATE
                        SET hashrate_hps = EXCLUDED.hashrate_hps,
                            shares_count = EXCLUDED.shares_count`,
                    [target.toISOString()]
                );
                // Pool-wide
                await c.query(
                    `INSERT INTO pool_hashrate_buckets(bucket_at, hashrate_hps, shares_count, miners_online)
                     SELECT $1::timestamptz,
                            COALESCE(SUM(diff) * 4294967296.0 / 60.0, 0)::float8,
                            COALESCE(COUNT(*), 0),
                            (SELECT COUNT(DISTINCT user_id) FROM shares
                              WHERE submitted_at >= $1::timestamptz
                                AND submitted_at <  ($1::timestamptz + interval '1 minute'))::int
                       FROM shares
                      WHERE submitted_at >= $1::timestamptz
                        AND submitted_at <  ($1::timestamptz + interval '1 minute')
                     ON CONFLICT (bucket_at) DO UPDATE
                        SET hashrate_hps = EXCLUDED.hashrate_hps,
                            shares_count = EXCLUDED.shares_count,
                            miners_online = EXCLUDED.miners_online`,
                    [target.toISOString()]
                );
                const anon = this.anonByMinute.get(target.getTime());
                if (anon && anon.count > 0) {
                    await c.query(
                        `UPDATE pool_hashrate_buckets
                            SET hashrate_hps = hashrate_hps + $2,
                                shares_count = shares_count + $3
                          WHERE bucket_at = $1::timestamptz`,
                        [target.toISOString(), hashrateFromShares(anon.diff, 60), anon.count]
                    );
                }
            });
            this.anonByMinute.delete(target.getTime());
        } catch (e) {
            this.log.error({ err: (e as Error).message }, "bucket roll failed");
        }
    }
}

export function estimateHashrate(totalDiff: number, windowSeconds: number): number {
    return hashrateFromShares(totalDiff, windowSeconds);
}

async function insertSignature(
    c: PoolClient,
    shareId: number | null,
    userId: number | null,
    workerId: number | null,
    attest: ShareAttest,
    timestampMs: number,
): Promise<void> {
    await c.query(
        `INSERT INTO share_signatures(share_id, user_id, worker_id, job_id, nonce, pubkey, signature, result, submitted_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, to_timestamp($9 / 1000.0))`,
        [shareId, userId, workerId, attest.jobId, attest.nonce, attest.pubkey, attest.signature, attest.result, timestampMs]
    );
}

function minuteStartMs(timestampMs: number): number {
    const d = new Date(timestampMs);
    d.setSeconds(0, 0);
    return d.getTime();
}
