// Entry point for the b3chain-pool-tp service.

import { config } from "../../config";
import { makeLogger } from "../../lib/logger";
import { addressToScriptPubKey } from "../../lib/address";
import { TpPoller } from "./poller";
import { Sv2TpServer } from "./server";

const log = makeLogger("sv2-tp-main");

async function main(): Promise<void> {
    if (!config.rpc.payoutAddress) throw new Error("B3POOL_PAYOUT_ADDRESS missing");
    if (!addressToScriptPubKey(config.rpc.payoutAddress)) {
        throw new Error(`B3POOL_PAYOUT_ADDRESS=${config.rpc.payoutAddress} invalid`);
    }
    log.info({
        bind: config.tp.bind, port: config.tp.port, pollMs: config.tp.pollMs,
    }, "tp boot");

    const poller = new TpPoller(makeLogger("tp-poll"));
    const server = new Sv2TpServer({
        bind: config.tp.bind,
        port: config.tp.port,
        poller,
        log: makeLogger("tp-srv"),
    });

    poller.start();
    await server.listen();

    const shutdown = async (sig: string) => {
        log.info({ sig }, "shutdown");
        poller.stop();
        await server.close();
        process.exit(0);
    };
    process.on("SIGTERM", () => void shutdown("SIGTERM"));
    process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((e) => {
    log.error({ err: e.message, stack: e.stack }, "fatal");
    process.exit(1);
});
