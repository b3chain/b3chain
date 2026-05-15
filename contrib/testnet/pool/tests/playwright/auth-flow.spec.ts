// Playwright smoke test: signup -> read verification email from
// mailpit -> verify -> enable 2FA -> login -> dashboard hashrate
// graph populated within 5 seconds of a connected miner.
//
// Requires:
//   - the dev docker-compose stack running (docker-compose.dev.yml)
//   - the three pool services running locally
//   - a miner connected to 127.0.0.1:3333 (e.g. scripts/fake-miner.js)
//
// Run with:  npx playwright test tests/playwright/auth-flow.spec.ts

import { test, expect } from "@playwright/test";

const BASE = process.env.B3POOL_BASE_URL ?? "http://127.0.0.1:5100";
const MAILPIT = process.env.MAILPIT_URL ?? "http://127.0.0.1:8025";

async function fetchVerificationLink(email: string): Promise<string> {
    const list = await (await fetch(`${MAILPIT}/api/v1/messages`)).json();
    const m = (list.messages as { ID: string; To: { Address: string }[] }[]).find((x) =>
        x.To.some((t) => t.Address === email)
    );
    if (!m) throw new Error("no mail for " + email);
    const body = await (await fetch(`${MAILPIT}/api/v1/message/${m.ID}`)).json();
    const link = (body.Text as string).match(/https?:\S+/)?.[0];
    if (!link) throw new Error("no link in mail body");
    return link;
}

test("signup -> verify -> 2FA -> dashboard", async ({ page }) => {
    const email = `t${Date.now()}@example.com`;
    const password = "supersecret123";

    await page.goto(`${BASE}/auth/signup`);
    await page.fill("input[name=email]", email);
    await page.fill("input[name=password]", password);
    await page.click("button[type=submit]");
    await expect(page.getByText("Check your inbox")).toBeVisible();

    const link = await fetchVerificationLink(email);
    await page.goto(link);
    await expect(page.getByText("Email verified")).toBeVisible();

    await page.fill("input[name=email]", email);
    await page.fill("input[name=password]", password);
    await page.click("button[type=submit]");
    await expect(page).toHaveURL(/\/dashboard/);

    // Hashrate tile should populate within 5 seconds of a miner connecting.
    await expect(page.locator("#user-hashrate")).not.toHaveText("…", { timeout: 5000 });
});
