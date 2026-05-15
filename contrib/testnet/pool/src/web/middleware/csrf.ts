import { Request, Response, NextFunction } from "express";
import crypto from "crypto";

// Lightweight per-session CSRF: token lives in session, must round-trip via
// either a hidden form field `_csrf` or the `x-csrf-token` header.

const TOKEN_KEY = "_csrf_token";

export function csrfTokenMiddleware(req: Request, res: Response, next: NextFunction): void {
    const sess = req.session as Record<string, unknown> | null;
    if (!sess) return next();
    let token = sess[TOKEN_KEY] as string | undefined;
    if (!token) {
        token = crypto.randomBytes(24).toString("hex");
        sess[TOKEN_KEY] = token;
    }
    res.locals.csrfToken = token;
    next();
}

export function csrfProtect(req: Request, res: Response, next: NextFunction): void {
    if (req.method === "GET" || req.method === "HEAD" || req.method === "OPTIONS") return next();
    const sess = req.session as Record<string, unknown> | null;
    const expected = sess?.[TOKEN_KEY] as string | undefined;
    const got =
        (req.body && typeof req.body === "object" && (req.body as Record<string, unknown>)._csrf) ||
        req.header("x-csrf-token");
    if (!expected || !got || typeof got !== "string" || got !== expected) {
        res.status(403).render("error", { title: "Forbidden", message: "CSRF token invalid or missing." });
        return;
    }
    next();
}
