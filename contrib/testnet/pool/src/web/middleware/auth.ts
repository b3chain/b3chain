import { Request, Response, NextFunction } from "express";
import { query } from "../../lib/db";

export interface AuthedUser {
    id: number;
    email: string;
    emailVerified: boolean;
    totpEnabled: boolean;
    payoutAddress: string | null;
    minimumPayoutB3c: number;
    isAdmin: boolean;
}

export async function loadCurrentUser(
    req: Request,
    res: Response,
    next: NextFunction
): Promise<void> {
    const sess = req.session as { userId?: number } | null;
    const uid = sess?.userId;
    if (!uid) {
        res.locals.user = null;
        return next();
    }
    const rows = await query<{
        id: string;
        email: string;
        email_verified: boolean;
        totp_enabled: boolean;
        payout_address: string | null;
        minimum_payout_b3c: string;
        is_admin: boolean;
    }>(
        `SELECT id, email, email_verified, totp_enabled, payout_address,
                minimum_payout_b3c, is_admin
           FROM users WHERE id = $1 LIMIT 1`,
        [uid]
    );
    if (rows.length === 0) {
        if (req.session) delete (req.session as Record<string, unknown>).userId;
        res.locals.user = null;
        return next();
    }
    const u = rows[0]!;
    const user: AuthedUser = {
        id: parseInt(u.id, 10),
        email: u.email,
        emailVerified: u.email_verified,
        totpEnabled: u.totp_enabled,
        payoutAddress: u.payout_address,
        minimumPayoutB3c: parseFloat(u.minimum_payout_b3c),
        isAdmin: u.is_admin,
    };
    (req as Request & { user: AuthedUser }).user = user;
    res.locals.user = user;
    next();
}

export function requireAuth(req: Request, res: Response, next: NextFunction): void {
    const u = (req as Request & { user?: AuthedUser }).user;
    if (!u) {
        res.redirect("/auth/login?next=" + encodeURIComponent(req.originalUrl));
        return;
    }
    next();
}

export function requireVerified(req: Request, res: Response, next: NextFunction): void {
    const u = (req as Request & { user?: AuthedUser }).user;
    if (!u) {
        res.redirect("/auth/login");
        return;
    }
    if (!u.emailVerified) {
        res.redirect("/auth/verify-email");
        return;
    }
    next();
}
