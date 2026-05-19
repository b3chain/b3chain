# Phase 6.3 — Verification Checklist (Stratum V2)

This document is the **independent verification gate** for Phase 6.3 of
the [B3Chain implementation plan](../../B3CHAIN-IMPLEMENTATION-PLAN.md):
the Stratum V2 stack at `contrib/testnet/pool/src/sv2/`. It mirrors the
Phase 6.2 checklist one row per phase of the SV2 rollout (A: foundation,
B: mining pool, C: template provider, D: job declaration, E: V1<->V2
translator, F: tests + e2e, G: live deploy).

The companion script
[`contrib/testing/audit/audit-stratum-v2.sh`](../contrib/testing/audit/audit-stratum-v2.sh)
runs every check and rewrites the status column of this file in place.
Exit code is **0 only if every item passes**.

The audit is wired into
[`contrib/testing/audit/verify-phase11.sh`](../contrib/testing/audit/verify-phase11.sh)
as row `P-2` so a single command continues to validate the full audit suite.

## Status legend

- `[x]` PASS — verifier confirmed the criterion holds
- `[!]` FAIL — verifier ran but the criterion did not hold
- `[?]` PENDING — verifier has not yet been run for this item
- `[-]` SKIP — not runnable in this environment (e.g. no Node.js / no live SV2 pool)

## How to run

```bash
cd b3chain
bash contrib/testing/audit/audit-stratum-v2.sh           # run + rewrite this file
bash contrib/testing/audit/audit-stratum-v2.sh --static  # static-only (no Node.js)
bash contrib/testing/audit/audit-stratum-v2.sh --dry-run # print what would run
```

Last run: **2026-05-19 20:36**

---

## S — Stratum V2 stack (Phase 6.3)

