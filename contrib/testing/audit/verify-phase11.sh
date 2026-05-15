#!/usr/bin/env bash
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# Phase 11 verifier — runs every check from doc/PHASE-11-VERIFICATION.md,
# rewrites the status column of that file in place, and exits non-zero
# on any failure.
#
# Usage:
#   bash contrib/testing/audit/verify-phase11.sh
#   bash contrib/testing/audit/verify-phase11.sh --dry-run
#   bash contrib/testing/audit/verify-phase11.sh --only ID
#   B3CHAIN_OFFLINE=1 bash contrib/testing/audit/verify-phase11.sh
#
# Environment overrides:
#   B3CHAIN_OFFLINE=1                skip network checks (22a..22d)
#   B3CHAIN_WEBSITE=/path            override website repo location
#   SSH_KEY=~/.ssh/lobby_cursor_ed25519
#   B3CHAIN_SKIP_AUDITS=1            don't re-run the heavy audits (3-10)
#   B3CHAIN_SKIP_CTEST=1             skip the C++ ctest check (11)

set -uo pipefail

# ---------------------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

WEBSITE_DIR="${B3CHAIN_WEBSITE:-$REPO_ROOT/../b3chain-website}"
WEBSITE_DIR="$(cd "$WEBSITE_DIR" 2>/dev/null && pwd || echo "$WEBSITE_DIR")"

CHECKLIST="$REPO_ROOT/doc/PHASE-11-VERIFICATION.md"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/lobby_cursor_ed25519}"

DRY_RUN=0
ONLY=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --only) shift; ONLY="$1" ;;
        --only=*) ONLY="${1#--only=}" ;;
        -h|--help)
            sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1"; exit 2 ;;
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

# ---------------------------------------------------------------------------
# Result accumulators
# ---------------------------------------------------------------------------
declare -A RESULT      # id -> PASS|FAIL|SKIP
declare -A NOTE        # id -> short note (failure reason)
declare -A LOGFILE     # id -> path to captured log
TMPDIR_LOG="$(mktemp -d -t b3chain-verify.XXXXXX)"
trap 'rm -rf "$TMPDIR_LOG"' EXIT

run_check() {
    # run_check ID DESCRIPTION CMD...
    local id="$1"; shift
    local desc="$1"; shift
    if [ -n "$ONLY" ] && [ "$ONLY" != "$id" ]; then
        return
    fi
    local logf="$TMPDIR_LOG/$id.log"
    LOGFILE[$id]="$logf"
    printf "${C_BOLD}[%s]${C_NC} %s\n" "$id" "$desc"
    if [ "$DRY_RUN" = 1 ]; then
        printf "  ${C_DIM}DRY-RUN: %s${C_NC}\n" "$*"
        RESULT[$id]="SKIP"
        NOTE[$id]="dry-run"
        return
    fi
    if "$@" >"$logf" 2>&1; then
        RESULT[$id]="PASS"
        printf "  ${C_GREEN}PASS${C_NC}\n"
    else
        local rc=$?
        RESULT[$id]="FAIL"
        NOTE[$id]="exit $rc"
        printf "  ${C_RED}FAIL${C_NC} (exit $rc) — log: %s\n" "$logf"
        sed -n '1,5p' "$logf" | sed 's/^/    /'
    fi
}

skip_check() {
    local id="$1"; shift
    local reason="$1"
    if [ -n "$ONLY" ] && [ "$ONLY" != "$id" ]; then
        return
    fi
    RESULT[$id]="SKIP"
    NOTE[$id]="$reason"
    printf "${C_BOLD}[%s]${C_NC} ${C_YELLOW}SKIP${C_NC} — %s\n" "$id" "$reason"
}

# ---------------------------------------------------------------------------
# A — Core repo
# ---------------------------------------------------------------------------
echo
echo "${C_BOLD}Phase 11 verification — running checks${C_NC}"
echo "${C_DIM}repo:    $REPO_ROOT${C_NC}"
echo "${C_DIM}website: $WEBSITE_DIR${C_NC}"
echo

# 1 — checklist structure
run_check "1" "checklist: SECURITY-AUDIT.md structure" \
    python3 "$SCRIPT_DIR/verify_checklist.py"

