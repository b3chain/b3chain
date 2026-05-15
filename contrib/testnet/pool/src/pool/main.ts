// Entry point for the b3chain-pool-daemon service.
//
// Wires together: IPC server (receives shares from stratum), share writer
// (batched DB inserts + 1-minute hashrate buckets), block recorder,
// block confirmer (polls getblock), PPLNS crediter (called by confirmer),
// hourly payout job.

import { config } from "../config";
import { makeLogger } from "../lib/logger";
import { IpcServer, IpcMessage } from "../lib/ipc";
import { ShareWriter } from "./share-writer";
import { BlockConfirmer } from "./block-confirmer";
import { PayoutJob } from "./payout-job";
import { recordFoundBlock } from "./block-recorder";

const log = makeLogger("pool-daemon");

async function main(): Promise<void> {
    const ipc = new IpcServer(config.pool.shareSocket);
    const writer = new ShareWriter(makeLogger("share-writer"));
    const confirmer = new BlockConfirmer(makeLogger("block-confirmer"));
    const payouts = new PayoutJob(makeLogger("payout-job"));

    ipc.on("message", (msg: IpcMessage) => {
        if (msg.type !== "share") return;
        void writer.accept(msg);
        if (msg.isBlock) void recordFoundBlock(msg, log);
    });
    ipc.on("client-error", (e) => log.warn({ err: (e as Error).message }, "ipc client error"));

    await ipc.listen();
    log.info({ socket: config.pool.shareSocket }, "ipc listening");

    writer.start();
    confirmer.start();
    payouts.start();

    const shutdown = async (sig: string) => {
        log.info({ sig }, "shutdown");
        confirmer.stop();
        payouts.stop();
        await writer.stop();
        await ipc.close();
        process.exit(0);
    };
    process.on("SIGTERM", () => void shutdown("SIGTERM"));
    process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((e) => {
    log.error({ err: e.message, stack: e.stack }, "fatal");
    process.exit(1);
});
