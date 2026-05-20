#!/usr/bin/env bash
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# Phase 6.2 verifier — proves the Stratum mining pool at
# contrib/testnet/pool/ ships the four phases (A: mineable MVP,
# B: verified accounts, C: PPLNS payouts, D: production polish)
# with the contracts documented in doc/PHASE-6.2-VERIFICATION.md.
#
# Runs every check from doc/PHASE-6.2-VERIFICATION.md, rewrites the
# status column of that file in place, and exits non-zero on any failure.
#
# Usage:
#   bash contrib/testing/audit/audit-stratum-pool.sh
#   bash contrib/testing/audit/audit-stratum-pool.sh --static    # static checks only
#   bash contrib/testing/audit/audit-stratum-pool.sh --dry-run
#
# Environment:
#   B3CHAIN_SKIP_NODE=1   skip the Node-test based checks (P-1d, P-2c, P-3a, P-4a)

export LC_ALL=C
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

CHECKLIST="$REPO_ROOT/doc/PHASE-6.2-VERIFICATION.md"
POOL_DIR="$REPO_ROOT/contrib/testnet/pool"

DRY_RUN=0
MODE="all"
while [ $# -gt 0 ]; do
    case "$1" in
        --static)    MODE="static" ;;
        --dry-run)   DRY_RUN=1 ;;
        -h|--help)   sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_BOLD=$'\033[1m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
    C_YELLOW=$'\033[33m'; C_DIM=$'\033[2m'; C_NC=$'\033[0m'
else
    C_BOLD=""; C_GREEN=""; C_RED=""; C_YELLOW=""; C_DIM=""; C_NC=""
fi

declare -A RESULT
declare -A NOTE
declare -A LOGFILE
TMPDIR_LOG="$(mktemp -d -t b3chain-audit-pool.XXXXXX)"
trap 'rm -rf "$TMPDIR_LOG"' EXIT

mark() {
    local id="$1" st="$2" note="${3:-}"
    RESULT[$id]="$st"
    [ -n "$note" ] && NOTE[$id]="$note"
    case "$st" in
        PASS) printf "  ${C_GREEN}PASS${C_NC}  %s%s\n" "$id" "${note:+  ${C_DIM}$note${C_NC}}" ;;
        FAIL) printf "  ${C_RED}FAIL${C_NC}  %s%s\n" "$id" "${note:+  $note}" ;;
        SKIP) printf "  ${C_YELLOW}SKIP${C_NC}  %s%s\n" "$id" "${note:+  ${C_DIM}$note${C_NC}}" ;;
    esac
}

run_check() {
    # run_check ID DESC SHELL_CMD OP EXPECTED
    local id="$1" desc="$2" cmd="$3" op="$4" expected="$5"
    local logf="$TMPDIR_LOG/$id.log"
    LOGFILE[$id]="$logf"
    printf "${C_BOLD}[%s]${C_NC} %s\n" "$id" "$desc"
    if [ "$DRY_RUN" = 1 ]; then
        printf "  ${C_DIM}DRY-RUN: %s${C_NC}\n" "$cmd"
        mark "$id" SKIP "dry-run"
        return
    fi
    local actual
    actual=$(bash -c "$cmd" 2>"$logf") || true
    printf '%s\n' "$actual" >>"$logf"
    case "$op" in
        eq)        if [ "$actual" = "$expected" ];      then mark "$id" PASS "got $actual"; else mark "$id" FAIL "got $actual, expected $expected"; fi ;;
        ge)        if [ "$actual" -ge "$expected" ] 2>/dev/null; then mark "$id" PASS "got $actual"; else mark "$id" FAIL "got $actual, expected >=$expected"; fi ;;
        nonempty)  if [ -n "$actual" ]; then mark "$id" PASS "got $(echo "$actual" | head -1)"; else mark "$id" FAIL "empty output"; fi ;;
        *)         mark "$id" FAIL "unknown op $op" ;;
    esac
}

skip_node_check() {
    # skip_node_check ID REASON
    mark "$1" SKIP "$2"
}

have_node() {
    command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1
}

node_modules_present() {
    [ -d "$POOL_DIR/node_modules/@noble/hashes" ] && [ -d "$POOL_DIR/node_modules/tsx" ]
}

