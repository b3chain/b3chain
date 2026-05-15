// V1 <-> V2 translator service.
//
// Listens on a TCP port (default :3337) for legacy Stratum V1 miners,
// re-uses StratumClient verbatim for the V1-side framing, and pairs each
// V1 connection with its own SV2 Extended channel against our own pool
// (default :3336). The two sides are bridged frame-by-frame:
//
//   V1 mining.subscribe       ->  Sv2UpstreamClient.connect() (NX + setup
//                                 + OpenExtendedMiningChannel) and
//                                 respond with the channel's
//                                 extranonce_prefix as extranonce1.
//   V1 mining.authorize       ->  ack (we do not authenticate downstream;
//                                 SV2 channel.userIdentity == V1 username
//                                 is what gets credited).
//   V1 mining.submit          ->  SubmitSharesExtended on the upstream
//                                 channel.
//   SV2 NewExtendedMiningJob  ->  V1 mining.notify (synthesised)
//   SV2 SetNewPrevHash        ->  cleanJobs=true on the next notify
//   SV2 SetTarget             ->  V1 mining.set_difficulty

import { EventEmitter } from "events";
import * as net from "net";
import { sha256 } from "@noble/hashes/sha2";
import { config } from "../../config";
import { Logger } from "../../lib/logger";
import { StratumClient, RpcCall } from "../../stratum/client";
import { bytesToHex, hexToBytes, reverseBytes } from "../../lib/header";
import {
    bigIntFromBytesBE, POOL_DIFF1_TARGET,
} from "../../lib/difficulty-math";
import { Sv2UpstreamClient } from "./sv2-client";
import { NewExtendedMiningJob, SetNewPrevHash, SetTarget } from "../lib/messages/mining";

export interface TranslatorOptions {
    bind: string;
    port: number;
    upstreamHost: string;
    upstreamPort: number;
    /** Trusted authority pubkey for upstream's Noise NX cert. */
    authorityPub: Uint8Array;
    log: Logger;
}

interface BridgeState {
    v1: StratumClient;
    sv2: Sv2UpstreamClient;
    /** Last NewExtendedMiningJob seen so SubmitShares can rebuild the job. */
    lastJob?: NewExtendedMiningJob;
    /** Last prev-hash announcement so we can stamp ntime / cleanJobs correctly. */
    lastPrevHash?: SetNewPrevHash;
    /** Map V1 jobId (hex string) -> SV2 jobId (number). */
    jobIdMap: Map<string, number>;
    nextV1JobNum: number;
}

export class TranslatorServer extends EventEmitter {
    private server: net.Server | null = null;
    private bridges = new Set<BridgeState>();

    constructor(private opts: TranslatorOptions) { super(); }

    async listen(): Promise<void> {
        await new Promise<void>((res, rej) => {
            const s = net.createServer((sock) => this.accept(sock));
            s.on("error", rej);
            s.listen(this.opts.port, this.opts.bind, () => {
                s.removeListener("error", rej);
                this.server = s;
                this.opts.log.info({ bind: this.opts.bind, port: this.opts.port }, "v1<->v2 translator listening");
                res();
            });
        });
    }

    async close(): Promise<void> {
        for (const b of this.bridges) { b.v1.sock.destroy(); b.sv2.close(); }
        if (this.server) await new Promise<void>((res) => this.server!.close(() => res()));
    }

    private accept(sock: net.Socket): void {
        const v1 = new StratumClient(sock, this.opts.log);
        const sv2 = new Sv2UpstreamClient({
            host: this.opts.upstreamHost,
            port: this.opts.upstreamPort,
            authorityPub: this.opts.authorityPub,
            userIdentity: "translator-anon",
            nominalHashRate: 1e7,
            minExtranonceSize: 4,
        });
        const bridge: BridgeState = {
            v1, sv2,
            jobIdMap: new Map(),
            nextV1JobNum: 1,
        };
        this.bridges.add(bridge);
        v1.on("rpc", (m: RpcCall) => void this.onV1(bridge, m));
        v1.on("close", () => { this.bridges.delete(bridge); sv2.close(); });
        sv2.on("job", (j: NewExtendedMiningJob) => this.onSv2Job(bridge, j));
        sv2.on("prevhash", (p: SetNewPrevHash) => this.onSv2PrevHash(bridge, p));
        sv2.on("target", (t: SetTarget) => this.onSv2Target(bridge, t));
        sv2.on("error", (e: Error) => {
            this.opts.log.warn({ err: e.message, id: v1.connId }, "translator sv2 error");
            v1.fail("upstream-error");
        });
        sv2.on("close", () => v1.fail("upstream-closed"));
    }

