// Newline-delimited JSON over a UNIX domain socket.
//
// The stratum service is the *client*: it opens the socket on startup and
// auto-reconnects with backoff if the daemon is down. The pool daemon is
// the *server*: it accepts the connection and persists messages.

import * as net from "net";
import * as fs from "fs";
import { EventEmitter } from "events";

export type ShareEvent = {
    type: "share";
    user: string;            // <email>.<workerName> (or anon connId in Phase A)
    workerName: string;
    diff: number;
    isBlock: boolean;
    blockHash?: string;
    blockHeight?: number;
    networkDifficulty?: number;
    timestampMs: number;
};

export type IpcMessage = ShareEvent;

export class IpcServer extends EventEmitter {
    private server: net.Server;
    constructor(private path: string) {
        super();
        this.server = net.createServer((sock) => this.handle(sock));
    }
    async listen(): Promise<void> {
        await fs.promises.rm(this.path, { force: true });
        await new Promise<void>((res, rej) => {
            this.server.once("error", rej);
            this.server.listen(this.path, () => {
                this.server.removeListener("error", rej);
                fs.chmodSync(this.path, 0o660);
                res();
            });
        });
    }
    async close(): Promise<void> {
        await new Promise<void>((res) => this.server.close(() => res()));
        await fs.promises.rm(this.path, { force: true });
    }
    private handle(sock: net.Socket) {
        let buf = "";
        sock.setEncoding("utf8");
        sock.on("data", (chunk) => {
            buf += chunk;
            let idx;
            while ((idx = buf.indexOf("\n")) >= 0) {
                const line = buf.slice(0, idx).trim();
                buf = buf.slice(idx + 1);
                if (!line) continue;
                try {
                    const msg = JSON.parse(line) as IpcMessage;
                    this.emit("message", msg);
                } catch (e) {
                    this.emit("parse-error", e, line);
                }
            }
        });
        sock.on("error", (e) => this.emit("client-error", e));
    }
}

export class IpcClient extends EventEmitter {
    private sock: net.Socket | null = null;
    private connecting = false;
    private retryMs = 500;
    private buffered: string[] = [];
    private maxBuffer = 5000;
    private closed = false;

    constructor(private path: string) {
        super();
    }

    start(): void {
        this.connect();
    }

    stop(): void {
        this.closed = true;
        if (this.sock) {
            this.sock.destroy();
            this.sock = null;
        }
    }

    send(msg: IpcMessage): void {
        const line = JSON.stringify(msg) + "\n";
        if (this.sock && !this.sock.destroyed && this.sock.writable) {
            this.sock.write(line);
        } else {
            if (this.buffered.length < this.maxBuffer) this.buffered.push(line);
        }
    }

    private connect(): void {
        if (this.connecting || this.closed) return;
        this.connecting = true;
        const sock = net.createConnection({ path: this.path }, () => {
            this.connecting = false;
            this.sock = sock;
            this.retryMs = 500;
            this.emit("connect");
            const queued = this.buffered.splice(0);
            for (const line of queued) sock.write(line);
        });
        sock.on("error", () => {
            // suppress; reconnect on close
        });
        sock.on("close", () => {
            this.sock = null;
            this.connecting = false;
            if (this.closed) return;
            this.emit("disconnect");
            const wait = this.retryMs;
            this.retryMs = Math.min(this.retryMs * 2, 10_000);
            setTimeout(() => this.connect(), wait);
        });
    }
}
