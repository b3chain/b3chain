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
import { Logger, makeLogger } from "../lib/logger";
import * as http from "http";

interface StratumStats {
    miners: number;
    hashrate: number;
    lastJobHeight: number | null;
}

async function fetchStratumStats(): Promise<StratumStats> {
    return new Promise((resolve) => {
        const req = http.get({ host: "127.0.0.1", port: 3334, path: "/stats", timeout: 1500 }, (res) => {
            let buf = "";
            res.on("data", (c) => (buf += c));
            res.on("end", () => {
                try {
                    resolve(JSON.parse(buf));
                } catch {
                    resolve({ miners: 0, hashrate: 0, lastJobHeight: null });
                }
            });
        });
        req.on("error", () => resolve({ miners: 0, hashrate: 0, lastJobHeight: null }));
        req.on("timeout", () => {
            req.destroy();
            resolve({ miners: 0, hashrate: 0, lastJobHeight: null });
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
                    const sess = (socket.request as unknown as { session?: { userId?: number } }).session;
                    if (!sess?.userId) return next(new Error("unauthorized"));
                    (socket.data as { userId: number }).userId = sess.userId;
                    socket.join(`user:${sess.userId}`);
                    next();
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
        const stats = await fetchStratumStats();
        this.io.emit("hashrate:update", {
            hashrate: stats.hashrate,
            miners: stats.miners,
            height: stats.lastJobHeight,
            t: Date.now(),
        });
    }

    async pushUser(userId: number): Promise<void> {
        const stats = await fetchUserStats(userId);
        this.io.of("/me").to(`user:${userId}`).emit("hashrate:update", {
            ...stats,
            t: Date.now(),
        });
    }

    notifyBlockFound(height: number, hash: string, finderUserId: number | null): void {
        this.lastBlock = { height, hash };
        this.io.emit("block:found", { height, hash, t: Date.now() });
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
