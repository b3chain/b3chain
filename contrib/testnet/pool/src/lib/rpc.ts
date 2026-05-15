// Minimal JSON-RPC client for b3chaind, with optional wallet endpoint
// support and connection re-use via the global fetch agent.

import { config } from "../config";

export class RpcError extends Error {
    public readonly code: number;
    public readonly data: unknown;
    constructor(code: number, message: string, data?: unknown) {
        super(message);
        this.code = code;
        this.data = data;
    }
}

let nextId = 1;

export interface RpcOptions {
    wallet?: string;
}

export async function rpc<T = unknown>(
    method: string,
    params: unknown[] = [],
    opts: RpcOptions = {}
): Promise<T> {
    const path = opts.wallet ? `/wallet/${encodeURIComponent(opts.wallet)}` : "/";
    const url = `http://${config.rpc.host}:${config.rpc.port}${path}`;
    const id = nextId++;
    const body = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    const auth = Buffer.from(`${config.rpc.user}:${config.rpc.password}`).toString("base64");

    let resp: Response;
    try {
        resp = await fetch(url, {
            method: "POST",
            headers: {
                "content-type": "application/json",
                authorization: `Basic ${auth}`,
            },
            body,
        });
    } catch (e) {
        throw new RpcError(-32000, `network error calling ${method}: ${(e as Error).message}`);
    }
    const text = await resp.text();
    if (!resp.ok && text === "") {
        throw new RpcError(resp.status, `HTTP ${resp.status} from b3chaind`);
    }
    let json: { result?: T; error?: { code: number; message: string; data?: unknown } };
    try {
        json = JSON.parse(text);
    } catch {
        throw new RpcError(-32700, `non-JSON response from ${method}: ${text.slice(0, 200)}`);
    }
    if (json.error) {
        throw new RpcError(json.error.code, json.error.message, json.error.data);
    }
    return json.result as T;
}

export type BlockTemplate = {
    version: number;
    rules?: string[];
    previousblockhash: string;
    transactions: { data: string; hash: string; txid?: string; depends?: number[] }[];
    coinbasetxn?: { data: string };
    coinbasevalue: number;
    target: string;
    mintime: number;
    curtime: number;
    bits: string;
    height: number;
    default_witness_commitment?: string;
    capabilities?: string[];
    mutable?: string[];
    longpollid?: string;
};

export async function getBlockTemplate(): Promise<BlockTemplate> {
    return rpc<BlockTemplate>("getblocktemplate", [{ rules: ["segwit"] }]);
}

export async function submitBlock(blockHex: string): Promise<string | null> {
    // submitblock returns null on accept, or an error string on reject.
    return rpc<string | null>("submitblock", [blockHex]);
}

export type GetBlockResult = {
    hash: string;
    confirmations: number;
    height: number;
    tx: string[];
    time: number;
    [k: string]: unknown;
};

export async function getBlock(hash: string): Promise<GetBlockResult | null> {
    try {
        return await rpc<GetBlockResult>("getblock", [hash]);
    } catch (e) {
        if (e instanceof RpcError && e.code === -5) return null;
        throw e;
    }
}

export async function validateAddress(addr: string): Promise<{ isvalid: boolean; address?: string }> {
    return rpc("validateaddress", [addr]);
}

export async function sendMany(
    fromAccount: string,
    targets: Record<string, number>,
    comment?: string
): Promise<string> {
    return rpc<string>(
        "sendmany",
        [fromAccount, targets, 1, comment ?? "pool-payout"],
        { wallet: config.rpc.payoutWallet }
    );
}

export async function getWalletBalance(): Promise<number> {
    return rpc<number>("getbalance", [], { wallet: config.rpc.payoutWallet });
}
