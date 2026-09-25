import * as crypto from "crypto";
import { Request } from "express";
import { query } from "../lib/db";
import { config } from "../config";

export async function createSession(userId: number, req: Request): Promise<string> {
    const id = crypto.randomBytes(24).toString("hex");
    const ua = String(req.get("user-agent") ?? "").slice(0, 512);
    await query(
        `INSERT INTO sessions(id, user_id, expires_at, user_agent, ip)
         VALUES ($1, $2, NOW() + ($3::int * interval '1 hour'), $4, $5)`,
        [id, userId, config.web.sessionHours, ua, req.ip ?? ""]
    );
    return id;
}

export async function userIdForSession(sid: string): Promise<number | null> {
    if (!sid) return null;
    const rows = await query<{ user_id: string }>(
        `SELECT user_id::text FROM sessions WHERE id = $1 AND expires_at > NOW() LIMIT 1`,
        [sid]
    );
    if (rows.length === 0) return null;
    const id = parseInt(rows[0]!.user_id, 10);
    return Number.isFinite(id) ? id : null;
}

export async function deleteSession(sid: string): Promise<void> {
    if (!sid) return;
    await query(`DELETE FROM sessions WHERE id = $1`, [sid]);
}