# ---------------------------------------------------------------------------
# Static checks (no Node.js required)
# ---------------------------------------------------------------------------
do_static_checks() {
    echo
    echo "${C_BOLD}Static checks (source-only)${C_NC}"
    echo

    # P-1a: stratum server has subscribe + authorize + submit handlers
    run_check "P-1a" "phase-a-stratum-server: 3 Stratum methods present" \
        "grep -cE 'mining\\.(subscribe|authorize|submit)' '$POOL_DIR/src/stratum/server.ts'" \
        ge 3

    # P-1b: share-validator implements a PoW hash over the header.
    # B3PoW-Scratch v1.1 update: a TypeScript port of B3PoW-Scratch
    # is pending (out of scope for this PoW rename). For now the pool
    # still uses blake3d() as the share-pow shim; this check accepts
    # either symbol so the upgrade lands without breaking the audit.
    run_check "P-1b" "phase-a-share-validator: (blake3d|b3pow) used in validator" \
        "grep -lE '(blake3d|b3pow|b3powScratch)\\(.*header.*\\)' '$POOL_DIR/src/stratum/share-validator.ts' | wc -l" \
        ge 1

    # P-1c: job manager polls getblocktemplate
    run_check "P-1c" "phase-a-template-poller: getBlockTemplate + template-error" \
        "grep -cE 'getBlockTemplate|template-error' '$POOL_DIR/src/stratum/job-manager.ts'" \
        ge 2

    # P-2a: schema has all five tables
    run_check "P-2a" "phase-b-schema: 5 critical tables in 001_init.sql" \
        "grep -cE 'CREATE TABLE.*\\b(users|workers|sessions|email_verify_tokens|password_reset_tokens)\\b' '$POOL_DIR/db/migrations/001_init.sql'" \
        ge 5

    # P-2b: auth router covers the full flow
    run_check "P-2b" "phase-b-auth-flow: 10 endpoint handlers" \
        "grep -cE '(r\\.get|r\\.post)\\(\"/(signup|verify-email|login|forgot|reset|2fa-setup|2fa-verify|logout|2fa-disable)\"' '$POOL_DIR/src/web/routes/auth.ts'" \
        ge 10

    # P-3b: payout job uses transactional debit + sendmany
    run_check "P-3b" "phase-c-payout-job: transactional debit + sendmany + recipients ledger" \
        "grep -cE 'sendMany|payout_recipients|delta_b3c|tx\\(' '$POOL_DIR/src/pool/payout-job.ts'" \
        ge 4

    # P-3c: confirmer + pplns flag
    run_check "P-3c" "phase-c-block-confirmer: pplns_credited + creditPplns + B3POOL_BLOCK_CONFIRMATIONS wiring" \
        "grep -cE 'pplns_credited|blockConfirmations|creditPplns' '$POOL_DIR/src/pool/block-confirmer.ts' '$POOL_DIR/src/pool/pplns.ts' | awk -F: '{s+=\$NF} END {print s}'" \
        ge 3

    # P-4b: rate limiters wired in auth router
    run_check "P-4b" "phase-d-rate-limit: authLimiter + signupLimiter + passwordResetLimiter" \
        "grep -cE 'authLimiter|signupLimiter|passwordResetLimiter' '$POOL_DIR/src/web/routes/auth.ts'" \
        ge 3

    # P-4c: prometheus metrics
    run_check "P-4c" "phase-d-metrics: 12 b3chain_pool_* lines (HELP + value per metric)" \
        "grep -cE 'b3chain_pool_[a-z_]+' '$POOL_DIR/src/web/routes/metrics.ts'" \
        ge 12

    # P-4d: runbook scenarios
    run_check "P-4d" "phase-d-runbook: pool-down + orphan + balance scenarios" \
        "grep -ciE 'pool is down|orphan|balance' '$POOL_DIR/docs/OPERATOR-RUNBOOK.md'" \
        ge 3
}

# ---------------------------------------------------------------------------
# Node-test checks (require Node.js + node_modules in pool dir)
# ---------------------------------------------------------------------------
do_node_checks() {
    echo
    echo "${C_BOLD}Node test checks${C_NC}"
    echo

    if [ "${B3CHAIN_SKIP_NODE:-0}" = "1" ]; then
        for id in P-1d P-2c P-3a P-4a; do
            skip_node_check "$id" "B3CHAIN_SKIP_NODE=1"
        done
        return
    fi

    if ! have_node; then
        for id in P-1d P-2c P-3a P-4a; do
            skip_node_check "$id" "node/npm not installed"
        done
        return
    fi

    if ! node_modules_present; then
        for id in P-1d P-2c P-3a P-4a; do
            skip_node_check "$id" "run 'cd $POOL_DIR && npm ci' first"
        done
        return
    fi

    # Count TAP "ok N - ..." lines (one per passing subtest); the
    # previous "grep -c '# pass'" was matching only the single summary
    # line "# pass N" once, regardless of N.
    run_check "P-1d" "phase-a-blake3-vector: tests/blake3.test.ts" \
        "cd '$POOL_DIR' && node --test --import tsx tests/blake3.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 3

    run_check "P-2c" "phase-b-address-validator: tests/address.test.ts" \
        "cd '$POOL_DIR' && node --test --import tsx tests/address.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 6

    run_check "P-3a" "phase-c-pplns-math: tests/pplns.test.ts (worked example)" \
        "cd '$POOL_DIR' && node --test --import tsx tests/pplns.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 5

    run_check "P-4a" "phase-d-vardiff: tests/vardiff.test.ts" \
        "cd '$POOL_DIR' && node --test --import tsx tests/vardiff.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 4
}