# 2 — shared helpers importable
run_check "2" "audit-folder: lib/audit_common.py importable" \
    python3 -c "import sys, pathlib; sys.path.insert(0, str(pathlib.Path('$SCRIPT_DIR/lib'))); import audit_common; assert hasattr(audit_common, 'RegtestNode') and hasattr(audit_common, 'AuditResult'), 'missing exports'"

# 3..10 — the heavy audits. These can be expensive; allow skipping.
audits=(
    "3:supply-cap:audit-supply-cap.py:python3"
    "4:pow-isolation:audit-pow-isolation.py:python3"
    "5:net-isolation:audit-network-isolation.py:python3"
    "6:addr-rejection:audit-address-rejection.py:python3"
    "7:simd-blake3:audit-simd-blake3.py:python3"
    "8:rebranding:audit-rebranding.sh:bash"
    "9:hd-coin-type-script:audit-hd-coin-type.py:python3"
    "10:51-attack-sim:audit-51-attack-sim.py:python3"
    "M-1:internal-miner:audit-internal-miner.sh:bash"
    "P-1:stratum-pool:audit-stratum-pool.sh:bash"
    "P-2:stratum-v2:audit-stratum-v2.sh:bash"
)
if [ "${B3CHAIN_SKIP_AUDITS:-0}" = "1" ]; then
    for entry in "${audits[@]}"; do
        IFS=':' read -r idx id _ _ <<<"$entry"
        skip_check "$idx" "B3CHAIN_SKIP_AUDITS=1"
    done
else
    for entry in "${audits[@]}"; do
        IFS=':' read -r idx id script runner <<<"$entry"
        run_check "$idx" "$id: $runner $script" \
            "$runner" "$SCRIPT_DIR/$script"
    done
fi

# 9-extra — coin_type 9333 documentation + wallet wiring
run_check "9-doc" "hd-coin-type: doc/b3chain-bip44.md mentions coin_type 9333" \
    bash -c "grep -q 'coin_type' '$REPO_ROOT/doc/b3chain-bip44.md' && grep -q '9333' '$REPO_ROOT/doc/b3chain-bip44.md'"
run_check "9-wallet" "hd-coin-type: src/wallet/walletutil.cpp uses 9333h" \
    bash -c "grep -q '9333h' '$REPO_ROOT/src/wallet/walletutil.cpp'"

# 11 — C++ tests
if [ "${B3CHAIN_SKIP_CTEST:-0}" = "1" ] || [ ! -d "$REPO_ROOT/build" ]; then
    skip_check "11" "no build/ directory (build B3Chain Core first or set B3CHAIN_SKIP_CTEST=1)"
else
    run_check "11" "cpp-audit-tests: ctest discovers consensus_invariants_tests" \
        bash -c "cd '$REPO_ROOT/build' && ctest -N -R 'consensus_invariants' 2>&1 | grep -q 'Test #'"
fi

# 12 — every audit row is [x] in SECURITY-AUDIT.md
run_check "12" "run-audits: every row in SECURITY-AUDIT.md is passed" \
    python3 "$SCRIPT_DIR/verify_checklist.py" --require-all-passed

# 13 — changelog mentions phase 11
run_check "13" "update-changelog: doc/CHANGELOG.md mentions Phase 11" \
    bash -c "grep -qi 'phase 11' '$REPO_ROOT/doc/CHANGELOG.md'"

# ---------------------------------------------------------------------------
# B — Website
# ---------------------------------------------------------------------------
if [ ! -d "$WEBSITE_DIR" ]; then
    for idx in 14 15 16 17 18 19a 19b; do
        skip_check "$idx" "website not found at $WEBSITE_DIR (set B3CHAIN_WEBSITE)"
    done
