import { Router } from "express";
import { query } from "../../lib/db";
import { config } from "../../config";
import { isValidB3AddressForNetwork } from "../../lib/address";
import { requireAdmin } from "../middleware/auth";
import { fetchStratumStats } from "../socket";

export function adminRoutes(): Router {
    const r = Router();
    r.use(requireAdmin);

    r.get("/", async (_req, res) => {
        const candidates = await query<{
            id: string;
            email: string;
            email_verified: boolean;
            payout_address: string | null;
            minimum_payout_b3c: string;
            balance: string;
        }>(
            `SELECT u.id, u.email, u.email_verified, u.payout_address, u.minimum_payout_b3c,
                    COALESCE((SELECT SUM(delta_b3c) FROM balance_entries WHERE user_id = u.id), 0)::text AS balance
               FROM users u
              ORDER BY u.id ASC
              LIMIT 200`
        );
        const ready = candidates.filter((c) => {
            const balance = parseFloat(c.balance);
            const min = parseFloat(c.minimum_payout_b3c);
            return c.email_verified
                && !!c.payout_address
                && isValidB3AddressForNetwork(c.payout_address, config.network)
                && balance >= min
                && balance > 0;
        });
        const orphans = await query(
            `SELECT height, hash, found_at FROM blocks WHERE is_orphan ORDER BY id DESC LIMIT 20`
        );
        const live = await fetchStratumStats();
        res.render("admin", {
            title: "Admin",
            ready,
            orphans,
            connections: live.connections ?? [],
            chainTip: live.lastJobHeight,
        });
    });

    return r;
}
