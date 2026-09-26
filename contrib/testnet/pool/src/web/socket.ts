// Socket.IO push namespaces.
//
//   /         — public pool stats (anonymous): hashrate:update, block:found
//   /me       — per-user (auth via signed cookie): hashrate:update, share:accepted,
//                payout:sent
//
// Per the workspace `complete-implementation.mdc` rule we push events
// rather than polling — the server runs a 5-second tick that emits the
// latest aggregated values to whichever rooms have subscribers.

import { Server as IOServer } from "socket.io";
import { Server as HttpServer } from "http";
import cookieSession from "cookie-session";
import { config } from "../config";
import { query } from "../lib/db";
import { consumeNew } from "../lib/event-cursor";
import { userIdForSession } from "./session-store";
import { shareHashrateHps, SHARE_HASHRATE_WINDOW_SECONDS } from "../lib/pool-stats";
import { formatDifficulty } from "../lib/difficulty-math";
import { Logger, makeLogger } from "../lib/logger";
import * as http from "http";

interface StratumStats {
    miners: number;
    lastJobHeight: number | null;
    networkDifficulty?: number | null;
    assignedDifficulty?: number | null;
    connections?: LiveConnection[];
}

export interface LiveConnection {
    user: string;
    worker: string;
    difficulty: number;
    accepted: number;
    rejected: number;
    lastShareAt: number | null;
}

export async function fetchStratumStats(): Promise<StratumStats> {
    return new Promise((resolve) => {
        const req = http.get({ host: "127.0.0.1", port: 3334, path: "/stats", timeout: 1500 }, (res) => {
            let buf = "";
            res.on("data", (c) => (buf += c));
            res.on("end", () => {
                try {
                    resolve(JSON.parse(buf));
                } catch {
                    resolve({ miners: 0, lastJobHeight: null, connections: [] });
                }
            });
        });
        req.on("error", () => resolve({ miners: 0, lastJobHeight: null, connections: [] }));
        req.on("timeout", () => {
            req.destroy();
            resolve({ miners: 0, lastJobHeight: null, connections: [] });
        });
    });
}

async function fetchUserStats(userId: number): Promise<{
    hashrate: number;
    activeWorkers: number;
    sharesLastHour: number;
    balance: number;
}> {
    const rows = await query<{ h: string | null; w: string; s: string; balance: string | null }>(
        `SELECT
           (SELECT COALESCE(SUM(diff)*4294967296.0/300.0, 0)
              FROM shares WHERE user_id = $1
                AND submitted_at >= NOW() - interval '5 minutes')::float8 AS h,
           (SELECT COUNT(*) FROM workers
              WHERE user_id = $1 AND last_seen_at >= NOW() - interval '10 minutes')::text AS w,
           (SELECT COUNT(*) FROM shares
              WHERE user_id = $1 AND submitted_at >= NOW() - interval '1 hour')::text AS s,
           (SELECT COALESCE(SUM(delta_b3c), 0) FROM balance_entries
              WHERE user_id = $1)::text AS balance`,
        [userId]
    );
    const r = rows[0]!;
    return {
        hashrate: r.h ? parseFloat(r.h) : 0,
        activeWorkers: parseInt(r.w, 10),
        sharesLastHour: parseInt(r.s, 10),
        balance: r.balance ? parseFloat(r.balance) : 0,
    };
}

export class SocketIoBus {
    public io: IOServer;
    private log: Logger;
    private tickTimer: NodeJS.Timeout | null = null;
    public lastBlock: { height: number; hash: string } | null = null;
    /** Null until the first tick records the current max ids. */
    private blockCursor: number | null = null;
    private payoutCursor: number | null = null;

    constructor(httpServer: HttpServer) {
        this.log = makeLogger("socket");
        this.io = new IOServer(httpServer, {
            path: "/socket.io/",
            serveClient: false,
            transports: ["websocket", "polling"],
        });

        // Cookie-session auth for /me namespace.
        const session = cookieSession({
            name: "b3pool",
            keys: [config.web.cookieSecret],
            maxAge: config.web.sessionHours * 3600 * 1000,
        });
        const me = this.io.of("/me");
        me.use((socket, next) => {
            const fakeRes = { getHeader: () => undefined, setHeader: () => undefined, on: () => undefined } as unknown as Parameters<typeof session>[1];
            session(
                socket.request as unknown as Parameters<typeof session>[0],
                fakeRes,
                (err) => {
                    if (err) return next(err);
                    const sess = (socket.request as unknown as { session?: { sid?: string } }).session;
                    const sid = sess?.sid;
                    if (!sid) return next(new Error("unauthorized"));
                    void userIdForSession(sid).then((uid) => {
                        if (!uid) return next(new Error("unauthorized"));
                        (socket.data as { userId: number }).userId = uid;
                        socket.join(`user:${uid}`);
                        next();
                    }, (err) => next(err as Error));
                }
            );
        });
        me.on("connection", (socket) => {
            const uid = (socket.data as { userId: number }).userId;
            this.log.debug({ uid }, "user socket connected");
            void this.pushUser(uid);
        });

        // Public namespace.
        this.io.on("connection", () => {
            void this.pushPool();
        });

        this.tickTimer = setInterval(() => void this.tick(), 5000);
    }

