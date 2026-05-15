// Operator: force a payout cycle right now (e.g. for support tickets).

import { makeLogger } from "../lib/logger";
import { PayoutJob } from "../pool/payout-job";
import { closePool } from "../lib/db";

async function main(): Promise<void> {
    const log = makeLogger("pay-now-cli");
    const job = new PayoutJob(log);
    await job.tick();
    await closePool();
}

main().catch((e) => {
    console.error(e);
    process.exit(1);
});
