import { Router } from "express";
import { query } from "../../lib/db";
import { config } from "../../config";
import { explorerBlockUrl } from "../../lib/explorer";
import { shareHashrateHps, SHARE_HASHRATE_WINDOW_SECONDS } from "../../lib/pool-stats";
import { fetchStratumStats } from "../socket";
import { requireAuth, AuthedUser } from "../middleware/auth";
import type { Request } from "express";

export function publicRoutes(): Router {
    const r = Router();

    r.get("/", async (_req, res) => {
        const blocks = await query<{
            height: string;
            hash: string;
            reward_b3c: string;
            confirmations: string;
            is_confirmed: boolean;
            is_orphan: boolean;
            found_at: string;
        }>(
            `SELECT height, hash, reward_b3c, confirmations, is_confirmed, is_orphan, found_at
               FROM blocks ORDER BY id DESC LIMIT 10`
        );
        const buckets = await query<{ bucket_at: string; hashrate_hps: string }>(
            `SELECT bucket_at::text, hashrate_hps::text
               FROM pool_hashrate_buckets
              WHERE bucket_at >= NOW() - interval '24 hours'
              ORDER BY bucket_at ASC`
        );
        const found = await query<{ n: string }>("SELECT COUNT(*)::text AS n FROM blocks");
        res.render("home", {
            title: "B3Chain Mining Pool",
            poolUrl: stratumPublicUrl(),
            feePercent: config.pool.feePercent,
            blocks,
            buckets,
            blocksFound: parseInt(found[0]?.n ?? "0", 10) || 0,
            explorerBlockUrl,
        });
    });

    r.get("/blocks", async (_req, res) => {
        const blocks = await query(
            `SELECT id, height, hash, reward_b3c, confirmations, is_confirmed, is_orphan,
                    found_at, finder_user_id IS NOT NULL AS has_finder
               FROM blocks ORDER BY id DESC LIMIT 200`
        );
        res.render("blocks", { title: "Recent blocks", blocks, explorerBlockUrl });
    });

    r.get("/blocks/:hash", async (req, res) => {
        const hash = String(req.params.hash ?? "");
        const rows = await query<{
            height: string;
            hash: string;
            reward_b3c: string;
            confirmations: string;
            is_confirmed: boolean;
            is_orphan: boolean;
            found_at: string;
            email: string | null;
            worker_name: string | null;
        }>(
            `SELECT b.height, b.hash, b.reward_b3c, b.confirmations, b.is_confirmed, b.is_orphan,
                    b.found_at, u.email, w.name AS worker_name
               FROM blocks b
               LEFT JOIN users u ON u.id = b.finder_user_id
               LEFT JOIN workers w ON w.id = b.finder_worker_id
              WHERE b.hash = $1
              LIMIT 1`,
            [hash]
        );
        const block = rows[0];
        if (!block) {
            res.status(404).render("error", { title: "Not found", message: "Block not found." });
            return;
        }
        res.render("block", {
            title: `Block ${block.height}`,
            block,
            explorerUrl: explorerBlockUrl(block.hash),
            confirmationsRequired: config.pool.blockConfirmations,
        });
    });

    r.get("/getting-started", (_req, res) => {
        res.render("getting-started", {
            title: "Getting started",
            poolUrl: stratumPublicUrl(),
            network: config.network,
            defaultDifficulty: config.stratum.defaultDifficulty,
            vardiffTargetSeconds: config.stratum.vardiffTargetSeconds,
            vardiffEnabled: config.stratum.vardiffEnabled,
        });
    });

    r.get("/api/pool/buckets", async (_req, res) => {
        const interval = bucketInterval(String(_req.query.range ?? "1h"));
        const rows = await query(
            `SELECT bucket_at, hashrate_hps, miners_online
               FROM pool_hashrate_buckets
              WHERE bucket_at >= NOW() - interval '${interval}'
              ORDER BY bucket_at ASC`
        );
        res.json(rows);
    });

    r.get("/api/pool/summary", async (_req, res) => {
        const [diffRows, blockRows, stats] = await Promise.all([
            query<{ d: string }>(
                `SELECT COALESCE(SUM(diff), 0)::float8::text AS d
                   FROM shares
                  WHERE submitted_at >= NOW() - interval '5 minutes'`
            ),
            query<{ n: string }>("SELECT COUNT(*)::text AS n FROM blocks"),
            fetchStratumStats(),
        ]);
        const totalDiff = parseFloat(diffRows[0]?.d ?? "0");
        res.json({
            hashrate5m: shareHashrateHps(totalDiff, SHARE_HASHRATE_WINDOW_SECONDS),
            connectedMiners: stats.miners,
            chainTip: stats.lastJobHeight,
            blocksFound: parseInt(blockRows[0]?.n ?? "0", 10) || 0,
            feePercent: config.pool.feePercent,
        });
    });

    r.get("/api/pool/blocks", async (_req, res) => {
        const rows = await query(
            `SELECT height, hash, reward_b3c, confirmations, is_confirmed, is_orphan, found_at
               FROM blocks ORDER BY id DESC LIMIT 200`
        );
        res.json(rows);
    });

    r.get("/api/me/buckets", requireAuth, async (req, res) => {
        const u = (req as Request & { user: AuthedUser }).user;
        const range = String(req.query.range ?? "24h");
        const interval = bucketInterval(range);
        const rows = await query(
            `SELECT bucket_at, hashrate_hps
               FROM hashrate_buckets
              WHERE user_id = $1
                AND bucket_at >= NOW() - interval '${interval}'
              ORDER BY bucket_at ASC`,
            [u.id]
        );
        res.json(rows);
    });

    return r;
}

function bucketInterval(range: string): string {
    if (range === "30d") return "30 days";
    if (range === "7d") return "7 days";
    if (range === "1h") return "1 hour";
    return "24 hours";
}

function stratumPublicUrl(): string {
    if (config.network === "testnet") return "stratum+tcp://pool.b3chain.org:3333";
    return `stratum+tcp://${config.web.baseUrl.replace(/^https?:\/\//, "").split("/")[0]}:${config.stratum.port}`;
}
