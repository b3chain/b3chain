#!/usr/bin/env bash
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# Phase 6.3 verifier — proves the Stratum V2 stack at
# contrib/testnet/pool/src/sv2/ ships the seven phases (A: foundation,
# B: mining pool, C: template provider, D: job declaration,
# E: V1<->V2 translator, F: tests/e2e, G: deploy) with the contracts
# documented in doc/PHASE-6.3-VERIFICATION.md.
#
# Runs every check from doc/PHASE-6.3-VERIFICATION.md, rewrites the
# status column of that file in place, and exits non-zero on any failure.
#
# Usage:
#   bash contrib/testing/audit/audit-stratum-v2.sh
#   bash contrib/testing/audit/audit-stratum-v2.sh --static    # static checks only
#   bash contrib/testing/audit/audit-stratum-v2.sh --dry-run
#
# Environment:
#   B3CHAIN_SKIP_NODE=1   skip the Node-test based checks

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

CHECKLIST="$REPO_ROOT/doc/PHASE-6.3-VERIFICATION.md"
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
TMPDIR_LOG="$(mktemp -d -t b3chain-audit-sv2.XXXXXX)"
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
    mark "$1" SKIP "$2"
}

have_node() {
    command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1
}

node_modules_present() {
    [ -d "$POOL_DIR/node_modules/@noble/curves" ] && \
        [ -d "$POOL_DIR/node_modules/@noble/ciphers" ] && \
        [ -d "$POOL_DIR/node_modules/tsx" ]
}

# ---------------------------------------------------------------------------
# Static checks (no Node.js required)
# ---------------------------------------------------------------------------
do_static_checks() {
    echo
    echo "${C_BOLD}Static checks (source-only)${C_NC}"
    echo

    # S-1c: install.sh wires SV2 keys + cert + nginx fetch path
    run_check "S-1c" "phase-a-keys: install.sh runs sv2-keys + publishes cert" \
        "grep -cE 'sv2-keys|sv2-authority|sv2-static|sv2-cert|/sv2/cert|/sv2/authority.hex' '$POOL_DIR/install.sh'" \
        ge 5

    # S-2a: SV2 mining server has channel + state machine
    run_check "S-2a" "phase-b-mining-srv: state machine + channel ops" \
        "grep -cE 'OpenStandardMiningChannel|OpenExtendedMiningChannel|HANDSHAKE_M1|SETUP_PENDING|READY' '$POOL_DIR/src/sv2/mining/server.ts'" \
        ge 5

    # S-2c: shares bridged to V1 validator
    run_check "S-2c" "phase-b-share-bridge: validateShare + ShareEvent + fullExtranonce" \
        "grep -cE 'validateShare|ShareEvent|fullExtranonce' '$POOL_DIR/src/sv2/mining/submit.ts'" \
        ge 3

    # S-2d: systemd unit
    run_check "S-2d" "phase-b-systemd: b3chain-pool-stratum-v2.service binds entrypoint" \
        "grep -cE 'b3chain-pool-stratum-v2|sv2/mining/main' '$POOL_DIR/systemd/b3chain-pool-stratum-v2.service'" \
        ge 1

    # S-2e: migration tables
    run_check "S-2e" "phase-b-migration: sv2_sessions/channels/declared_jobs tables" \
        "grep -cE 'CREATE TABLE.*sv2_(sessions|channels|declared_jobs)' '$POOL_DIR/db/migrations/004_sv2_sessions_and_jobs.sql'" \
        ge 3

    # S-3b: TP poller
    run_check "S-3b" "phase-c-tp-poller: getBlockTemplate + emit template + encodeNew*" \
        "grep -cE 'getBlockTemplate|emit\\(\"template\"|encodeNewTemplate|encodeSetNewPrevHashTP' '$POOL_DIR/src/sv2/tp/poller.ts'" \
        ge 4

    # S-3c: TP systemd
    run_check "S-3c" "phase-c-tp-systemd: b3chain-pool-tp.service uses sv2/tp/main" \
        "grep -cE 'b3chain-pool-tp|sv2/tp/main|User=b3chain-pool' '$POOL_DIR/systemd/b3chain-pool-tp.service'" \
        ge 2

    # S-4b: JD coinbase enforcement
    run_check "S-4b" "phase-d-jd-coinbase: rejects coinbases that don't pay the pool" \
        "grep -cE 'coinbase-does-not-pay-pool|expectedSpk|paidPool' '$POOL_DIR/src/sv2/jd/custom_job.ts'" \
        ge 3

    # S-4c: JD bridge
    run_check "S-4c" "phase-d-jd-bridge: SetCustomMiningJob + pushCustomJob + deliverCustomJob" \
        "cat '$POOL_DIR/src/sv2/mining/server.ts' '$POOL_DIR/src/sv2/jd/server.ts' '$POOL_DIR/src/sv2/mining/main.ts' | grep -cE 'SetCustomMiningJob|pushCustomJob|deliverCustomJob'" \
        ge 4

    # S-5b: translator systemd
    run_check "S-5b" "phase-e-translator-svc: depends on stratum-v2 + runs sv2/translator/main" \
        "grep -cE 'b3chain-pool-translator|sv2/translator/main|After=.*b3chain-pool-stratum-v2' '$POOL_DIR/systemd/b3chain-pool-translator.service'" \
        ge 2

    # S-6a: e2e compose ships SV2 + translator
    run_check "S-6a" "phase-f-e2e-compose: SV2 + translator services + enable flags" \
        "grep -cE 'pool-stratum-v2:|pool-translator:|B3POOL_SV2_ENABLE|B3POOL_TRANSLATOR_ENABLE' '$POOL_DIR/tests/e2e/docker-compose.e2e.yml'" \
        ge 4
}

