// Entry point for the b3chain-pool-translator service.
//
// Reads the upstream SV2 pool's authority pubkey from the cert file
// (the install.sh writes it under $CFG_DIR by default).

import * as fs from "fs";
import { config } from "../../config";
import { makeLogger } from "../../lib/logger";
import { decodeCertificate } from "../lib/cert";
import { loadOrCreateAuthorityKey } from "../lib/keys";
import { TranslatorServer } from "./server";

const log = makeLogger("sv2-translator-main");

async function main(): Promise<void> {
    if (!config.translator.enable) {
        log.warn("B3POOL_TRANSLATOR_ENABLE=false; refusing to start");
        process.exit(0);
    }
    const [host, portStr] = config.translator.upstream.split(":");
    if (!host || !portStr) throw new Error(`bad B3POOL_TRANSLATOR_UPSTREAM: ${config.translator.upstream}`);
    const port = parseInt(portStr, 10);
    if (!Number.isFinite(port)) throw new Error(`bad upstream port: ${portStr}`);

    // Authority pubkey is the one our SV2 mining pool's cert is signed
    // under. We can re-derive it from the local authority keypair file
    // because translator + pool live on the same host. Cross-host
    // translator deployments would point at a public authority.hex
    // published via nginx (see install.sh phase G).
    const authority = loadOrCreateAuthorityKey(config.sv2.authorityKeyFile);
    let authorityPub = authority.pub;
    if (fs.existsSync(config.sv2.certFile)) {
        const cert = decodeCertificate(new Uint8Array(fs.readFileSync(config.sv2.certFile)));
        log.info({
            certPub: Buffer.from(cert.publicKey).toString("hex"),
            certNotValidAfter: new Date(cert.notValidAfter * 1000).toISOString(),
        }, "loaded upstream pool cert");
    }

    log.info({
        bind: config.translator.bind, port: config.translator.port,
        upstream: `${host}:${port}`,
    }, "translator boot");

    const server = new TranslatorServer({
        bind: config.translator.bind,
        port: config.translator.port,
        upstreamHost: host,
        upstreamPort: port,
        authorityPub,
        log: makeLogger("translator"),
    });
    await server.listen();

    const shutdown = async (sig: string) => {
        log.info({ sig }, "shutdown");
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
