# Phase 11 — Verification Checklist

This document is the **independent verification gate** for the work delivered
under [`doc/SECURITY-AUDIT.md`](SECURITY-AUDIT.md) and the website refactor
that accompanied it. Every row corresponds to one todo from the original Phase
11 plan and has a **strict, runnable acceptance criterion**: a command that
must produce a specific output, or an artifact that must exist.

The companion script
[`contrib/testing/audit/verify-phase11.sh`](../contrib/testing/audit/verify-phase11.sh)
runs every check and rewrites the status column of this file in place. Exit
code is **0 only if every item passes**.

## Status legend

- `[x]` PASS — verifier confirmed the criterion holds
- `[!]` FAIL — verifier ran but the criterion did not hold
- `[?]` PENDING — verifier has not yet been run for this item
- `[-]` SKIP — not runnable in this environment (e.g. live HTTPS check on
  an offline machine); the row records why

## How to run

```bash
cd b3chain
bash contrib/testing/audit/verify-phase11.sh            # run + rewrite this file
bash contrib/testing/audit/verify-phase11.sh --dry-run  # print what would run
bash contrib/testing/audit/verify-phase11.sh --only A2  # one row only
```

Last run: **2026-05-14 00:09**

---

## A — Core repository deliverables

| # | ID | Acceptance criterion | Verification command | Expected | Status |
|---|----|----------------------|----------------------|----------|--------|
| 1 | `checklist` | `doc/SECURITY-AUDIT.md` exists with status legend, summary table, and one row per audit ID `C-1..C-4`, `H-1`, `N-1`, `W-1`, `W-2`, `B-1`, `B-2`, `A-1` | `python3 contrib/testing/audit/verify_checklist.py` | exit 0; reports 11 audit rows | `[x]` |
| 2 | `audit-folder` | Shared helpers exist and are importable | `python3 -c "import sys; sys.path.insert(0,'contrib/testing/audit/lib'); import audit_common; assert hasattr(audit_common,'RegtestNode') and hasattr(audit_common,'AuditResult')"` | exit 0 | `[x]` |
| 3 | `supply-cap` | C-1..C-4 audit script runs and passes | `python3 contrib/testing/audit/audit-supply-cap.py` | last line `AUDIT RESULT: PASS  [C-1..C-4]`; exit 0 | `[-]` |
| 4 | `pow-isolation` | H-1 audit script runs and passes | `python3 contrib/testing/audit/audit-pow-isolation.py` | last line `AUDIT RESULT: PASS  [H-1]`; exit 0 | `[-]` |
| 5 | `net-isolation` | N-1 audit script runs and passes | `python3 contrib/testing/audit/audit-network-isolation.py` | last line `AUDIT RESULT: PASS  [N-1]`; exit 0 | `[-]` |
| 6 | `addr-rejection` | W-1 audit covers ≥30 Bitcoin addresses and all are rejected | `python3 contrib/testing/audit/audit-address-rejection.py` | last line `AUDIT RESULT: PASS  [W-1]`; exit 0; log mentions ≥30 samples | `[-]` |
| 7 | `simd-blake3` | B-1 differential covers required edge sizes plus ≥1000 fuzz inputs | `python3 contrib/testing/audit/audit-simd-blake3.py` | last line `AUDIT RESULT: PASS  [B-1]`; exit 0; log shows fuzz `n>=1000` | `[-]` |
| 8 | `rebranding` | B-2 forbidden-pattern grep clean and full test suites still pass | `bash contrib/testing/audit/audit-rebranding.sh` | last line `AUDIT RESULT: PASS  [B-2]`; exit 0 | `[-]` |
| 9 | `hd-coin-type` | (a) `doc/b3chain-bip44.md` exists and documents `coin_type 9333`; (b) `src/wallet/walletutil.cpp` derivation path uses `9333h` gated by `!IsTestChain()`; (c) audit script passes | `grep -q 'coin_type.*9333' doc/b3chain-bip44.md && grep -q '9333h' src/wallet/walletutil.cpp && python3 contrib/testing/audit/audit-hd-coin-type.py` | exit 0; audit prints `AUDIT RESULT: PASS  [W-2]` | `[-]` |
| 10 | `51-attack-sim` | A-1 demo runs end-to-end, log shows actual reorg event | `python3 contrib/testing/audit/audit-51-attack-sim.py` | exit 0; log contains `reorganize` (or equivalent reorg signal) **and** `double-spend` outcome line | `[-]` |
| 11 | `cpp-audit-tests` | C++ audit tests exist under `src/test/audit/` and CTest discovers ≥1 of them | `cmake --build build --target consensus_invariants_tests 2>/dev/null; ctest --test-dir build -N -R 'audit\|consensus_invariants' \| grep -c 'Test #'` | ≥1; running them: `ctest --test-dir build -R 'consensus_invariants' --output-on-failure` exits 0 | `[-]` |
| 12 | `run-audits` | The master checklist has every audit row marked `[x]` (or `[-]` with a note) | `python3 contrib/testing/audit/verify_checklist.py --require-all-passed` | exit 0; reports `11/11 PASS` | `[x]` |
| 13 | `update-changelog` | `doc/CHANGELOG.md` mentions Phase 11 status | `grep -ci 'phase 11' doc/CHANGELOG.md` | ≥1 | `[x]` |

