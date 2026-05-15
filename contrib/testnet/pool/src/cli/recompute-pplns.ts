// Operator: replay PPLNS for one or more block ids. Use after a config
// change (e.g. fee % adjustment) or to repair a broken credit.
//
// USAGE:
//   tsx src/cli/recompute-pplns.ts 17 18 19

import { query, closePool } from "../lib/db";
import { creditPplns } from "../pool/pplns";
import { makeLogger } from "../lib/logger";

async function main(): Promise<void> {
    const log = makeLogger("recompute-pplns");
    const args = process.argv.slice(2);
    if (args.length === 0) {
        console.error("usage: recompute-pplns <blockId> [blockId ...]");
        process.exit(2);
    }
    for (const idStr of args) {
        const id = parseInt(idStr, 10);
        if (!Number.isFinite(id)) {
            console.error(`skip non-numeric block id ${idStr}`);
            continue;
        }
        await query(
            `DELETE FROM balance_entries WHERE block_id = $1 AND payout_id IS NULL`,
            [id]
        );
        await query(`UPDATE blocks SET pplns_credited = FALSE WHERE id = $1`, [id]);
        await creditPplns(id, log);
    }
    await closePool();
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
