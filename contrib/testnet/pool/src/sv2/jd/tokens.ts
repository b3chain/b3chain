// In-memory mining_job_token store with TTL.
//
// Tokens are 32 random bytes. Each one is single-use: AllocateMiningJobToken
// hands one out, DeclareMiningJob consumes it. We persist a row in
// `sv2_declared_jobs` so operators can audit JD activity.

import { randomBytes } from "node:crypto";
import { config } from "../../config";
import { query } from "../../lib/db";
import { Logger } from "../../lib/logger";

export interface JdToken {
    bytes: Uint8Array;
    userIdentifier: string;
    sessionId: number | null;
    issuedAt: number;
    expiresAt: number;
    coinbaseOutputMaxAdditionalSize: number;
    consumed: boolean;
}

const TOKEN_LEN = 32;

export class JdTokenStore {
    private byHex = new Map<string, JdToken>();

    constructor(private log: Logger) {
        // Periodic GC of expired/unused tokens.
        setInterval(() => this.gc(), 60_000).unref?.();
    }

    async issue(opts: {
        userIdentifier: string;
        sessionId: number | null;
        coinbaseOutputMaxAdditionalSize: number;
    }): Promise<JdToken> {
        const bytes = new Uint8Array(randomBytes(TOKEN_LEN));
        const now = Date.now();
        const tok: JdToken = {
            bytes,
            userIdentifier: opts.userIdentifier,
            sessionId: opts.sessionId,
            issuedAt: now,
            expiresAt: now + config.jd.tokenTtlMs,
            coinbaseOutputMaxAdditionalSize: opts.coinbaseOutputMaxAdditionalSize,
            consumed: false,
        };
        this.byHex.set(toHex(bytes), tok);
        try {
            await query(
                `INSERT INTO sv2_declared_jobs
                    (session_id, user_identifier, mining_job_token,
                     coinbase_max_extra_size, expires_at)
                 VALUES ($1, $2, $3, $4, to_timestamp($5))`,
                [
                    tok.sessionId,
                    tok.userIdentifier,
                    Buffer.from(tok.bytes),
                    tok.coinbaseOutputMaxAdditionalSize,
                    Math.floor(tok.expiresAt / 1000),
                ],
            );
        } catch (e) {
            this.log.warn({ err: (e as Error).message }, "jd token persist failed (continuing)");
        }
        return tok;
    }

    /** Mark a token consumed. Returns the token if it was valid+unconsumed. */
    async consume(tokenBytes: Uint8Array, declared: {
        version: number; coinbasePrefix: Uint8Array;
        coinbaseSuffix: Uint8Array; txCount: number;
    }): Promise<JdToken | null> {
        const hex = toHex(tokenBytes);
        const tok = this.byHex.get(hex);
        const now = Date.now();
        if (!tok) return null;
        if (tok.consumed) return null;
        if (tok.expiresAt <= now) { this.byHex.delete(hex); return null; }
        tok.consumed = true;
        try {
            await query(
                `UPDATE sv2_declared_jobs
                    SET consumed_at = now(),
                        declared_version = $2,
                        declared_coinbase_prefix = $3,
                        declared_coinbase_suffix = $4,
                        declared_tx_count = $5
                  WHERE mining_job_token = $1`,
                [
                    Buffer.from(tokenBytes),
                    declared.version,
                    Buffer.from(declared.coinbasePrefix),
                    Buffer.from(declared.coinbaseSuffix),
                    declared.txCount,
                ],
            );
        } catch (e) {
            this.log.warn({ err: (e as Error).message }, "jd token consume audit failed (continuing)");
        }
        return tok;
    }

    /** Mark a previously issued token rejected (DeclareMiningJob.Error). */
    async reject(tokenBytes: Uint8Array, reason: string): Promise<void> {
        const hex = toHex(tokenBytes);
        const tok = this.byHex.get(hex);
        if (tok) tok.consumed = true;
        try {
            await query(
                `UPDATE sv2_declared_jobs
                    SET rejected_reason = $2
                  WHERE mining_job_token = $1`,
                [Buffer.from(tokenBytes), reason.slice(0, 200)],
            );
        } catch (e) {
            this.log.warn({ err: (e as Error).message }, "jd token reject audit failed");
        }
    }

    private gc(): void {
        const now = Date.now();
        for (const [k, t] of this.byHex) {
            if (t.expiresAt <= now || t.consumed) this.byHex.delete(k);
        }
    }
}

function toHex(b: Uint8Array): string {
    let s = "";
    for (const x of b) s += x.toString(16).padStart(2, "0");
    return s;
}
