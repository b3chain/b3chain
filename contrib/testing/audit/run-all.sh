#!/usr/bin/env bash
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# Run every B3Chain Phase 11 audit in sequence and print a summary table.

export LC_ALL=C
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

source "$SCRIPT_DIR/lib/audit_common.sh"
audit_find_bindir || exit 1

echo
printf "${AUDIT_BOLD}B3Chain Phase 11 Security Audit — running every check${AUDIT_NC}\n"
printf "Binaries: %s\n" "$BINDIR"
echo

# (script_path, audit_id)
declare -a AUDITS=(
    "audit-supply-cap.py:C-1..C-4"
    "audit-b3pow-isolation.py:H-1"
    "audit-b3pow-budget.py:H-1.1"
    "audit-b3pow-cache.py:H-1.2"
    "audit-b3pow-headers-cap.py:H-1.3"
    "audit-network-isolation.py:N-1"
    "audit-address-rejection.py:W-1"
    "audit-simd-blake3.py:B-1"
    "audit-rebranding.sh:B-2"
    "audit-hd-coin-type.py:W-2"
    "audit-51-attack-sim.py:A-1"
    "audit-51attack-watch.py:A-2"
)

declare -a RESULTS=()
overall=0

for entry in "${AUDITS[@]}"; do
    script="${entry%%:*}"
    audit_id="${entry##*:}"
    echo
    printf "${AUDIT_BOLD}########  %s  (%s)  ########${AUDIT_NC}\n" "$script" "$audit_id"
    if [[ "$script" == *.sh ]]; then
        bash "$SCRIPT_DIR/$script"
        rc=$?
    else
        python3 "$SCRIPT_DIR/$script"
        rc=$?
    fi
    if [ $rc -eq 0 ]; then
        RESULTS+=("$audit_id|$script|PASS")
    else
        RESULTS+=("$audit_id|$script|FAIL")
        overall=1
    fi
done

echo
printf "${AUDIT_BOLD}========================================================================${AUDIT_NC}\n"
printf "${AUDIT_BOLD}  AUDIT SUMMARY${AUDIT_NC}\n"
printf "${AUDIT_BOLD}========================================================================${AUDIT_NC}\n"
printf "%-15s  %-32s  %s\n" "ID" "SCRIPT" "RESULT"
printf "%-15s  %-32s  %s\n" "---------------" "--------------------------------" "------"
for r in "${RESULTS[@]}"; do
    IFS='|' read -r id script result <<<"$r"
    if [ "$result" = "PASS" ]; then
        printf "%-15s  %-32s  ${AUDIT_GREEN}%s${AUDIT_NC}\n" "$id" "$script" "$result"
    else
        printf "%-15s  %-32s  ${AUDIT_RED}%s${AUDIT_NC}\n" "$id" "$script" "$result"
    fi
done

echo
if [ $overall -eq 0 ]; then
    printf "${AUDIT_BOLD}${AUDIT_GREEN}OVERALL: PASS${AUDIT_NC}\n"
else
    printf "${AUDIT_BOLD}${AUDIT_RED}OVERALL: FAIL${AUDIT_NC}\n"
fi
exit $overall
