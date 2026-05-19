# Phase 6.2 — Verification Checklist

This document is the **independent verification gate** for Phase 6.2 of
the [B3Chain implementation plan](../../B3CHAIN-IMPLEMENTATION-PLAN.md):
the public Stratum V1 mining pool at `contrib/testnet/pool/`. It mirrors
[`PHASE-6-VERIFICATION.md`](PHASE-6-VERIFICATION.md) (the internal-miner
verifier) one row per phase of the rollout.

The companion script
[`contrib/testing/audit/audit-stratum-pool.sh`](../contrib/testing/audit/audit-stratum-pool.sh)
runs every check and rewrites the status column of this file in place.
Exit code is **0 only if every item passes**.

The audit is wired into
[`contrib/testing/audit/verify-phase11.sh`](../contrib/testing/audit/verify-phase11.sh)
so a single command continues to validate the full audit suite.

## Status legend

- `[x]` PASS — verifier confirmed the criterion holds
- `[!]` FAIL — verifier ran but the criterion did not hold
- `[?]` PENDING — verifier has not yet been run for this item
- `[-]` SKIP — not runnable in this environment (e.g. no Node.js / no live pool)

## How to run

```bash
cd b3chain
bash contrib/testing/audit/audit-stratum-pool.sh           # run + rewrite this file
bash contrib/testing/audit/audit-stratum-pool.sh --static  # static-only (no Node.js)
bash contrib/testing/audit/audit-stratum-pool.sh --dry-run # print what would run
```

Last run: **2026-05-19 20:36**

---

## P — Stratum mining pool (Phase 6.2)

| #     | ID   | Acceptance criterion | Verification command | Expected | Status |
|-------|------|----------------------|----------------------|----------|--------|
| P-1a  | `phase-a-stratum-server` | Stratum V1 server module exists with `mining.subscribe`, `mining.authorize`, and `mining.submit` handlers | `grep -cE 'mining\.(subscribe\|authorize\|submit)' contrib/testnet/pool/src/stratum/server.ts` | ≥ 3 (one match per method) | `[x]` |
| P-1b  | `phase-a-share-validator` | Share validator computes `BLAKE3(BLAKE3(header))` and compares against `targetFromShareDifficulty(diff)` | `grep -lE 'blake3d\\(.*header.*\\)' contrib/testnet/pool/src/stratum/share-validator.ts` | path printed (1 file) | `[x]` |
| P-1c  | `phase-a-template-poller` | Pool daemon polls `getblocktemplate` on a configurable interval and broadcasts new jobs | `grep -nE 'getBlockTemplate\|template-error' contrib/testnet/pool/src/stratum/job-manager.ts` | ≥ 2 matches | `[x]` |
| P-1d  | `phase-a-blake3-vector` | The pool's BLAKE3d helper reproduces the published double-BLAKE3 vector for the empty input (`fb6d63b21d8c9f215de0e4fd9f4d0e7ed53ff023c7243e76f5a7367b2a4507b6`) | `cd contrib/testnet/pool && node --test --import tsx tests/blake3.test.ts 2>&1 \| grep -c '# pass'` | ≥ 3 (one per assertion in tests/blake3.test.ts) | `[x]` |
| P-2a  | `phase-b-schema` | `db/migrations/001_init.sql` creates `users`, `workers`, `sessions`, `email_verify_tokens`, `password_reset_tokens` | `grep -cE 'CREATE TABLE.*\\b(users\|workers\|sessions\|email_verify_tokens\|password_reset_tokens)\\b' contrib/testnet/pool/db/migrations/001_init.sql` | ≥ 5 | `[x]` |
| P-2b  | `phase-b-auth-flow` | Auth router implements signup, email-verify, login, password-reset, 2FA-setup, 2FA-verify endpoints | `grep -cE '(r\\.get\|r\\.post)\\("/(signup\|verify-email\|login\|forgot\|reset\|2fa-setup\|2fa-verify\|logout\|2fa-disable)"' contrib/testnet/pool/src/web/routes/auth.ts` | ≥ 10 (each endpoint has at least one handler) | `[x]` |
| P-2c  | `phase-b-address-validator` | Address validator accepts mainnet (`b3`), testnet (`tb3`), and regtest (`b3rt`) HRPs and rejects everything else | `cd contrib/testnet/pool && node --test --import tsx tests/address.test.ts 2>&1 \| grep -c '# pass'` | ≥ 6 (one per `test()` in tests/address.test.ts) | `[x]` |
| P-3a  | `phase-c-pplns-math` | PPLNS math reproduces the worked example in `docs/PPLNS.md` (alice 19.80, bob 4.95, carol 24.75) | `cd contrib/testnet/pool && node --test --import tsx tests/pplns.test.ts 2>&1 \| grep -c '# pass'` | ≥ 5 | `[x]` |
| P-3b  | `phase-c-payout-job` | Payout job code reads each user's `minimum_payout_b3c`, validates the address, and only debits inside the same DB transaction as the `payouts` row insert | `grep -E 'BEGIN\|sendMany\|payout_recipients\|delta_b3c' contrib/testnet/pool/src/pool/payout-job.ts \| wc -l` | ≥ 4 | `[x]` |
| P-3c  | `phase-c-block-confirmer` | Confirmer marks a block confirmed after `B3POOL_BLOCK_CONFIRMATIONS` confirms and triggers PPLNS exactly once via the `pplns_credited` flag | `grep -nE 'pplns_credited\|blockConfirmations\|creditPplns' contrib/testnet/pool/src/pool/{block-confirmer,pplns}.ts` | ≥ 3 | `[x]` |
| P-4a  | `phase-d-vardiff` | Vardiff convergence test passes (synthetic share stream converges to ~target diff in ≤ 30 retunes) | `cd contrib/testnet/pool && node --test --import tsx tests/vardiff.test.ts 2>&1 \| grep -c '# pass'` | ≥ 4 | `[x]` |
| P-4b  | `phase-d-rate-limit` | Web app installs `express-rate-limit` middleware on auth + signup + password-reset routes | `grep -nE 'authLimiter\|signupLimiter\|passwordResetLimiter' contrib/testnet/pool/src/web/routes/auth.ts` | ≥ 3 (one per route family) | `[x]` |
| P-4c  | `phase-d-metrics` | `/metrics` endpoint exposes at least 6 Prometheus gauges/counters with `b3chain_pool_*` prefix | `grep -cE 'b3chain_pool_[a-z_]+' contrib/testnet/pool/src/web/routes/metrics.ts` | ≥ 12 (each metric appears as both HELP and a value line) | `[x]` |
| P-4d  | `phase-d-runbook` | `docs/OPERATOR-RUNBOOK.md` covers pool-down, orphaned-block, and balance-dispute scenarios | `grep -ciE 'pool is down\|orphan\|balance' contrib/testnet/pool/docs/OPERATOR-RUNBOOK.md` | ≥ 3 | `[x]` |

