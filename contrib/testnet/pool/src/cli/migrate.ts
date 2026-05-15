// SQL migration runner. Applies db/migrations/*.sql in lexicographic
// order, tracking already-applied filenames in a `_migrations` table.

import * as fs from "fs";
import * as path from "path";
import { getPool, query, closePool } from "../lib/db";

async function main(): Promise<void> {
    const pool = getPool();
    await pool.query(
        `CREATE TABLE IF NOT EXISTS _migrations(
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`
    );
    const dir = path.resolve(__dirname, "..", "..", "db", "migrations");
    const files = fs.readdirSync(dir).filter((f) => f.endsWith(".sql")).sort();
    for (const f of files) {
        const done = await query<{ filename: string }>(
            "SELECT filename FROM _migrations WHERE filename = $1",
            [f]
        );
        if (done.length > 0) {
            console.log(`[migrate] skip ${f} (already applied)`);
            continue;
        }
        const sql = fs.readFileSync(path.join(dir, f), "utf8");
        console.log(`[migrate] applying ${f}…`);
        await pool.query("BEGIN");
        try {
            await pool.query(sql);
            await pool.query("INSERT INTO _migrations(filename) VALUES ($1)", [f]);
            await pool.query("COMMIT");
            console.log(`[migrate]   ok`);
        } catch (e) {
            await pool.query("ROLLBACK");
            console.error(`[migrate]   FAILED:`, e);
            process.exitCode = 1;
            break;
        }
    }
    await closePool();
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
