import { Router } from "express";
import * as http from "http";
import { query } from "../../lib/db";
import { config } from "../../config";
import { isValidB3AddressForNetwork } from "../../lib/address";
import { requireAdmin } from "../middleware/auth";
import { fetchStratumStats } from "../socket";
import { listAccountSlots, PgPassportStore } from "../../lib/passports";

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
        let slotRows: Awaited<ReturnType<typeof listAccountSlots>> = [];
        try {
            slotRows = await listAccountSlots();
        } catch {
            slotRows = [];
        }
        const accounts = new Map<string, { id: string; email: string; slots: Array<{ slotNo: number; pubkey: string | null; lockedAt: string | null }> }>();
        for (const row of slotRows) {
            let account = accounts.get(row.userId);
            if (!account) {
                account = { id: row.userId, email: row.email, slots: [] };
                accounts.set(row.userId, account);
            }
            if (row.slotNo !== null) {
                account.slots.push({ slotNo: row.slotNo, pubkey: row.pubkey, lockedAt: row.lockedAt });
            }
        }
        res.render("admin", {
            title: "Admin",
            ready,
            orphans,
            connections: live.connections ?? [],
            chainTip: live.lastJobHeight,
            accounts: [...accounts.values()],
        });
    });

    const passports = new PgPassportStore();
    r.post("/api/users/:id/device-slots", async (req, res) => {
        const id = parseInt(String(req.params.id), 10);
        if (!Number.isInteger(id) || id <= 0) {
            res.status(400).json({ ok: false });
            return;
        }
        const users = await query<{ id: string }>("SELECT id::text AS id FROM users WHERE id = $1", [id]);
        if (!users.length) {
            res.status(404).json({ ok: false });
            return;
        }
        const slot = await passports.addEmpty(id);
        notifyDeviceSlot(id);
        if (req.is("json")) {
            res.json({ ok: true, slotNo: slot.slotNo, id: slot.id });
            return;
        }
        res.redirect("/admin");
    });

    return r;
}

function notifyDeviceSlot(userId: number): void {
    const body = JSON.stringify({ userId });
    const req = http.request(
        {
            host: "127.0.0.1",
            port: 3334,
            method: "POST",
            path: "/device-slots",
            headers: {
                "content-type": "application/json",
                "content-length": Buffer.byteLength(body),
            },
            timeout: 1500,
        },
        (res) => {
            res.resume();
        },
    );
    req.on("error", () => {});
    req.on("timeout", () => req.destroy());
    req.end(body);
}
