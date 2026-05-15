# Phase 6.1 — Verification Checklist

This document is the **independent verification gate** for Phase 6.1 of the
[B3Chain implementation plan](../../B3CHAIN-IMPLEMENTATION-PLAN.md): the
internal miner (regtest/testnet `generatetoaddress` and friends) computes
proof-of-work using `GetPoWHash()` (double BLAKE3-256), not `GetHash()`
(double SHA-256).

The companion script
[`contrib/testing/audit/audit-internal-miner.sh`](../contrib/testing/audit/audit-internal-miner.sh)
runs every check and rewrites the status column of this file in place. Exit
code is **0 only if every item passes**.

The audit is also wired into
[`contrib/testing/audit/verify-phase11.sh`](../contrib/testing/audit/verify-phase11.sh)
so a single command continues to validate the full audit suite.

## Status legend

- `[x]` PASS — verifier confirmed the criterion holds
- `[!]` FAIL — verifier ran but the criterion did not hold
- `[?]` PENDING — verifier has not yet been run for this item
- `[-]` SKIP — not runnable in this environment (e.g. no built binary)

## How to run

```bash
cd b3chain
bash contrib/testing/audit/audit-internal-miner.sh           # run + rewrite this file
bash contrib/testing/audit/audit-internal-miner.sh --static  # static checks only (no daemon)
bash contrib/testing/audit/audit-internal-miner.sh --dry-run # print what would run
```

Last run: **2026-05-15 03:49**

---

## M — Internal miner (Phase 6.1)

| #     | ID   | Acceptance criterion | Verification command | Expected | Status |
|-------|------|----------------------|----------------------|----------|--------|
| M-1a  | `comment-mapping` | The comment-step "use `GetPoWHash()`" maps to a concrete code line in the internal miner's nonce loop | `grep -n 'CheckProofOfWork(block.GetPoWHash()' src/rpc/mining.cpp` | exactly 1 match inside `GenerateBlock()` | `[x]` |
| M-1b  | `loop-location` | A `while` loop in `GenerateBlock()` increments `block.nNonce` until `CheckProofOfWork(...)` passes | `awk '/^static bool GenerateBlock/,/^\}/' src/rpc/mining.cpp \| grep -cE 'while.*GetPoWHash\|\\+\\+block\\.nNonce'` | ≥2 (the `while` line and the `++nNonce` line) | `[x]` |
| M-1c  | `bypass-paths` | Every production `CheckProofOfWork(...)` call site in `src/` (excluding `src/pow.cpp`/`src/pow.h` plumbing and `src/test/` synthetic-hash fuzz inputs) passes a value derived from `GetPoWHash()`, never `GetHash()` | `grep -RnE 'CheckProofOfWork\\(' src/ --include='*.cpp' --include='*.h' \| grep -vE '^src/(pow\\.(cpp\|h)\|test/)' \| grep -vE 'GetPoWHash\|pow_hash\|powhash' \| wc -l` | 0 | `[x]` |
| M-1d  | `internal-miner-e2e` | A live regtest node mined via `generatetoaddress`, `generatetodescriptor`, and `generateblock` produces 15 blocks (5 per RPC) for which independent Python re-derivation confirms (i) `SHA256d(header) == block.GetHash()` (dual-hash ID stays SHA-256d), (ii) `BLAKE3(BLAKE3(header)) <= target_from_nbits(bits)` (miner used BLAKE3d PoW), and (iii) `BLAKE3d(header) != SHA256d(header)` (the two hash methods are independent) | `bash contrib/testing/audit/audit-internal-miner.sh --e2e-only` | exit 0; SUMMARY line reports `15 blocks across 3 RPCs (5 each), all per-block + aggregate checks PASS` | `[x]` |

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

- M-1d is skipped (`[-]`) when no `b3chaind` binary is found under
  `build/bin/` or `build/src/` (and `BINDIR` is not set).
- M-1d is skipped when the python `blake3` package is missing (the row's
  note will say `pip3 install blake3`).
- M-1a, M-1b, M-1c run from source files only and never skip.

## Findings

The audit script appends to this section every time it runs. Phase 6.1 is
considered "verified" once this section is empty after a clean run.

<!-- VERIFIER-FINDINGS-START -->
*Last verifier run: 2026-05-15 03:49*

*(clean run — no failures, no skips)*
<!-- VERIFIER-FINDINGS-END -->

## Why this document exists

The [B3Chain implementation plan](../../B3CHAIN-IMPLEMENTATION-PLAN.md)
marks Phase 6 complete in [`doc/CHANGELOG.md`](CHANGELOG.md), but
"complete" without an independent verifier is a self-report. This file
translates each step of Phase 6.1 into a property that anyone (including
a future maintainer or external auditor) can independently re-verify by
running one command. It is the gate between "the agent claims it
shipped" and "we know it shipped correctly."

The verifier follows the workspace's
[`tiered-verification.mdc`](../../.cursor/rules/tiered-verification.mdc)
Tier-3 protocol (async / loop / timing code requires explicit
comment-to-code mapping, loop-location proof, and bypass-path
enumeration) and the
[`verify-before-done.mdc`](../../.cursor/rules/verify-before-done.mdc)
"the loop question" rule.
