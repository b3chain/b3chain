import cookieSession from "cookie-session";
import { Request, Response, NextFunction } from "express";
import { config } from "../../config";

export function sessionMiddleware() {
    return cookieSession({
        name: "b3pool",
        keys: [config.web.cookieSecret],
        maxAge: config.web.sessionHours * 3600 * 1000,
        sameSite: "lax",
        httpOnly: true,
        secure: config.web.baseUrl.startsWith("https://"),
    });
}

export interface PoolSession {
    userId?: number;
    pendingTotpUserId?: number;
    flashSuccess?: string;
    flashError?: string;
}

declare module "express-serve-static-core" {
    interface Request {
        // cookie-session attaches `req.session` as `Cookie | null` typed dynamically.
        session: (PoolSession & { [k: string]: unknown }) | null;
    }
}

export function consumeFlash(req: Request, res: Response, next: NextFunction) {
    const s = req.session as PoolSession | null;
    if (!s) return next();
    res.locals.flashSuccess = s.flashSuccess;
    res.locals.flashError = s.flashError;
    delete s.flashSuccess;
    delete s.flashError;
    next();
}

export function setFlash(req: Request, kind: "success" | "error", msg: string): void {
    const s = req.session as PoolSession | null;
    if (!s) return;
    if (kind === "success") s.flashSuccess = msg;
    else s.flashError = msg;
}
