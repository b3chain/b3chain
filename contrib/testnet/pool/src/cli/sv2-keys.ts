// CLI helper invoked by install.sh:
//   - ensures the Ed25519 authority keypair file exists
//   - ensures the X25519 static keypair file exists
//   - issues / refreshes the signed certificate
//   - prints a hex blob of the authority pubkey + cert so install.sh can
//     publish it under nginx for miners to fetch
//
// Usage:  node dist/cli/sv2-keys.js
// All paths come from the standard pool config / env.

import * as fs from "fs";
import * as path from "path";
import { config } from "../config";
import { loadOrCreateAuthorityKey, loadOrCreateStaticKey } from "../sv2/lib/keys";
import {
    encodeCertificate,
    loadOrIssueCertificate,
    SV2_CERT_LEN,
} from "../sv2/lib/cert";
import { bytesToHex } from "../sv2/lib/types";

function ensureDir(p: string): void {
    const d = path.dirname(p);
    if (d && !fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
}

function main(): void {
    const cfg = config.sv2;
    ensureDir(cfg.authorityKeyFile);
    ensureDir(cfg.staticKeyFile);
    ensureDir(cfg.certFile);

    const authority = loadOrCreateAuthorityKey(cfg.authorityKeyFile);
    const stat = loadOrCreateStaticKey(cfg.staticKeyFile);
    const cert = loadOrIssueCertificate(
        cfg.certFile,
        authority,
        stat.pub,
        cfg.certValidityDays * 24 * 60 * 60,
    );

    const certBytes = encodeCertificate(cert);
    if (certBytes.length !== SV2_CERT_LEN) {
        console.error(`unexpected cert length ${certBytes.length}, expected ${SV2_CERT_LEN}`);
        process.exit(1);
    }

    process.stdout.write(JSON.stringify({
        authorityPub: bytesToHex(authority.pub),
        staticPub: bytesToHex(stat.pub),
        certHex: bytesToHex(certBytes),
        validFrom: cert.validFrom,
        notValidAfter: cert.notValidAfter,
        certFile: cfg.certFile,
    }, null, 2));
    process.stdout.write("\n");
}

main();
