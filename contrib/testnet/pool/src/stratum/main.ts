// Entry point for the b3chain-pool-stratum service.

import { config } from "../config";
import { makeLogger } from "../lib/logger";
import { JobManager } from "./job-manager";
import { StratumServer } from "./server";
import { IpcClient } from "../lib/ipc";
import * as http from "http";

const log = makeLogger("stratum-main");

async function main(): Promise<void> {
    const ipc = new IpcClient(config.pool.shareSocket);
    ipc.on("connect", () => log.info("ipc connected to pool daemon"));
    ipc.on("disconnect", () => log.warn("ipc disconnected from pool daemon"));
    ipc.start();

    const jobs = new JobManager(makeLogger("jobs"));
    const server = new StratumServer(jobs, ipc, makeLogger("stratum"));

    jobs.start();
    await server.listen();

    // Tiny HTTP endpoint on a sibling port for /stats consumption by the
    // web service (no auth, bind localhost only).
    const stats = http.createServer((req, res) => {
        if (req.url === "/stats") {
            const body = JSON.stringify({
                miners: server.clientCount(),
                hashrate: server.estimatedHashrate(),
                lastJobHeight: jobs.getCurrent()?.height ?? null,
            });
            res.writeHead(200, { "content-type": "application/json" });
            res.end(body);
            return;
        }
        res.writeHead(404);
        res.end();
    });
    stats.listen(3334, "127.0.0.1", () => log.info("stratum stats endpoint on 127.0.0.1:3334"));

    const shutdown = async (sig: string) => {
        log.info({ sig }, "shutdown");
        jobs.stop();
        ipc.stop();
        await server.close();
        await new Promise<void>((res) => stats.close(() => res()));
        process.exit(0);
    };
    process.on("SIGTERM", () => void shutdown("SIGTERM"));
    process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((e) => {
    log.error({ err: e.message, stack: e.stack }, "fatal");
    process.exit(1);
});
