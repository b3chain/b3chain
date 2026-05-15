// Prometheus-compatible /metrics endpoint.

import { Router } from "express";
import { query } from "../../lib/db";

export function metricsRoutes(): Router {
    const r = Router();
    r.get("/metrics", async (_req, res) => {
        const stats = await Promise.all([
            query<{ n: string }>("SELECT COUNT(*)::text AS n FROM users WHERE email_verified"),
            query<{ n: string }>("SELECT COUNT(*)::text AS n FROM workers WHERE last_seen_at >= NOW() - interval '10 minutes'"),
            query<{ n: string }>("SELECT COUNT(*)::text AS n FROM blocks WHERE found_at >= NOW() - interval '24 hours'"),
            query<{ n: string }>("SELECT COUNT(*)::text AS n FROM blocks WHERE is_orphan"),
            query<{ n: string }>("SELECT COUNT(*)::text AS n FROM payouts"),
            query<{ n: string }>("SELECT COALESCE(SUM(total_b3c),0)::text AS n FROM payouts"),
            query<{ n: string }>(
                "SELECT COALESCE(SUM(diff)*4294967296.0/3600.0, 0)::text AS n FROM shares WHERE submitted_at >= NOW() - interval '1 hour'"
            ),
        ]);
        const lines = [
            "# HELP b3chain_pool_users_verified Number of verified users",
            "# TYPE b3chain_pool_users_verified gauge",
            `b3chain_pool_users_verified ${stats[0][0]?.n ?? 0}`,
            "# HELP b3chain_pool_workers_active Workers seen in the last 10 minutes",
            "# TYPE b3chain_pool_workers_active gauge",
            `b3chain_pool_workers_active ${stats[1][0]?.n ?? 0}`,
            "# HELP b3chain_pool_blocks_24h Blocks found in the last 24 hours",
            "# TYPE b3chain_pool_blocks_24h gauge",
            `b3chain_pool_blocks_24h ${stats[2][0]?.n ?? 0}`,
            "# HELP b3chain_pool_blocks_orphan_total Orphaned blocks lifetime",
            "# TYPE b3chain_pool_blocks_orphan_total counter",
            `b3chain_pool_blocks_orphan_total ${stats[3][0]?.n ?? 0}`,
            "# HELP b3chain_pool_payouts_total Total payouts sent",
            "# TYPE b3chain_pool_payouts_total counter",
            `b3chain_pool_payouts_total ${stats[4][0]?.n ?? 0}`,
            "# HELP b3chain_pool_payouts_b3c_total Total B3C paid out",
            "# TYPE b3chain_pool_payouts_b3c_total counter",
            `b3chain_pool_payouts_b3c_total ${stats[5][0]?.n ?? 0}`,
            "# HELP b3chain_pool_hashrate_1h Estimated pool hashrate over last hour (H/s)",
            "# TYPE b3chain_pool_hashrate_1h gauge",
            `b3chain_pool_hashrate_1h ${stats[6][0]?.n ?? 0}`,
        ];
        res.type("text/plain").send(lines.join("\n") + "\n");
    });
    return r;
}