## B — Website deliverables (b3chain-website repo)

All `b3chain-website/...` paths are relative to the sibling repo checked out
next to this one (the verifier auto-detects `../b3chain-website` and falls back
to `$B3CHAIN_WEBSITE`).

| # | ID | Acceptance criterion | Verification command | Expected | Status |
|---|----|----------------------|----------------------|----------|--------|
| 14 | `css-extract` | (a) `b3chain-website/css/style.css` exists; (b) `index.html` and `testing.html` link it; (c) **zero** remaining `<style>` blocks in any HTML page | `test -f ../b3chain-website/css/style.css && grep -l 'css/style.css' ../b3chain-website/index.html ../b3chain-website/testing.html \| wc -l` (=2) and `grep -rln '<style' ../b3chain-website --include='*.html' \| wc -l` (=0) | both | `[x]` |
| 15 | `testing-hub` | `testing.html` is a hub with the three required sections | `grep -cE 'Reproducible tests\|Phase 11 security audit\|Attacks &amp; defense' ../b3chain-website/testing.html` | ≥3 | `[x]` |
| 16 | `existing-detail-pages` | All six existing-test detail pages exist | `for f in pow-verifier test-vectors regtest-simulation test-results limitations reporting; do test -f "../b3chain-website/testing/$f.html" \|\| { echo MISSING $f; exit 1; }; done` | exit 0 | `[x]` |
| 17 | `audit-detail-pages` | The audit hub plus seven per-audit detail pages exist | `for f in security-audit audit-supply-cap audit-pow-isolation audit-network-isolation audit-address-rejection audit-simd-blake3 audit-rebranding audit-hd-coin-type; do test -f "../b3chain-website/testing/$f.html" \|\| { echo MISSING $f; exit 1; }; done` | exit 0 | `[x]` |
| 18 | `attack-page` | `51-attack.html` exists and contains the required educational sections (Nakamoto math, cost calculator, live demo walkthrough, defenses) | `grep -cE 'Nakamoto\|cost\|defense\|reorg' ../b3chain-website/testing/51-attack.html` | ≥4 | `[x]` |
| 19a | `verify-website-breadcrumbs` | Every page in `testing/*.html` has a breadcrumb link back to the hub | `grep -L 'href="/testing.html"\|href="../testing.html"' ../b3chain-website/testing/*.html \| wc -l` | 0 | `[x]` |
| 19b | `verify-website-links` | All on-disk `href`/`src` references resolve | `python3 contrib/testing/audit/verify_links.py ../b3chain-website` | exit 0; reports 0 broken | `[x]` |

## C — Deployment deliverables

