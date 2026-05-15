// Entry point for the b3chain-pool-stratum-v2 service.
//
// Mirrors stratum/main.ts but speaks the Stratum V2 Mining Protocol over
// Noise NX. Reuses the same JobManager, IPC client, and validateShare()
// path so SV2 shares land in the same PPLNS pipeline as V1 shares.

import { config } from "../../config";
import { makeLogger } from "../../lib/logger";
import { JobManager } from "../../stratum/job-manager";
import { addressToScriptPubKey } from "../../lib/address";
import { IpcClient } from "../../lib/ipc";
import { Sv2MiningServer } from "./server";
import { Sv2JdServer } from "../jd/server";
import { loadOrCreateAuthorityKey, loadOrCreateStaticKey } from "../lib/keys";
import { loadOrIssueCertificate } from "../lib/cert";

const log = makeLogger("sv2-stratum-main");

async function main(): Promise<void> {
    if (!config.sv2.enable) {
        log.warn("B3POOL_SV2_ENABLE=false; refusing to start");
        process.exit(0);
    }
    if (!config.rpc.payoutAddress) {
        throw new Error("B3POOL_PAYOUT_ADDRESS is not set; the SV2 pool needs a coinbase recipient");
    }
    if (!addressToScriptPubKey(config.rpc.payoutAddress)) {
        throw new Error(`B3POOL_PAYOUT_ADDRESS=${config.rpc.payoutAddress} is not a valid bech32 address`);
    }

    const authority = loadOrCreateAuthorityKey(config.sv2.authorityKeyFile);
    const stat = loadOrCreateStaticKey(config.sv2.staticKeyFile);
    const cert = loadOrIssueCertificate(
        config.sv2.certFile,
        authority,
        stat.pub,
        config.sv2.certValidityDays * 24 * 60 * 60,
    );

    log.info({
        bind: config.sv2.bind, port: config.sv2.port,
        authorityPub: Buffer.from(authority.pub).toString("hex"),
        staticPub: Buffer.from(stat.pub).toString("hex"),
        certNotValidAfter: new Date(cert.notValidAfter * 1000).toISOString(),
    }, "sv2 pool boot");

    const ipc = new IpcClient(config.pool.shareSocket);
    ipc.on("connect", () => log.info("sv2 ipc connected"));
    ipc.on("disconnect", () => log.warn("sv2 ipc disconnected"));
    ipc.start();

    const jobs = new JobManager(makeLogger("sv2-jobs"));
    const server = new Sv2MiningServer({
        bind: config.sv2.bind,
        port: config.sv2.port,
        staticKey: stat,
        cert,
        defaultDifficulty: config.stratum.defaultDifficulty,
        log: makeLogger("sv2-mining"),
        jobs,
        onShare: (event) => ipc.send(event),
    });

    jobs.start();
    await server.listen();

    let jd: Sv2JdServer | null = null;
    if (config.jd.enable) {
        jd = new Sv2JdServer({
            bind: config.jd.bind,
            port: config.jd.port,
            staticKey: stat,
            cert,
            log: makeLogger("sv2-jd"),
            deliverCustomJob: async (delivery, userIdentity) =>
                server.pushCustomJob(userIdentity, {
                    requestId: delivery.requestId,
                    miningJobToken: delivery.miningJobToken,
                    version: delivery.version,
                    coinbasePrefix: delivery.coinbasePrefix,
                    coinbaseSuffix: delivery.coinbaseSuffix,
                }),
        });
        await jd.listen();
        log.info({ bind: config.jd.bind, port: config.jd.port }, "sv2 jd server up");
    }

    const shutdown = async (sig: string) => {
        log.info({ sig }, "shutdown");
        jobs.stop();
        ipc.stop();
        await server.close();
        if (jd) await jd.close();
        process.exit(0);
    };
    process.on("SIGTERM", () => void shutdown("SIGTERM"));
    process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((e) => {
    log.error({ err: e.message, stack: e.stack }, "fatal");
    process.exit(1);
});
