import { Router, Request } from "express";
import * as argon2 from "argon2";
import { query, tx } from "../../lib/db";
import { config } from "../../config";
import { requireAuth, requireVerified, AuthedUser } from "../middleware/auth";
import { setFlash } from "../middleware/session";
import { isValidB3AddressForNetwork } from "../../lib/address";
import { validateAddress } from "../../lib/rpc";

export function dashboardRoutes(): Router {
    const r = Router();

    r.use(requireAuth);

    r.get("/", requireVerified, async (req, res) => {
        const u = (req as Request & { user: AuthedUser }).user;
        const stats = await query<{ h: string; w: string; s: string; balance: string; pending: string }>(
            `SELECT
               (SELECT COALESCE(SUM(diff)*4294967296.0/300.0, 0) FROM shares
                  WHERE user_id = $1
                    AND submitted_at >= NOW() - interval '5 minutes')::float8::text AS h,
               (SELECT COUNT(*) FROM workers
                  WHERE user_id = $1
                    AND last_seen_at >= NOW() - interval '10 minutes')::text AS w,
               (SELECT COUNT(*) FROM shares
                  WHERE user_id = $1
                    AND submitted_at >= NOW() - interval '1 hour')::text AS s,
               (SELECT COALESCE(SUM(delta_b3c), 0) FROM balance_entries
                  WHERE user_id = $1)::text AS balance,
               (SELECT COALESCE(SUM(delta_b3c), 0) FROM balance_entries
                  WHERE user_id = $1 AND payout_id IS NULL AND kind = 'credit')::text AS pending`,
            [u.id]
        );
        const buckets = await query(
            `SELECT bucket_at, hashrate_hps
               FROM hashrate_buckets
              WHERE user_id = $1 AND bucket_at >= NOW() - interval '24 hours'
              ORDER BY bucket_at ASC`,
            [u.id]
        );
        const recentShares = await query(
            `SELECT s.id, s.diff, s.is_block, s.block_hash, s.submitted_at, w.name AS worker_name
               FROM shares s
               JOIN workers w ON w.id = s.worker_id
              WHERE s.user_id = $1
              ORDER BY s.id DESC LIMIT 25`,
            [u.id]
        );
        const recentBlocks = await query(
            `SELECT id, height, hash, reward_b3c, confirmations,
                    is_confirmed, is_orphan, found_at
               FROM blocks
              WHERE finder_user_id = $1
              ORDER BY id DESC LIMIT 10`,
            [u.id]
        );
        res.render("dashboard/index", {
            title: "Dashboard",
            stats: stats[0]!,
            buckets,
            recentShares,
            recentBlocks,
        });
    });

    r.get("/workers", requireVerified, async (req, res) => {
        const u = (req as Request & { user: AuthedUser }).user;
        const workers = await query(
            `SELECT w.id, w.name, w.last_seen_at,
                    COALESCE((SELECT SUM(diff)*4294967296.0/3600.0 FROM shares
                                 WHERE worker_id = w.id
                                   AND submitted_at >= NOW() - interval '1 hour'), 0)::float8 AS h_hour,
                    COALESCE((SELECT COUNT(*) FROM shares
                                 WHERE worker_id = w.id), 0) AS shares_total
               FROM workers w
              WHERE w.user_id = $1
              ORDER BY w.last_seen_at DESC NULLS LAST`,
            [u.id]
        );
        res.render("dashboard/workers", { title: "Workers", workers });
    });

    r.get("/payouts", requireVerified, async (req, res) => {
        const u = (req as Request & { user: AuthedUser }).user;
        const rows = await query(
            `SELECT p.id, p.txid, p.confirmed, p.sent_at, pr.amount_b3c, pr.address
               FROM payouts p
               JOIN payout_recipients pr ON pr.payout_id = p.id
              WHERE pr.user_id = $1
              ORDER BY p.id DESC LIMIT 100`,
            [u.id]
        );
        const balance = await query<{ b: string }>(
            `SELECT COALESCE(SUM(delta_b3c),0)::text AS b FROM balance_entries WHERE user_id = $1`,
            [u.id]
        );
        res.render("dashboard/payouts", {
            title: "Payouts",
            payouts: rows,
            balance: parseFloat(balance[0]!.b),
            minimum: u.minimumPayoutB3c,
        });
    });

    r.get("/settings", requireVerified, (req, res) => {
        const u = (req as Request & { user: AuthedUser }).user;
        res.render("dashboard/settings", { title: "Settings", user: u, err: null });
    });

    r.post("/settings/payout", requireVerified, async (req, res) => {
        const u = (req as Request & { user: AuthedUser }).user;
        const addr = String(req.body.payout_address ?? "").trim();
        const min = parseFloat(String(req.body.minimum_payout_b3c ?? ""));
        if (!isValidB3AddressForNetwork(addr, config.network)) {
            res.status(400).render("dashboard/settings", {
                title: "Settings",
                user: u,
                err: `Address is not a valid ${config.network} B3Chain address`,
            });
            return;
        }
        try {
            const ok = await validateAddress(addr);
            if (!ok.isvalid) throw new Error("rejected by node");
        } catch (e) {
            res.status(400).render("dashboard/settings", {
                title: "Settings",
                user: u,
                err: `Address rejected by b3chaind: ${(e as Error).message}`,
            });
            return;
        }
        if (!Number.isFinite(min) || min < 0.01 || min > 1000) {
            res.status(400).render("dashboard/settings", {
                title: "Settings",
                user: u,
                err: "Minimum payout must be between 0.01 and 1000 B3C",
            });
            return;
        }
        await query(
            "UPDATE users SET payout_address = $1, minimum_payout_b3c = $2 WHERE id = $3",
            [addr, min.toFixed(8), u.id]
        );
        setFlash(req, "success", "Payout settings saved.");
        res.redirect("/dashboard/settings");
    });

    r.post("/settings/password", requireVerified, async (req, res) => {
        const u = (req as Request & { user: AuthedUser }).user;
        const oldPw = String(req.body.old_password ?? "");
        const newPw = String(req.body.new_password ?? "");
        if (newPw.length < 10) {
            res.status(400).render("dashboard/settings", { title: "Settings", user: u, err: "New password too short" });
            return;
        }
        const rows = await query<{ password_hash: string }>(
            "SELECT password_hash FROM users WHERE id = $1",
            [u.id]
        );
        const ok = rows.length > 0 ? await argon2.verify(rows[0]!.password_hash, oldPw).catch(() => false) : false;
        if (!ok) {
            res.status(400).render("dashboard/settings", { title: "Settings", user: u, err: "Old password is wrong" });
            return;
        }
        const hash = await argon2.hash(newPw, { type: argon2.argon2id });
        await query("UPDATE users SET password_hash = $1 WHERE id = $2", [hash, u.id]);
        setFlash(req, "success", "Password changed.");
        res.redirect("/dashboard/settings");
    });

    r.get("/api/buckets", requireVerified, async (req, res) => {
        const u = (req as Request & { user: AuthedUser }).user;
        const range = String(req.query.range ?? "24h");
        const interval = range === "30d" ? "30 days" : range === "7d" ? "7 days" : range === "1h" ? "1 hour" : "24 hours";
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
