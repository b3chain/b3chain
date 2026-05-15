// Entry point for the b3chain-pool-web service.

import * as http from "http";
import { config } from "../config";
import { makeLogger } from "../lib/logger";
import { buildApp } from "./server";
import { SocketIoBus } from "./socket";

const log = makeLogger("web-main");

function main(): void {
    const app = buildApp();
    const server = http.createServer(app);
    const bus = new SocketIoBus(server);

    server.listen(config.web.port, config.web.bind, () => {
        log.info({ bind: config.web.bind, port: config.web.port }, "web listening");
    });

    const shutdown = (sig: string) => {
        log.info({ sig }, "shutdown");
        bus.stop();
        server.close(() => process.exit(0));
        setTimeout(() => process.exit(1), 5000).unref();
    };
    process.on("SIGTERM", () => shutdown("SIGTERM"));
    process.on("SIGINT", () => shutdown("SIGINT"));
}

main();
