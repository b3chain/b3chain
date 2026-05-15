import { Pool, PoolClient } from "pg";
import { config } from "../config";

let pool: Pool | null = null;

export function getPool(): Pool {
    if (!pool) {
        pool = new Pool({ connectionString: config.db.url });
        pool.on("error", (err) => {
            console.error("[db] pool error:", err);
        });
    }
    return pool;
}

export async function closePool(): Promise<void> {
    if (pool) {
        await pool.end();
        pool = null;
    }
}

export async function query<T extends Record<string, unknown> = Record<string, unknown>>(
    text: string,
    params: unknown[] = []
): Promise<T[]> {
    const r = await getPool().query<T>(text, params as never);
    return r.rows;
}

export async function tx<T>(fn: (c: PoolClient) => Promise<T>): Promise<T> {
    const c = await getPool().connect();
    try {
        await c.query("BEGIN");
        const out = await fn(c);
        await c.query("COMMIT");
        return out;
    } catch (e) {
        await c.query("ROLLBACK").catch(() => {});
        throw e;
    } finally {
        c.release();
    }
}