    async tick(): Promise<void> {
        await this.pushPool();
        await this.pollNewRows();
        // Push per-user updates only to rooms with at least one subscriber.
        const me = this.io.of("/me");
        const rooms = me.adapter.rooms;
        for (const room of rooms.keys()) {
            if (!room.startsWith("user:")) continue;
            const uid = parseInt(room.slice(5), 10);
            if (Number.isFinite(uid)) await this.pushUser(uid);
        }
    }

    async pushPool(): Promise<void> {
        const [stats, diffRows, blockRows] = await Promise.all([
            fetchStratumStats(),
            query<{ d: string }>(
                `SELECT COALESCE(SUM(diff), 0)::float8::text AS d
                   FROM shares
                  WHERE submitted_at >= NOW() - interval '5 minutes'`
            ),
            query<{ n: string }>("SELECT COUNT(*)::text AS n FROM blocks"),
        ]);
        const totalDiff = parseFloat(diffRows[0]?.d ?? "0");
        const network = stats.networkDifficulty;
        const assigned = stats.assignedDifficulty;
        this.io.emit("hashrate:update", {
            hashrate: shareHashrateHps(totalDiff, SHARE_HASHRATE_WINDOW_SECONDS),
            miners: stats.miners,
            height: stats.lastJobHeight,
            blocksFound: parseInt(blockRows[0]?.n ?? "0", 10) || 0,
            networkDifficulty: network ?? null,
            assignedDifficulty: assigned ?? null,
            networkDifficultyText: network == null ? null : formatDifficulty(network),
            assignedDifficultyText: assigned == null ? null : formatDifficulty(assigned),
            t: Date.now(),
        });
    }

    async pollNewRows(): Promise<void> {
        if (this.blockCursor === null || this.payoutCursor === null) {
            const [b, p] = await Promise.all([
                query<{ n: string }>("SELECT COALESCE(MAX(id), 0)::text AS n FROM blocks"),
                query<{ n: string }>("SELECT COALESCE(MAX(id), 0)::text AS n FROM payouts"),
            ]);
            this.blockCursor = parseInt(b[0]?.n ?? "0", 10) || 0;
            this.payoutCursor = parseInt(p[0]?.n ?? "0", 10) || 0;
            return;
        }
        const blocks = await query<{
            id: string;
            height: string;
            hash: string;
            reward_b3c: string;
            finder_user_id: string | null;
            found_at: string;
        }>(
            `SELECT id, height, hash, reward_b3c, finder_user_id, found_at
               FROM blocks WHERE id > $1 ORDER BY id ASC`,
            [this.blockCursor]
        );
        const blockStep = consumeNew(
            this.blockCursor,
            blocks.map((row) => ({
                id: parseInt(row.id, 10),
                height: parseInt(row.height, 10),
                hash: row.hash,
                reward: row.reward_b3c,
                finderUserId: row.finder_user_id ? parseInt(row.finder_user_id, 10) : null,
                foundAt: row.found_at,
            }))
        );
        this.blockCursor = blockStep.cursor;
        for (const row of blockStep.fresh) {
            this.notifyBlockFound(row.height, row.hash, row.finderUserId, row.reward, row.foundAt);
        }

        const payouts = await query<{
            id: string;
            txid: string | null;
            user_id: string;
            amount_b3c: string;
        }>(
            `SELECT p.id, p.txid, pr.user_id, pr.amount_b3c
               FROM payouts p
               JOIN payout_recipients pr ON pr.payout_id = p.id
              WHERE p.id > $1
              ORDER BY p.id ASC`,
            [this.payoutCursor]
        );
        const payStep = consumeNew(
            this.payoutCursor,
            payouts.map((row) => ({
                id: parseInt(row.id, 10),
                userId: parseInt(row.user_id, 10),
                amount: parseFloat(row.amount_b3c),
                txid: row.txid ?? "",
            }))
        );
        this.payoutCursor = payStep.cursor;
        for (const row of payStep.fresh) {
            this.notifyPayout(row.userId, row.amount, row.txid);
        }
    }

    async pushUser(userId: number): Promise<void> {
        const stats = await fetchUserStats(userId);
        this.io.of("/me").to(`user:${userId}`).emit("hashrate:update", {
            ...stats,
            t: Date.now(),
        });
    }

    notifyBlockFound(
        height: number,
        hash: string,
        finderUserId: number | null,
        reward?: string,
        foundAt?: string
    ): void {
        this.lastBlock = { height, hash };
        this.io.emit("block:found", { height, hash, reward: reward ?? null, foundAt: foundAt ?? null, t: Date.now() });
        if (finderUserId !== null) {
            this.io.of("/me").to(`user:${finderUserId}`).emit("block:found", { height, hash, t: Date.now() });
        }
    }

    notifyPayout(userId: number, amount: number, txid: string): void {
        this.io.of("/me").to(`user:${userId}`).emit("payout:sent", { amount, txid, t: Date.now() });
    }

    stop(): void {
        if (this.tickTimer) clearInterval(this.tickTimer);
        this.io.close();
    }
}