## How a row becomes PASS

The audit script sets the status column based on what it observed:

```
For each row:
  1. parse the verification command from the table
  2. run it (with bash, captured stdout/stderr, captured exit code)
  3. apply the row's pass-rule
  4. write [x] if pass-rule held, [!] if not, [-] if skipped
```

Skip behaviour:

- Rows P-1d, P-2c, P-3a, P-4a are skipped (`[-]`) when Node.js 20 is
  not available or the pool's `node_modules/` are not installed
  (`cd contrib/testnet/pool && npm ci`).
- All other rows run from source files only and never skip.

## Findings

The audit script appends to this section every time it runs. Phase 6.2
is considered "verified" once this section is empty after a clean run.

<!-- VERIFIER-FINDINGS-START -->
*Last verifier run: 2026-05-19 20:36*

*(clean run — no failures, no skips)*
<!-- VERIFIER-FINDINGS-END -->

## Why this document exists

The [B3Chain implementation plan](../../B3CHAIN-IMPLEMENTATION-PLAN.md)
calls for a "production-shaped" reference Stratum pool. "Production-shaped"
without an independent verifier is a self-report. This file translates each
phase of the pool's rollout (A: mineable MVP, B: verified accounts and
dashboards, C: PPLNS payouts, D: production polish) into a property that
anyone (including a future maintainer or external auditor) can re-verify
by running one command. It is the gate between "the agent claims the pool
shipped" and "we know the pool shipped correctly."

The verifier follows the workspace's
[`tiered-verification.mdc`](../../.cursor/rules/tiered-verification.mdc)
Tier-3 protocol (multi-component / async / state-machine code requires
explicit comment-to-code mapping, loop-location proof, and bypass-path
enumeration) and the
[`verify-before-done.mdc`](../../.cursor/rules/verify-before-done.mdc)
"the loop question" rule.