| #     | ID   | Acceptance criterion | Verification command | Expected | Status |
|-------|------|----------------------|----------------------|----------|--------|
| S-1a  | `phase-a-codec` | SV2 type encoders + frame codec round-trip cleanly with golden vectors | `cd contrib/testnet/pool && node --env-file=.env.test --test --import tsx tests/sv2-codec.test.ts 2>&1 \| grep -c '# pass'` | ≥ 13 | `[x]` |
| S-1b  | `phase-a-noise` | Noise NX handshake + transport AEAD round-trip; tampered ciphertext rejected; 106-byte SignedCertificate signs and verifies | `cd contrib/testnet/pool && node --env-file=.env.test --test --import tsx tests/sv2-noise.test.ts 2>&1 \| grep -c '# pass'` | ≥ 6 | `[x]` |
| S-1c  | `phase-a-keys` | install.sh invokes the keypair + cert generator before the SV2 services start, and publishes both the cert and the authority pubkey under nginx | `grep -cE 'sv2-keys\|sv2-authority\|sv2-static\|sv2-cert\|/sv2/cert\|/sv2/authority.hex' contrib/testnet/pool/install.sh` | ≥ 5 | `[x]` |
| S-2a  | `phase-b-mining-srv` | Native SV2 Mining Protocol pool exposes Standard + Extended channels and a Noise NX listener | `grep -cE 'OpenStandardMiningChannel\|OpenExtendedMiningChannel\|HANDSHAKE_M1\|SETUP_PENDING\|READY' contrib/testnet/pool/src/sv2/mining/server.ts` | ≥ 5 | `[x]` |
| S-2b  | `phase-b-channel` | Channel layer pins extranonce_prefix per channel and reconstructs the full 8-byte extranonce slot at submit time | `cd contrib/testnet/pool && node --env-file=.env.test --test --import tsx tests/sv2-mining.test.ts 2>&1 \| grep -c '# pass'` | ≥ 5 | `[x]` |
| S-2c  | `phase-b-share-bridge` | SV2 SubmitShares is bridged into the existing V1 share-validator and emits the protocol-agnostic ShareEvent over IPC | `grep -cE 'validateShare\|ShareEvent\|fullExtranonce' contrib/testnet/pool/src/sv2/mining/submit.ts` | ≥ 3 | `[x]` |
| S-2d  | `phase-b-systemd` | b3chain-pool-stratum-v2.service exists and runs the compiled SV2 mining entrypoint | `grep -cE 'b3chain-pool-stratum-v2\|sv2/mining/main' contrib/testnet/pool/systemd/b3chain-pool-stratum-v2.service` | ≥ 1 | `[x]` |
| S-2e  | `phase-b-migration` | sv2_sessions / sv2_channels / sv2_declared_jobs tables are created in migration 004 | `grep -cE 'CREATE TABLE.*sv2_(sessions\|channels\|declared_jobs)' contrib/testnet/pool/db/migrations/004_sv2_sessions_and_jobs.sql` | ≥ 3 | `[x]` |
| S-3a  | `phase-c-tp-msgs` | Template Distribution messages (NewTemplate / SetNewPrevHashTP / RequestTransactionData / SubmitSolutionTP / CoinbaseOutputDataSize) round-trip | `cd contrib/testnet/pool && node --env-file=.env.test --test --import tsx tests/sv2-tp.test.ts 2>&1 \| grep -c '# pass'` | ≥ 5 | `[x]` |
| S-3b  | `phase-c-tp-poller` | Template provider polls getblocktemplate and emits NewTemplate + SetNewPrevHashTP | `grep -cE 'getBlockTemplate\|emit\\(\"template\"\|encodeNewTemplate\|encodeSetNewPrevHashTP' contrib/testnet/pool/src/sv2/tp/poller.ts` | ≥ 4 | `[x]` |
| S-3c  | `phase-c-tp-systemd` | b3chain-pool-tp.service binds the entrypoint and runs as the pool user | `grep -cE 'b3chain-pool-tp\|sv2/tp/main\|User=b3chain-pool' contrib/testnet/pool/systemd/b3chain-pool-tp.service` | ≥ 2 | `[x]` |
| S-4a  | `phase-d-jd-tokens` | JD token store issues 32-byte single-use tokens with TTL and rejects re-use / expired tokens | `cd contrib/testnet/pool && node --env-file=.env.test --test --import tsx tests/sv2-jd.test.ts 2>&1 \| grep -c '# pass'` | ≥ 4 | `[x]` |
| S-4b  | `phase-d-jd-coinbase` | DeclareMiningJob coinbase validator rejects suffixes that do not pay the pool's payout address | `grep -cE 'coinbase-does-not-pay-pool\|expectedSpk\|paidPool' contrib/testnet/pool/src/sv2/jd/custom_job.ts` | ≥ 3 | `[x]` |
| S-4c  | `phase-d-jd-bridge` | JD server delivers DeclareMiningJob results into the mining pool via SetCustomMiningJob over an open Extended channel | `cat contrib/testnet/pool/src/sv2/{mining/server.ts,jd/server.ts,mining/main.ts} \| grep -cE 'SetCustomMiningJob\|pushCustomJob\|deliverCustomJob'` | ≥ 4 | `[x]` |
| S-5a  | `phase-e-translator` | V1 mining.subscribe -> SV2 OpenExtendedMiningChannel -> V1 mining.notify roundtrip works against an in-process fake pool | `cd contrib/testnet/pool && node --env-file=.env.test --test --import tsx tests/sv2-translator.test.ts 2>&1 \| grep -c '# pass'` | ≥ 1 | `[x]` |
| S-5b  | `phase-e-translator-svc` | b3chain-pool-translator.service runs sv2/translator/main.js and depends on the SV2 pool unit | `grep -cE 'b3chain-pool-translator\|sv2/translator/main\|After=.*b3chain-pool-stratum-v2' contrib/testnet/pool/systemd/b3chain-pool-translator.service` | ≥ 2 | `[x]` |
| S-6a  | `phase-f-e2e-compose` | docker-compose.e2e.yml ships pool-stratum-v2 + pool-translator services with B3POOL_SV2_ENABLE / B3POOL_TRANSLATOR_ENABLE | `grep -cE 'pool-stratum-v2:\|pool-translator:\|B3POOL_SV2_ENABLE\|B3POOL_TRANSLATOR_ENABLE' contrib/testnet/pool/tests/e2e/docker-compose.e2e.yml` | ≥ 4 | `[x]` |

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

- Rows S-1a, S-1b, S-2b, S-3a, S-4a, S-5a are skipped (`[-]`) when
  Node.js 20 is not available or the pool's `node_modules/` are not
  installed (`cd contrib/testnet/pool && npm ci`).
- All other rows run from source files only and never skip.

## Findings

The audit script appends to this section every time it runs. Phase 6.3
is considered "verified" once this section is empty after a clean run.

<!-- VERIFIER-FINDINGS-START -->
*Last verifier run: 2026-05-19 20:36*

*(clean run — no failures, no skips)*
<!-- VERIFIER-FINDINGS-END -->

## Why this document exists

The [B3Chain implementation plan](../../B3CHAIN-IMPLEMENTATION-PLAN.md)
calls for a "production-shaped" Stratum mining pool. Phase 6.2 delivered
the V1 pool; this phase adds Stratum V2 (Mining Protocol + Job
Declaration + Template Distribution + V1<->V2 translator) over a Noise
NX channel. As with Phase 6.2, "production-shaped" without an
independent verifier is a self-report; this checklist translates each
phase of the SV2 rollout into a property that anyone can re-verify in
one command.

The verifier follows the workspace's
[`tiered-verification.mdc`](../../.cursor/rules/tiered-verification.mdc)
Tier-3 protocol (multi-component / async / state-machine code requires
explicit comment-to-code mapping, loop-location proof, and bypass-path
enumeration) and the
[`verify-before-done.mdc`](../../.cursor/rules/verify-before-done.mdc)
"the loop question" rule.