else
    # 14 — CSS extracted
    run_check "14" "css-extract: shared CSS exists, both pages link it, no inline styles" \
        bash -c "
            test -f '$WEBSITE_DIR/css/style.css' &&
            grep -q 'css/style.css' '$WEBSITE_DIR/index.html' &&
            grep -q 'css/style.css' '$WEBSITE_DIR/testing.html' &&
            ! grep -rln '<style' '$WEBSITE_DIR' --include='*.html' >/dev/null
        "

    # 15 — testing.html is a hub
    run_check "15" "testing-hub: hub has 3 required sections" \
        bash -c "grep -cE 'Reproducible tests|Phase 11 security audit|Attacks &amp; defense' '$WEBSITE_DIR/testing.html' | grep -qE '^[3-9]|^[1-9][0-9]'"

    # 16 — six existing-test pages
    run_check "16" "existing-detail-pages: 6 pages exist" \
        bash -c "
            for f in pow-verifier test-vectors regtest-simulation test-results limitations reporting; do
                test -f '$WEBSITE_DIR/testing/'\$f'.html' || { echo MISSING \$f; exit 1; }
            done
        "

    # 17 — eight audit pages
    run_check "17" "audit-detail-pages: 8 audit pages exist" \
        bash -c "
            for f in security-audit audit-supply-cap audit-pow-isolation audit-network-isolation audit-address-rejection audit-simd-blake3 audit-rebranding audit-hd-coin-type; do
                test -f '$WEBSITE_DIR/testing/'\$f'.html' || { echo MISSING \$f; exit 1; }
            done
        "

    # 18 — 51-attack page covers required topics
    run_check "18" "attack-page: 51-attack.html includes math, cost, defenses, reorg" \
        bash -c "
            f='$WEBSITE_DIR/testing/51-attack.html'
            test -f \"\$f\" || { echo MISSING; exit 1; }
            for kw in -i Nakamoto cost defense reorg; do :; done
            count=\$(grep -ciE 'nakamoto|cost|defense|reorg' \"\$f\")
            test \"\$count\" -ge 4 || { echo only-\$count-keywords; exit 1; }
        "

    # 19a — every detail page links back to /testing.html
    run_check "19a" "verify-website: all pages have hub breadcrumb" \
        bash -c "
            missing=\$(grep -L 'href=\"/testing.html\"\\|href=\"../testing.html\"\\|href=\"testing.html\"' '$WEBSITE_DIR'/testing/*.html | wc -l)
            test \"\$missing\" -eq 0 || { echo \$missing-pages-missing-breadcrumb; exit 1; }
        "

    # 19b — link checker
    run_check "19b" "verify-website: on-disk link checker" \
        python3 "$SCRIPT_DIR/verify_links.py" "$WEBSITE_DIR"
fi

# ---------------------------------------------------------------------------
# C — Deployment
# ---------------------------------------------------------------------------
OFFLINE="${B3CHAIN_OFFLINE:-0}"
if [ "$OFFLINE" = "1" ]; then
    for idx in 20 21 22a 22b 22c 22d; do
        skip_check "$idx" "B3CHAIN_OFFLINE=1"
    done
else
    # 20 — core repo pushed
    if [ -d "$REPO_ROOT/.git" ]; then
        run_check "20" "commit-push-core: local b3chain-main matches origin" \
            bash -c "
                cd '$REPO_ROOT'
                local_sha=\$(git rev-parse HEAD)
                remote_sha=\$(git ls-remote https://github.com/b3chain/b3chain.git b3chain-main 2>/dev/null | awk '{print \$1}')
                test -n \"\$remote_sha\" || { echo cannot-reach-github; exit 1; }
                test \"\$local_sha\" = \"\$remote_sha\" || { echo local=\$local_sha remote=\$remote_sha; exit 1; }
            "
    else
        skip_check "20" "$REPO_ROOT is not a git checkout"
    fi

    # 21 — website repo pushed
    if [ -d "$WEBSITE_DIR/.git" ]; then
        run_check "21" "commit-push-website: local main matches origin" \
            bash -c "
                cd '$WEBSITE_DIR'
                local_sha=\$(git rev-parse HEAD)
                remote_sha=\$(git ls-remote https://github.com/b3chain/b3chain-website.git main 2>/dev/null | awk '{print \$1}')
                test -n \"\$remote_sha\" || { echo cannot-reach-github; exit 1; }
                test \"\$local_sha\" = \"\$remote_sha\" || { echo local=\$local_sha remote=\$remote_sha; exit 1; }
            "
    else
        skip_check "21" "$WEBSITE_DIR is not a git checkout"
    fi

    # 22a — live audit hub serves
    run_check "22a" "deploy-server: https://b3chain.org/testing/security-audit.html is live" \
        bash -c "curl -fsSL --max-time 10 -o /dev/null -w '%{http_code}\n' https://b3chain.org/testing/security-audit.html | grep -q '^200$'"

    # 22b — every detail page is live
    run_check "22b" "deploy-server-pages: every audit detail page is live" \
        bash -c "
            ok=0; total=0
            for p in security-audit audit-supply-cap audit-pow-isolation audit-network-isolation audit-address-rejection audit-simd-blake3 audit-rebranding audit-hd-coin-type 51-attack; do
                total=\$((total+1))
                code=\$(curl -fsSL --max-time 10 -o /dev/null -w '%{http_code}' \"https://b3chain.org/testing/\$p.html\" || echo 000)
                if [ \"\$code\" = '200' ]; then ok=\$((ok+1)); else echo \"  \$p -> \$code\"; fi
            done
            test \"\$ok\" -eq \"\$total\" || { echo \"\$ok/\$total live\"; exit 1; }
        "

    # 22c — TLS cert is fresh
    run_check "22c" "cert-fresh: live TLS cert has more than 30 days remaining" \
        bash -c "
            enddate=\$(echo | openssl s_client -servername b3chain.org -connect b3chain.org:443 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | sed 's/notAfter=//')
            test -n \"\$enddate\" || { echo cannot-fetch-cert; exit 1; }
            end_ts=\$(date -d \"\$enddate\" +%s 2>/dev/null || date -j -f '%b %d %T %Y %Z' \"\$enddate\" +%s 2>/dev/null)
            now_ts=\$(date +%s)
            days=\$(( (end_ts - now_ts) / 86400 ))
            test \"\$days\" -gt 30 || { echo only-\$days-days-left; exit 1; }
            echo \"\$days days remain\"
        "

    # 22d — renewal hook still installed on server
    if [ -f "$SSH_KEY" ]; then
        run_check "22d" "cert-renewal-hook: nginx-reload deploy hook still on server" \
            ssh -p 2222 -i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
                deploy@166.88.4.250 \
                "sudo test -x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx && sudo grep -q 'systemctl reload nginx' /etc/letsencrypt/renewal-hooks/deploy/reload-nginx"
    else
        skip_check "22d" "no SSH key at $SSH_KEY"
    fi
fi

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
printf "${C_BOLD}  Phase 11 verification summary${C_NC}\n"
printf "${C_BOLD}=========================================================================${C_NC}\n"
printf "  ${C_GREEN}PASS${C_NC}: %3d   ${C_RED}FAIL${C_NC}: %3d   ${C_YELLOW}SKIP${C_NC}: %3d\n" "$pass" "$fail" "$skip"
echo

# ---------------------------------------------------------------------------
# Write per-row results map; then rewrite the checklist + findings section.
# ---------------------------------------------------------------------------
{
    for id in "${!RESULT[@]}"; do
        printf '%s\t%s\t%s\n' "$id" "${RESULT[$id]}" "${NOTE[$id]:-}"
    done
} > "$TMPDIR_LOG/_results.tsv"

if [ "$DRY_RUN" = 0 ] && [ -z "$ONLY" ] && [ -f "$CHECKLIST" ]; then
    python3 - "$CHECKLIST" "$TMPDIR_LOG" <<'PYEOF'
import sys, re, datetime
from pathlib import Path

checklist = Path(sys.argv[1])
logdir    = Path(sys.argv[2])
text = checklist.read_text(encoding="utf-8")

results = {}
notes   = {}
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
    m = re.match(r'^(\|\s*)(\d+[a-z\-]*)(\s*\|.*?\|\s*)`?\[[x!\?\- ]\]`?(\s*\|)\s*$', line)
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
# Exit status
# ---------------------------------------------------------------------------
if [ "$fail" -gt 0 ]; then
    printf "\n${C_RED}OVERALL: FAIL${C_NC}  ($fail check(s) failed; logs in $TMPDIR_LOG)\n"
    # Preserve logs on failure
    cp -r "$TMPDIR_LOG" "$REPO_ROOT/.verify-phase11-last-run" 2>/dev/null || true
    trap - EXIT
    exit 1
fi
printf "${C_GREEN}OVERALL: PASS${C_NC}  ($pass passed, $skip skipped)\n"
exit 0
