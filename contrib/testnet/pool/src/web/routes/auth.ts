import { Router, Request, Response } from "express";
import * as argon2 from "argon2";
import * as crypto from "crypto";
import { authenticator } from "otplib";
import qrcode from "qrcode";
import { query, tx } from "../../lib/db";
import { config } from "../../config";
import { sendEmail } from "../../email/send";
import { authLimiter, signupLimiter, passwordResetLimiter } from "../middleware/ratelimit";
import { setFlash } from "../middleware/session";
import { isValidB3AddressForNetwork } from "../../lib/address";

function isEmail(s: string): boolean {
    return typeof s === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s) && s.length < 256;
}

function genToken(): string {
    return crypto.randomBytes(24).toString("hex");
}

export function authRoutes(): Router {
    const r = Router();

    r.get("/signup", (_req, res) => res.render("auth/signup", { title: "Create an account", err: null, email: "" }));

    r.post("/signup", signupLimiter, async (req: Request, res: Response) => {
        const email = String(req.body.email ?? "").trim().toLowerCase();
        const password = String(req.body.password ?? "");
        const payoutAddress = String(req.body.payout_address ?? "").trim();
        if (!isEmail(email)) {
            res.status(400).render("auth/signup", { title: "Create an account", err: "Invalid email", email });
            return;
        }
        if (password.length < 10) {
            res.status(400).render("auth/signup", {
                title: "Create an account",
                err: "Password must be at least 10 characters",
                email,
            });
            return;
        }
        if (payoutAddress && !isValidB3AddressForNetwork(payoutAddress, config.network)) {
            res.status(400).render("auth/signup", {
                title: "Create an account",
                err: `Payout address is not a valid ${config.network} B3Chain address`,
                email,
            });
            return;
        }
        const exists = await query("SELECT 1 FROM users WHERE email = $1", [email]);
        if (exists.length > 0) {
            res.status(400).render("auth/signup", {
                title: "Create an account",
                err: "Email already registered",
                email,
            });
            return;
        }
        const hash = await argon2.hash(password, { type: argon2.argon2id });
        const token = genToken();
        await tx(async (c) => {
            const ins = await c.query<{ id: string }>(
                `INSERT INTO users(email, password_hash, payout_address)
                 VALUES ($1, $2, $3) RETURNING id`,
                [email, hash, payoutAddress || null]
            );
            const uid = parseInt(ins.rows[0]!.id, 10);
            await c.query(
                `INSERT INTO email_verify_tokens(token, user_id, expires_at)
                 VALUES ($1, $2, NOW() + interval '2 days')`,
                [token, uid]
            );
        });
        const verifyUrl = `${config.web.baseUrl}/auth/verify-email?token=${token}`;
        await sendEmail(
            email,
            "Verify your B3Chain Pool account",
            `Welcome to the B3Chain mining pool.\n\nClick to confirm your email:\n${verifyUrl}\n\nLink expires in 48 hours.\n`
        ).catch(() => undefined);
        setFlash(req, "success", "Account created. Check your inbox to confirm your email.");
        res.redirect("/auth/login");
    });

    r.get("/verify-email", async (req, res) => {
        const token = String(req.query.token ?? "");
        if (!token) {
            res.render("auth/verify", { title: "Verify email", message: "Check your inbox for a verification link." });
            return;
        }
        const rows = await query<{ user_id: string }>(
            `SELECT user_id FROM email_verify_tokens WHERE token = $1 AND expires_at > NOW()`,
            [token]
        );
        if (rows.length === 0) {
            res.status(400).render("auth/verify", { title: "Verify email", message: "Invalid or expired verification link." });
            return;
        }
        const uid = parseInt(rows[0]!.user_id, 10);
        await tx(async (c) => {
            await c.query("UPDATE users SET email_verified = TRUE WHERE id = $1", [uid]);
            await c.query("DELETE FROM email_verify_tokens WHERE user_id = $1", [uid]);
        });
        setFlash(req, "success", "Email verified. You can now log in.");
        res.redirect("/auth/login");
    });

    r.get("/login", (req, res) => {
        res.render("auth/login", {
            title: "Log in",
            err: null,
            email: "",
            next: String(req.query.next ?? "/dashboard"),
        });
    });

    r.post("/login", authLimiter, async (req, res) => {
        const email = String(req.body.email ?? "").trim().toLowerCase();
        const password = String(req.body.password ?? "");
        const next = String(req.body.next ?? "/dashboard");
        const rows = await query<{
            id: string;
            password_hash: string;
            email_verified: boolean;
            totp_enabled: boolean;
        }>(
            `SELECT id, password_hash, email_verified, totp_enabled FROM users WHERE email = $1 LIMIT 1`,
            [email]
        );
        if (rows.length === 0) {
            res.status(400).render("auth/login", { title: "Log in", err: "Invalid email or password", email, next });
            return;
        }
        const row = rows[0]!;
        let ok = false;
        try {
            ok = await argon2.verify(row.password_hash, password);
        } catch {
            ok = false;
        }
        if (!ok) {
            res.status(400).render("auth/login", { title: "Log in", err: "Invalid email or password", email, next });
            return;
        }
        const sess = req.session as Record<string, unknown> | null;
        if (!sess) {
            res.status(500).render("error", { title: "Server error", message: "Session unavailable" });
            return;
        }
        if (row.totp_enabled) {
            sess.pendingTotpUserId = parseInt(row.id, 10);
            sess.pendingTotpNext = next;
            res.redirect("/auth/2fa-verify");
            return;
        }
        sess.userId = parseInt(row.id, 10);
        await query("UPDATE users SET last_login_at = NOW() WHERE id = $1", [row.id]);
        res.redirect(safeNext(next));
    });

    r.post("/logout", (req, res) => {
        if (req.session) (req.session as Record<string, unknown>).userId = undefined;
        res.redirect("/");
    });

    r.get("/forgot", (_req, res) =>
        res.render("auth/forgot", { title: "Reset password", err: null, message: null })
    );

    r.post("/forgot", passwordResetLimiter, async (req, res) => {
        const email = String(req.body.email ?? "").trim().toLowerCase();
        if (!isEmail(email)) {
            res.status(400).render("auth/forgot", { title: "Reset password", err: "Invalid email", message: null });
            return;
        }
        const rows = await query<{ id: string }>("SELECT id FROM users WHERE email = $1", [email]);
        // Always show success even if no such user (don't leak account existence).
        if (rows.length > 0) {
            const token = genToken();
            await query(
                `INSERT INTO password_reset_tokens(token, user_id, expires_at)
                 VALUES ($1, $2, NOW() + interval '2 hours')`,
                [token, rows[0]!.id]
            );
            const url = `${config.web.baseUrl}/auth/reset?token=${token}`;
            await sendEmail(
                email,
                "Reset your B3Chain Pool password",
                `Open this link within 2 hours to reset your password:\n${url}\n`
            ).catch(() => undefined);
        }
        res.render("auth/forgot", {
            title: "Reset password",
            err: null,
            message: "If that email exists in our system, a reset link is on its way.",
        });
    });

    r.get("/reset", async (req, res) => {
        const token = String(req.query.token ?? "");
        const rows = await query("SELECT 1 FROM password_reset_tokens WHERE token = $1 AND expires_at > NOW()", [token]);
        if (rows.length === 0) {
            res.status(400).render("error", { title: "Invalid link", message: "This reset link is invalid or expired." });
            return;
        }
        res.render("auth/reset", { title: "Set a new password", token, err: null });
    });

    r.post("/reset", authLimiter, async (req, res) => {
        const token = String(req.body.token ?? "");
        const password = String(req.body.password ?? "");
        if (password.length < 10) {
            res.status(400).render("auth/reset", { title: "Set a new password", token, err: "Password too short" });
            return;
        }
        const rows = await query<{ user_id: string }>(
            "SELECT user_id FROM password_reset_tokens WHERE token = $1 AND expires_at > NOW()",
            [token]
        );
        if (rows.length === 0) {
            res.status(400).render("error", { title: "Invalid link", message: "This reset link is invalid or expired." });
            return;
        }
        const uid = parseInt(rows[0]!.user_id, 10);
        const hash = await argon2.hash(password, { type: argon2.argon2id });
        await tx(async (c) => {
            await c.query("UPDATE users SET password_hash = $1 WHERE id = $2", [hash, uid]);
            await c.query("DELETE FROM password_reset_tokens WHERE user_id = $1", [uid]);
        });
        setFlash(req, "success", "Password updated. Please log in.");
        res.redirect("/auth/login");
    });

    r.get("/2fa-setup", async (req, res) => {
        const sess = req.session as { userId?: number } | null;
        if (!sess?.userId) {
            res.redirect("/auth/login");
            return;
        }
        const u = await query<{ totp_enabled: boolean; email: string }>(
            "SELECT totp_enabled, email FROM users WHERE id = $1",
            [sess.userId]
        );
        if (u.length === 0) {
            res.redirect("/auth/login");
            return;
        }
        if (u[0]!.totp_enabled) {
            res.render("auth/2fa-setup", { title: "Two-factor auth", enabled: true, otpauthUrl: null, qrDataUrl: null, secret: null, err: null });
            return;
        }
        const secret = authenticator.generateSecret();
        (sess as Record<string, unknown>).pendingTotpSecret = secret;
        const otpauth = authenticator.keyuri(u[0]!.email, "B3ChainPool", secret);
        const qrDataUrl = await qrcode.toDataURL(otpauth);
        res.render("auth/2fa-setup", { title: "Two-factor auth", enabled: false, otpauthUrl: otpauth, qrDataUrl, secret, err: null });
    });

    r.post("/2fa-setup", async (req, res) => {
        const sess = req.session as { userId?: number; pendingTotpSecret?: string } | null;
        if (!sess?.userId || !sess.pendingTotpSecret) {
            res.redirect("/auth/login");
            return;
        }
        const code = String(req.body.code ?? "").trim();
        if (!authenticator.check(code, sess.pendingTotpSecret)) {
            const u = await query<{ email: string }>("SELECT email FROM users WHERE id = $1", [sess.userId]);
            const otpauth = authenticator.keyuri(u[0]!.email, "B3ChainPool", sess.pendingTotpSecret);
            const qrDataUrl = await qrcode.toDataURL(otpauth);
            res.status(400).render("auth/2fa-setup", {
                title: "Two-factor auth",
                enabled: false,
                otpauthUrl: otpauth,
                qrDataUrl,
                secret: sess.pendingTotpSecret,
                err: "Code did not match. Try again.",
            });
            return;
        }
        await query(
            "UPDATE users SET totp_secret = $1, totp_enabled = TRUE WHERE id = $2",
            [sess.pendingTotpSecret, sess.userId]
        );
        delete (sess as Record<string, unknown>).pendingTotpSecret;
        setFlash(req, "success", "Two-factor authentication enabled.");
        res.redirect("/dashboard/settings");
    });

    r.post("/2fa-disable", async (req, res) => {
        const sess = req.session as { userId?: number } | null;
        if (!sess?.userId) {
            res.redirect("/auth/login");
            return;
        }
        await query(
            "UPDATE users SET totp_secret = NULL, totp_enabled = FALSE WHERE id = $1",
            [sess.userId]
        );
        setFlash(req, "success", "Two-factor authentication disabled.");
        res.redirect("/dashboard/settings");
    });

    r.get("/2fa-verify", (req, res) => {
        const sess = req.session as { pendingTotpUserId?: number } | null;
        if (!sess?.pendingTotpUserId) {
            res.redirect("/auth/login");
            return;
        }
        res.render("auth/2fa-verify", { title: "Two-factor verification", err: null });
    });

    r.post("/2fa-verify", authLimiter, async (req, res) => {
        const sess = req.session as { pendingTotpUserId?: number; pendingTotpNext?: string } | null;
        if (!sess?.pendingTotpUserId) {
            res.redirect("/auth/login");
            return;
        }
        const code = String(req.body.code ?? "").trim();
        const u = await query<{ totp_secret: string }>(
            "SELECT totp_secret FROM users WHERE id = $1",
            [sess.pendingTotpUserId]
        );
        if (u.length === 0 || !u[0]!.totp_secret || !authenticator.check(code, u[0]!.totp_secret)) {
            res.status(400).render("auth/2fa-verify", { title: "Two-factor verification", err: "Code did not match." });
            return;
        }
        const uid = sess.pendingTotpUserId;
        const next = sess.pendingTotpNext ?? "/dashboard";
        delete (sess as Record<string, unknown>).pendingTotpUserId;
        delete (sess as Record<string, unknown>).pendingTotpNext;
        (sess as Record<string, unknown>).userId = uid;
        await query("UPDATE users SET last_login_at = NOW() WHERE id = $1", [uid]);
        res.redirect(safeNext(next));
    });

    return r;
}

function safeNext(next: string): string {
    if (typeof next !== "string" || !next.startsWith("/") || next.startsWith("//")) return "/dashboard";
    return next;
}
