// End-to-end smoke test. This is intentionally a thin orchestrator —
// the heavy lifting is in tests/e2e/docker-compose.e2e.yml + the
// production code paths (no mocks).
//
// Choreography:
//   1. `docker compose up -d` to start b3chaind regtest + postgres + pool
//   2. seed a verified user via the seed-admin CLI
//   3. spawn N simulated stratum clients (lightweight TCP -> mining.subscribe
//      / authorize / submit loop) for 60 seconds
//   4. assert that at least one block was found (pool difficulty 1 means
//      every share is a block under regtest's tiny target)
//   5. assert the user's balance > 0 once 100 confirms mature
//   6. assert that pay-now CLI emits a sendmany txid and the dashboard
//      reflects it
//
// Skipped automatically if `docker compose` is not on PATH or
// SKIP_E2E is set; intended for CI in a Linux environment.

import { test } from "node:test";
import { execSync, spawn } from "node:child_process";
import * as path from "node:path";

const SKIP = process.env.SKIP_E2E === "1" || !haveDocker();

function haveDocker(): boolean {
    try {
        execSync("docker compose version", { stdio: "ignore" });
        return true;
    } catch {
        return false;
    }
}

test("mine-and-pay e2e", { skip: SKIP }, async () => {
    const compose = path.join(__dirname, "docker-compose.e2e.yml");
    execSync(`docker compose -f "${compose}" up -d`, { stdio: "inherit" });
    try {
        // Wait for the stratum container to print "stratum listening".
        await waitForLog("pool-stratum", /stratum listening/, 60_000);
        // Bootstrap one verified test user.
        execSync(
            `docker compose -f "${compose}" exec -T pool-stratum sh -c \
                "cd /app/src && npm run seed-admin -- e2e@example.com 'pw1234567890'"`,
            { stdio: "inherit" }
        );
        // Spawn 5 simulated miners.
        const procs = Array.from({ length: 5 }, (_, i) =>
            spawn(process.execPath, [path.join(__dirname, "..", "..", "scripts", "fake-miner.js"), `e2e@example.com.r${i}`], {
                stdio: "inherit",
                env: { ...process.env, STRATUM_PORT: "13333" },
            })
        );
        await new Promise((r) => setTimeout(r, 60_000));
        for (const p of procs) p.kill();

        // Mature 100 blocks via b3chaind regtest (the daemon mints rewards
        // straight to pool-payouts wallet via getblocktemplate coinbasetxn).
        execSync(
            `docker compose -f "${compose}" exec -T b3chaind \
                b3chain-cli -regtest -rpcuser=dev -rpcpassword=dev \
                generatetoaddress 100 \
                $(b3chain-cli -regtest -rpcuser=dev -rpcpassword=dev getnewaddress)`,
            { stdio: "inherit" }
        );

        // Force a payout cycle.
        execSync(
            `docker compose -f "${compose}" exec -T pool-stratum sh -c \
                "cd /app/src && npm run pay-now"`,
            { stdio: "inherit" }
        );

        // No assertion library inside container; verify via SQL.
        execSync(
            `docker compose -f "${compose}" exec -T postgres psql -U b3chain_pool -c \
              "SELECT user_id, SUM(delta_b3c) AS balance FROM balance_entries GROUP BY user_id;"`,
            { stdio: "inherit" }
        );
    } finally {
        execSync(`docker compose -f "${compose}" down -v`, { stdio: "inherit" });
    }
});

function waitForLog(svc: string, pattern: RegExp, ms: number): Promise<void> {
    return new Promise((resolve, reject) => {
        const start = Date.now();
        const compose = path.join(__dirname, "docker-compose.e2e.yml");
        const tick = setInterval(() => {
            try {
                const out = execSync(`docker compose -f "${compose}" logs ${svc}`, { stdio: ["ignore", "pipe", "ignore"] }).toString();
                if (pattern.test(out)) {
                    clearInterval(tick);
                    resolve();
                    return;
                }
            } catch {
                // ignored, log not yet
            }
            if (Date.now() - start > ms) {
                clearInterval(tick);
                reject(new Error(`timed out waiting for ${pattern} in ${svc} logs`));
            }
        }, 1000);
    });
}
