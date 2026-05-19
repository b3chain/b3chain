#!/usr/bin/env bash
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# Phase 6.1 verifier — proves the internal miner (regtest/testnet
# generatetoaddress / generatetodescriptor / generateblock) computes
# proof-of-work using GetPoWHash() (B3PoW-Scratch v1.1), not GetHash()
# (SHA-256d).  See contrib/miner/b3miner-rtl/SPEC.md for the PoW spec.
#
# Runs every check from doc/PHASE-6-VERIFICATION.md, rewrites the status
# column of that file in place, and exits non-zero on any failure.
#
# Usage:
#   bash contrib/testing/audit/audit-internal-miner.sh
#   bash contrib/testing/audit/audit-internal-miner.sh --static    # static checks only
#   bash contrib/testing/audit/audit-internal-miner.sh --e2e-only  # live regtest only
#   bash contrib/testing/audit/audit-internal-miner.sh --dry-run
#
# Environment:
#   BINDIR=/path/to/build/bin     override binary location
#   B3CHAIN_SKIP_E2E=1            skip the live regtest end-to-end check

set -uo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

CHECKLIST="$REPO_ROOT/doc/PHASE-6-VERIFICATION.md"
LIB_DIR="$SCRIPT_DIR/lib"

DRY_RUN=0
MODE="all"
while [ $# -gt 0 ]; do
    case "$1" in
        --static)    MODE="static" ;;
        --e2e-only)  MODE="e2e" ;;
        --dry-run)   DRY_RUN=1 ;;
        -h|--help)   sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_BOLD=$'\033[1m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
    C_YELLOW=$'\033[33m'; C_DIM=$'\033[2m'; C_NC=$'\033[0m'
else
    C_BOLD=""; C_GREEN=""; C_RED=""; C_YELLOW=""; C_DIM=""; C_NC=""
fi

declare -A RESULT      # id -> PASS|FAIL|SKIP
declare -A NOTE        # id -> short note
declare -A LOGFILE     # id -> path to captured log
TMPDIR_LOG="$(mktemp -d -t b3chain-audit-miner.XXXXXX)"
trap 'rm -rf "$TMPDIR_LOG"' EXIT

mark() {
    # mark ID STATUS [NOTE]
    local id="$1" st="$2" note="${3:-}"
    RESULT[$id]="$st"
    [ -n "$note" ] && NOTE[$id]="$note"
    case "$st" in
        PASS) printf "  ${C_GREEN}PASS${C_NC}  %s%s\n" "$id" "${note:+  ${C_DIM}$note${C_NC}}" ;;
        FAIL) printf "  ${C_RED}FAIL${C_NC}  %s%s\n" "$id" "${note:+  $note}" ;;
        SKIP) printf "  ${C_YELLOW}SKIP${C_NC}  %s%s\n" "$id" "${note:+  ${C_DIM}$note${C_NC}}" ;;
    esac
}

run_static() {
    # run_static ID DESC SHELL_CMD EXPECTED_OP EXPECTED_VALUE
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
        eq)   if [ "$actual" = "$expected" ];      then mark "$id" PASS "got $actual"; else mark "$id" FAIL "got $actual, expected $expected"; fi ;;
        ge)   if [ "$actual" -ge "$expected" ] 2>/dev/null; then mark "$id" PASS "got $actual"; else mark "$id" FAIL "got $actual, expected >=$expected"; fi ;;
        nonempty) if [ -n "$actual" ]; then mark "$id" PASS "got $(echo "$actual" | head -1)"; else mark "$id" FAIL "empty output"; fi ;;
        *)    mark "$id" FAIL "unknown op $op" ;;
    esac
}

# ---------------------------------------------------------------------------
# Static checks (M-1a, M-1b, M-1c)
# ---------------------------------------------------------------------------
do_static_checks() {
    echo
    echo "${C_BOLD}Static checks (source-only, no daemon)${C_NC}"
    echo

    # M-1a: comment-step "use GetPoWHash() with a B3PoW pad" maps to a
    # concrete code line in the internal miner's nonce loop.  v1.1
    # nonce loop calls block.GetPoWHash(block.hashPrevBlock, pad, ...).
    run_static "M-1a" "comment-mapping: GenerateBlock() loop calls block.GetPoWHash(block.hashPrevBlock, pad, ...)" \
        "grep -c 'block\\.GetPoWHash(block\\.hashPrevBlock' src/rpc/mining.cpp" \
        eq 1

    # M-1a.2: GenerateBlock() initialises the 1 MB scratchpad exactly
    # once (outside the nonce loop) via b3pow::InitScratchpad.
    run_static "M-1a.2" "comment-mapping: GenerateBlock() calls b3pow::InitScratchpad once" \
        "grep -c 'b3pow::InitScratchpad' src/rpc/mining.cpp" \
        eq 1

    # M-1b: a while loop in GenerateBlock() increments block.nNonce until the
    # PoW check passes. We extract just the GenerateBlock function body and
    # count the characteristic lines (the GetPoWHash call and the ++nNonce).
    run_static "M-1b" "loop-location: while-loop + ++nNonce inside GenerateBlock()" \
        "awk '/^static bool GenerateBlock/,/^\\}/' src/rpc/mining.cpp | grep -cE 'GetPoWHash\\(block\\.hashPrevBlock|\\+\\+block\\.nNonce'" \
        ge 2

    # M-1c: every production CheckProofOfWork() call site outside pow.{cpp,h}
    # plumbing and outside test/ (synthetic-hash fuzz inputs) passes a value
    # derived from GetPoWHash().  *pow_hash_opt is the v1.1 idiom (the
    # optional returned by GetPoWHash()).
    run_static "M-1c" "bypass-paths: 0 production call sites use a non-PoW hash" \
        "grep -RnE 'CheckProofOfWork\\(' src/ --include='*.cpp' --include='*.h' | grep -vE '^src/(pow\\.(cpp|h)|test/)' | grep -vE 'GetPoWHash|pow_hash|powhash|\\*pow_opt|\\*pow_hash_opt' | wc -l" \
        eq 0
}