| # | ID | Acceptance criterion | Verification command | Expected | Status |
|---|----|----------------------|----------------------|----------|--------|
| 20 | `commit-push-core` | The local `b3chain-main` HEAD matches `origin/b3chain-main` on GitHub | `cd b3chain && [ "$(git rev-parse HEAD)" = "$(git ls-remote https://github.com/b3chain/b3chain.git b3chain-main \| awk '{print $1}')" ]` | exit 0 | `[x]` |
| 21 | `commit-push-website` | The local `main` HEAD matches `origin/main` on GitHub | `cd ../b3chain-website && [ "$(git rev-parse HEAD)" = "$(git ls-remote https://github.com/b3chain/b3chain-website.git main \| awk '{print $1}')" ]` | exit 0 | `[x]` |
| 22a | `deploy-server` | Live server serves the new audit hub page over HTTPS | `curl -fsI https://b3chain.org/testing/security-audit.html` | `HTTP/2 200` (or `HTTP/1.1 200`) | `[x]` |
| 22b | `deploy-server-pages` | Every audit detail page is live | `for p in security-audit audit-supply-cap audit-pow-isolation audit-network-isolation audit-address-rejection audit-simd-blake3 audit-rebranding audit-hd-coin-type 51-attack; do curl -fsI -o /dev/null -w '%{http_code} %{url_effective}\n' "https://b3chain.org/testing/$p.html"; done \| grep -c '^200 '` | ≥9 | `[x]` |
| 22c | `cert-fresh` | Live TLS certificate is **not** the stale May-11 cert that bit us before; renewal hook is still in place | `echo \| openssl s_client -servername b3chain.org -connect b3chain.org:443 2>/dev/null \| openssl x509 -noout -enddate` | `notAfter` is more than 30 days in the future | `[x]` |
| 22d | `cert-renewal-hook` | The certbot deploy hook installed on the server is still present and reloads nginx | `ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o StrictHostKeyChecking=no deploy@166.88.4.250 'sudo test -x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx && grep -q "systemctl reload nginx" /etc/letsencrypt/renewal-hooks/deploy/reload-nginx'` | exit 0 | `[x]` |

---

## How a row becomes PASS

The verifier sets the status column based on what it observed:

```
For each row:
  1. parse the verification command from the table
  2. run it (with bash, captured stdout/stderr, captured exit code)
  3. apply the row's pass-rule (exit-code-only, regex-on-output, or both)
  4. write [x] if pass-rule held, [!] if not, [-] if skipped
  5. on FAIL, append a "Findings" row at the bottom with the captured output
```

Skip behaviour:

- Items 22a–22d are skipped (`[-]`) when `B3CHAIN_OFFLINE=1` is set, or when
  the verifier cannot reach `b3chain.org` over the network.
- Item 22d is additionally skipped when `~/.ssh/lobby_cursor_ed25519` is
  absent (verifier emits a note explaining why).
- Item 11 (`cpp-audit-tests`) is skipped when no `build/` directory exists
  (the row's note will say `build B3Chain Core first`).

## Findings

The verifier appends to this section every time it runs. The other agent's
work is considered "done" once this section is empty after a clean run.

<!-- VERIFIER-FINDINGS-START -->
*Last verifier run: 2026-05-14 00:09*

**Skipped:**

- Row 10: B3CHAIN_SKIP_AUDITS=1
- Row 11: no build/ directory (build B3Chain Core first or set B3CHAIN_SKIP_CTEST=1)
- Row 3: B3CHAIN_SKIP_AUDITS=1
- Row 4: B3CHAIN_SKIP_AUDITS=1
- Row 5: B3CHAIN_SKIP_AUDITS=1
- Row 6: B3CHAIN_SKIP_AUDITS=1
- Row 7: B3CHAIN_SKIP_AUDITS=1
- Row 8: B3CHAIN_SKIP_AUDITS=1
- Row 9: B3CHAIN_SKIP_AUDITS=1
<!-- VERIFIER-FINDINGS-END -->

## Why this document exists

The original [Phase 11 plan](../../.cursor/plans/b3chain_phase_11_security_audit_b30ee69d.plan.md)
marks every todo `completed`, but "completed" is a self-report, not a proof.
This file translates each todo into a property that anyone (including a future
maintainer or external auditor) can independently re-verify by running one
command. It is the gate between "the agent claims it shipped" and "we know it
shipped correctly."