case "$MODE" in
    static)  do_static_checks ;;
    all)     do_static_checks; do_node_checks ;;
esac

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
pass=0; fail=0; skip=0
for id in "${!RESULT[@]}"; do
    case "${RESULT[$id]}" in
        PASS) pass=$((pass+1)) ;;
        FAIL) fail=$((fail+1)) ;;
        SKIP) skip=$((skip+1)) ;;
    esac
done

echo
printf "${C_BOLD}=========================================================================${C_NC}\n"
printf "${C_BOLD}  Phase 6.2 stratum-pool verification summary${C_NC}\n"
printf "${C_BOLD}=========================================================================${C_NC}\n"
printf "  ${C_GREEN}PASS${C_NC}: %3d   ${C_RED}FAIL${C_NC}: %3d   ${C_YELLOW}SKIP${C_NC}: %3d\n" "$pass" "$fail" "$skip"
echo

# ---------------------------------------------------------------------------
# Rewrite checklist
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = 0 ] && [ -f "$CHECKLIST" ]; then
    {
        for id in "${!RESULT[@]}"; do
            printf '%s\t%s\t%s\n' "$id" "${RESULT[$id]}" "${NOTE[$id]:-}"
        done
    } > "$TMPDIR_LOG/_results.tsv"

    python3 - "$CHECKLIST" "$TMPDIR_LOG" <<'PYEOF'
import sys, re, datetime
from pathlib import Path

checklist = Path(sys.argv[1])
logdir    = Path(sys.argv[2])
text = checklist.read_text(encoding="utf-8")

results, notes = {}, {}
rfile = logdir / "_results.tsv"
if rfile.is_file():
    for line in rfile.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        rid = parts[0]
        st  = parts[1] if len(parts) > 1 else ""
        nt  = parts[2] if len(parts) > 2 else ""
        results[rid] = {"PASS": "[x]", "FAIL": "[!]", "SKIP": "[-]"}.get(st, "[?]")
        if nt:
            notes[rid] = nt

def replace_row(line: str) -> str:
    m = re.match(r'^(\|\s*)(P-\d[a-z])(\s*\|.*?\|\s*)`?\[[x!\?\- ]\]`?(\s*\|)\s*$', line)
    if not m:
        return line
    rid = m.group(2)
    new = results.get(rid)
    if not new:
        return line
    return f"{m.group(1)}{rid}{m.group(3)}`{new}`{m.group(4)}"

new_lines = [replace_row(l) for l in text.splitlines()]
new_text  = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")

fail_blocks = []
for rid, st in sorted(results.items()):
    if st != "[!]":
        continue
    log = (logdir / f"{rid}.log")
    body = log.read_text(encoding="utf-8", errors="replace").strip() if log.is_file() else "(no log)"
    note = notes.get(rid, "")
    header = f"### Row {rid}" + (f" — {note}" if note else "")
    fail_blocks.append(f"{header}\n\n```\n{body}\n```\n")

skip_blocks = []
for rid, st in sorted(results.items()):
    if st != "[-]":
        continue
    note = notes.get(rid, "")
    skip_blocks.append(f"- Row {rid}: {note or '(no reason)'}")

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
parts = []
if fail_blocks:
    parts.append("**Failures:**\n\n" + "\n".join(fail_blocks))
if skip_blocks:
    parts.append("**Skipped:**\n\n" + "\n".join(skip_blocks))
if not parts:
    parts.append("*(clean run — no failures, no skips)*")
body = "\n\n".join(parts)
new_text = re.sub(
    r"<!-- VERIFIER-FINDINGS-START -->.*?<!-- VERIFIER-FINDINGS-END -->",
    f"<!-- VERIFIER-FINDINGS-START -->\n*Last verifier run: {now}*\n\n{body}\n<!-- VERIFIER-FINDINGS-END -->",
    new_text,
    flags=re.DOTALL,
)
new_text = re.sub(r"^Last run:.*$", f"Last run: **{now}**", new_text, count=1, flags=re.MULTILINE)
checklist.write_text(new_text, encoding="utf-8")

p = sum(1 for v in results.values() if v == "[x]")
f = sum(1 for v in results.values() if v == "[!]")
s = sum(1 for v in results.values() if v == "[-]")
print(f"  wrote {checklist}  ({p} PASS, {f} FAIL, {s} SKIP)")
PYEOF
fi

if [ "$fail" -gt 0 ]; then
    printf "\n${C_RED}OVERALL: FAIL${C_NC}  ($fail check(s) failed; logs in $TMPDIR_LOG)\n"
    cp -r "$TMPDIR_LOG" "$REPO_ROOT/.audit-stratum-pool-last-run" 2>/dev/null || true
    trap - EXIT
    exit 1
fi
printf "${C_GREEN}OVERALL: PASS${C_NC}  ($pass passed, $skip skipped)\n"
exit 0