    private async onV1(bridge: BridgeState, m: RpcCall): Promise<void> {
        const { v1, sv2 } = bridge;
        try {
            switch (m.method) {
                case "mining.subscribe": {
                    if (m.params.length > 0 && typeof m.params[0] === "string") {
                        v1.userAgent = m.params[0];
                    }
                    sv2.opts.userIdentity = v1.username || "v1-anon";
                    await sv2.connect();
                    const en1Hex = bytesToHex(sv2.extranoncePrefix);
                    v1.sendResult(m.id, [
                        [
                            ["mining.set_difficulty", `subscribe-${v1.connId}.diff`],
                            ["mining.notify", `subscribe-${v1.connId}.notify`],
                        ],
                        en1Hex,
                        sv2.extranonceSize,
                    ]);
                    v1.state = "subscribed";
                    return;
                }
                case "mining.authorize": {
                    const username = String(m.params[0] ?? "");
                    v1.username = username;
                    sv2.opts.userIdentity = username || "v1-anon";
                    v1.sendResult(m.id, true);
                    v1.state = "authorized";
                    // Difficulty comes from upstream SV2 SetTarget (see
                    // onSv2Target). Push the initial vardiff value so the
                    // miner has a working diff before the first SetTarget.
                    v1.pushDifficulty(v1.vardiff.diff);
                    return;
                }
                case "mining.submit": {
                    if (v1.state !== "authorized") {
                        v1.sendError(m.id, 24, "unauthorized worker");
                        return;
                    }
                    if (!bridge.lastJob || !bridge.lastPrevHash) {
                        v1.sendError(m.id, 21, "no-job");
                        return;
                    }
                    const [, v1JobId, en2Hex, ntimeHex, nonceHex, versionRollHex] = m.params as [string, string, string, string, string, string?];
                    const sv2JobId = bridge.jobIdMap.get(v1JobId);
                    if (!sv2JobId) {
                        v1.sendError(m.id, 21, "stale");
                        return;
                    }
                    const en2 = hexToBytes(en2Hex);
                    const ntime = parseInt(ntimeHex, 16);
                    const nonce = parseInt(nonceHex, 16);
                    const version = versionRollHex ? parseInt(versionRollHex, 16) : bridge.lastJob.version;
                    const r = await sv2.submitExtendedShare({
                        nonce, ntime, version, extranonce: en2, jobId: sv2JobId,
                    });
                    if (r.ok) {
                        v1.sharesAccepted++;
                        v1.sendResult(m.id, true);
                    } else {
                        v1.sharesRejected++;
                        v1.sendError(m.id, 23, r.reason ?? "rejected");
                    }
                    return;
                }
                case "mining.suggest_difficulty": {
                    // Translator ignores miner-suggested difficulty; the
                    // upstream SV2 channel decides it via SetTarget.
                    v1.sendResult(m.id, true);
                    return;
                }
                default:
                    v1.sendError(m.id, 20, "method not supported by translator");
            }
        } catch (e) {
            this.opts.log.warn({ err: (e as Error).message, id: v1.connId, method: m.method }, "v1 handler failed");
            v1.sendError(m.id, 20, "internal-error");
        }
    }

    private onSv2Job(bridge: BridgeState, j: NewExtendedMiningJob): void {
        bridge.lastJob = j;
        const v1JobId = (bridge.nextV1JobNum++).toString(16).padStart(8, "0");
        bridge.jobIdMap.set(v1JobId, j.jobId);
        if (bridge.jobIdMap.size > 64) {
            const oldest = bridge.jobIdMap.keys().next().value;
            if (oldest !== undefined) bridge.jobIdMap.delete(oldest);
        }
        const ph = bridge.lastPrevHash;
        if (!ph) return; // wait for prev-hash before issuing notify
        // Reconstruct V1 mining.notify params from SV2 extended job + prev-hash.
        bridge.v1.sendNotify("mining.notify", [
            v1JobId,
            bytesToHex(reverseBytes(ph.prevHash)),
            bytesToHex(j.coinbaseTxPrefix),
            bytesToHex(j.coinbaseTxSuffix),
            j.merklePath.map(p => bytesToHex(reverseBytes(p))),
            "0x" + j.version.toString(16).padStart(8, "0"),
            "0x" + ph.nbits.toString(16).padStart(8, "0"),
            "0x" + ph.minNtime.toString(16).padStart(8, "0"),
            true,
        ]);
    }

    private onSv2PrevHash(bridge: BridgeState, p: SetNewPrevHash): void {
        bridge.lastPrevHash = p;
        if (bridge.lastJob) this.onSv2Job(bridge, bridge.lastJob);
    }

    private onSv2Target(bridge: BridgeState, t: SetTarget): void {
        // SV2 target is a 256-bit BE target. Convert to V1 share difficulty.
        const tgt = bigIntFromBytesBE(t.maxTarget);
        if (tgt === 0n) return;
        const diff = Number(POOL_DIFF1_TARGET / tgt);
        if (diff > 0) bridge.v1.pushDifficulty(diff);
    }
}

// re-export for caller
export { sha256 };
