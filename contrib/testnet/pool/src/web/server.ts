import express, { Application } from "express";
import * as path from "path";
import { sessionMiddleware, consumeFlash } from "./middleware/session";
import { csrfTokenMiddleware, csrfProtect } from "./middleware/csrf";
import { loadCurrentUser } from "./middleware/auth";
import { publicRoutes } from "./routes/public";
import { authRoutes } from "./routes/auth";
import { dashboardRoutes } from "./routes/dashboard";
import { metricsRoutes } from "./routes/metrics";
import { apiLimiter } from "./middleware/ratelimit";
import { config } from "../config";

export function buildApp(): Application {
    const app = express();
    // EJS templates live in src/web/views (tsc only emits .ts -> .js,
    // it does not copy .ejs templates into dist/). Resolve via the
    // project root so the same path works from dist/web (compiled) or
    // src/web (tsx dev).
    const projectRoot = path.resolve(__dirname, "..", "..");
    const viewsDir = path.join(projectRoot, "src", "web", "views");
    app.set("views", viewsDir);
    app.set("view engine", "ejs");
    app.set("trust proxy", 1);
    app.disable("x-powered-by");

    app.use(express.urlencoded({ extended: false, limit: "32kb" }));
    app.use(express.json({ limit: "32kb" }));
    app.use(express.static(path.join(projectRoot, "public"), { maxAge: "7d" }));

    app.use(sessionMiddleware());
    app.use(consumeFlash);
    app.use(csrfTokenMiddleware);
    app.use(loadCurrentUser);

    app.use((req, res, next) => {
        res.locals.network = config.network;
        res.locals.feePercent = config.pool.feePercent;
        res.locals.path = req.path;
        next();
    });

    app.use(metricsRoutes());
    app.use("/api/", apiLimiter);
    app.use(csrfProtect);

    app.use("/", publicRoutes());
    app.use("/auth", authRoutes());
    app.use("/dashboard", dashboardRoutes());

    app.use((_req, res) => {
        res.status(404).render("error", { title: "Not found", message: "Page not found." });
    });
    app.use((err: Error, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
        console.error("[web] error:", err);
        res.status(500).render("error", { title: "Server error", message: "Something went wrong." });
    });

    return app;
}