# ---------------------------------------------------------------------------
# Live regtest end-to-end check (M-1d)
# ---------------------------------------------------------------------------
do_e2e_check() {
    echo
    echo "${C_BOLD}End-to-end check (live regtest node, B3PoW-Scratch verification)${C_NC}"
    echo

    if [ "$DRY_RUN" = 1 ]; then
        printf "${C_BOLD}[M-1d]${C_NC} ${C_DIM}DRY-RUN: would spawn regtest node and verify 15 blocks${C_NC}\n"
        mark "M-1d" SKIP "dry-run"
        return
    fi

    if [ "${B3CHAIN_SKIP_E2E:-0}" = "1" ]; then
        mark "M-1d" SKIP "B3CHAIN_SKIP_E2E=1"
        return
    fi

    # Locate b3chaind
    local b3chaind=""
    if [ -n "${BINDIR:-}" ] && [ -x "$BINDIR/b3chaind" ]; then
        b3chaind="$BINDIR/b3chaind"
    elif [ -x "$REPO_ROOT/build/bin/b3chaind" ]; then
        b3chaind="$REPO_ROOT/build/bin/b3chaind"
    elif [ -x "$REPO_ROOT/build/src/b3chaind" ]; then
        b3chaind="$REPO_ROOT/build/src/b3chaind"
    else
        mark "M-1d" SKIP "no b3chaind binary (build the project or set BINDIR)"
        return
    fi

    # Verify python blake3 module
    if ! python3 -c "import blake3" 2>/dev/null; then
        mark "M-1d" SKIP "python blake3 module missing (pip3 install blake3)"
        return
    fi

    local logf="$TMPDIR_LOG/M-1d.log"
    LOGFILE["M-1d"]="$logf"
    printf "${C_BOLD}[M-1d]${C_NC} internal-miner-e2e: spawn regtest, mine via 3 RPCs, verify B3PoW-Scratch v1.1 per block\n"

    if BINDIR="$(dirname "$b3chaind")" python3 "$SCRIPT_DIR/audit-b3pow-miner-e2e.py" >"$logf" 2>&1; then
        mark "M-1d" PASS "$(grep -E '^SUMMARY' "$logf" | tail -1 | sed 's/^SUMMARY: //')"
    else
        local rc=$?
        mark "M-1d" FAIL "exit $rc — log: $logf"
        sed -n '1,20p' "$logf" | sed 's/^/    /'
    fi
}

# ---------------------------------------------------------------------------
# Run selected checks
# ---------------------------------------------------------------------------
case "$MODE" in
    static)  do_static_checks ;;
    e2e)     do_e2e_check ;;
    all)     do_static_checks; do_e2e_check ;;
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
printf "${C_BOLD}  Phase 6.1 internal-miner verification summary${C_NC}\n"
printf "${C_BOLD}=========================================================================${C_NC}\n"
printf "  ${C_GREEN}PASS${C_NC}: %3d   ${C_RED}FAIL${C_NC}: %3d   ${C_YELLOW}SKIP${C_NC}: %3d\n" "$pass" "$fail" "$skip"
echo

# ---------------------------------------------------------------------------
# Rewrite checklist (skipped for --e2e-only and --dry-run)
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = 0 ] && [ "$MODE" != "e2e" ] && [ -f "$CHECKLIST" ]; then
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
    m = re.match(r'^(\|\s*)(M-1[a-z])(\s*\|.*?\|\s*)`?\[[x!\?\- ]\]`?(\s*\|)\s*$', line)
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

# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------
if [ "$fail" -gt 0 ]; then
    printf "\n${C_RED}OVERALL: FAIL${C_NC}  ($fail check(s) failed; logs in $TMPDIR_LOG)\n"
    cp -r "$TMPDIR_LOG" "$REPO_ROOT/.audit-internal-miner-last-run" 2>/dev/null || true
    trap - EXIT
    exit 1
fi
printf "${C_GREEN}OVERALL: PASS${C_NC}  ($pass passed, $skip skipped)\n"
exit 0
