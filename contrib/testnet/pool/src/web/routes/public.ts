import { Router } from "express";
import { query } from "../../lib/db";
import { config } from "../../config";

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
        res.render("home", {
            title: "B3Chain Mining Pool",
            poolUrl: stratumPublicUrl(),
            feePercent: config.pool.feePercent,
            blocks,
            buckets,
        });
    });

    r.get("/blocks", async (_req, res) => {
        const blocks = await query(
            `SELECT id, height, hash, reward_b3c, confirmations, is_confirmed, is_orphan,
                    found_at, finder_user_id IS NOT NULL AS has_finder
               FROM blocks ORDER BY id DESC LIMIT 200`
        );
        res.render("blocks", { title: "Recent blocks", blocks });
    });

    r.get("/getting-started", (_req, res) => {
        res.render("getting-started", {
            title: "Getting started",
            poolUrl: stratumPublicUrl(),
            network: config.network,
        });
    });

    r.get("/api/pool/buckets", async (_req, res) => {
        const range = String(_req.query.range ?? "1h");
        const interval =
            range === "30d" ? "30 days" : range === "7d" ? "7 days" : range === "24h" ? "24 hours" : "1 hour";
        const rows = await query(
            `SELECT bucket_at, hashrate_hps, miners_online
               FROM pool_hashrate_buckets
              WHERE bucket_at >= NOW() - interval '${interval}'
              ORDER BY bucket_at ASC`
        );
        res.json(rows);
    });

    return r;
}

function stratumPublicUrl(): string {
    if (config.network === "testnet") return "stratum+tcp://pool.b3chain.org:3333";
    return `stratum+tcp://${config.web.baseUrl.replace(/^https?:\/\//, "").split("/")[0]}:${config.stratum.port}`;
}