# ---------------------------------------------------------------------------
# Node-test checks
# ---------------------------------------------------------------------------
do_node_checks() {
    echo
    echo "${C_BOLD}Node test checks${C_NC}"
    echo

    if [ "${B3CHAIN_SKIP_NODE:-0}" = "1" ]; then
        for id in S-1a S-1b S-2b S-3a S-4a S-5a; do
            skip_node_check "$id" "B3CHAIN_SKIP_NODE=1"
        done
        return
    fi

    if ! have_node; then
        for id in S-1a S-1b S-2b S-3a S-4a S-5a; do
            skip_node_check "$id" "node/npm not installed"
        done
        return
    fi

    if ! node_modules_present; then
        for id in S-1a S-1b S-2b S-3a S-4a S-5a; do
            skip_node_check "$id" "run 'cd $POOL_DIR && npm ci' first"
        done
        return
    fi

    # See audit-stratum-pool.sh: count TAP "ok N - ..." pass markers,
    # not the single "# pass N" summary line.  We source .env.test via
    # `set -a; . ./.env.test; set +a` instead of `node --env-file=`
    # because the latter requires Node 20.6+ and not all CI hosts ship
    # that yet (Ubuntu 24.04 ships Node 18).
    run_check "S-1a" "phase-a-codec: tests/sv2-codec.test.ts" \
        "cd '$POOL_DIR' && set -a && . ./.env.test && set +a && node --test --import tsx tests/sv2-codec.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 13

    run_check "S-1b" "phase-a-noise: tests/sv2-noise.test.ts" \
        "cd '$POOL_DIR' && set -a && . ./.env.test && set +a && node --test --import tsx tests/sv2-noise.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 6

    run_check "S-2b" "phase-b-channel: tests/sv2-mining.test.ts" \
        "cd '$POOL_DIR' && set -a && . ./.env.test && set +a && node --test --import tsx tests/sv2-mining.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 5

    run_check "S-3a" "phase-c-tp-msgs: tests/sv2-tp.test.ts" \
        "cd '$POOL_DIR' && set -a && . ./.env.test && set +a && node --test --import tsx tests/sv2-tp.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 5

    run_check "S-4a" "phase-d-jd-tokens: tests/sv2-jd.test.ts" \
        "cd '$POOL_DIR' && set -a && . ./.env.test && set +a && node --test --import tsx tests/sv2-jd.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 4

    run_check "S-5a" "phase-e-translator: tests/sv2-translator.test.ts" \
        "cd '$POOL_DIR' && set -a && . ./.env.test && set +a && node --test --import tsx tests/sv2-translator.test.ts 2>&1 | grep -cE '^ok [0-9]'" \
        ge 1
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
printf "${C_BOLD}  Phase 6.3 stratum-v2 verification summary${C_NC}\n"
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
    m = re.match(r'^(\|\s*)(S-\d[a-z])(\s*\|.*?\|\s*)`?\[[x!\?\- ]\]`?(\s*\|)\s*$', line)
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
    cp -r "$TMPDIR_LOG" "$REPO_ROOT/.audit-stratum-v2-last-run" 2>/dev/null || true
    trap - EXIT
    exit 1
fi
printf "${C_GREEN}OVERALL: PASS${C_NC}  ($pass passed, $skip skipped)\n"
exit 0
