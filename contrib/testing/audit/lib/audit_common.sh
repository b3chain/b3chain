#!/bin/bash
# Shared bash helpers for B3Chain Phase 11 audit shell scripts.
# Source from another script:
#     source "$(dirname "$0")/lib/audit_common.sh"

if [ -t 1 ] && [ -z "$NO_COLOR" ]; then
    AUDIT_RED='\033[0;31m'; AUDIT_GREEN='\033[0;32m'
    AUDIT_YELLOW='\033[0;33m'; AUDIT_BOLD='\033[1m'; AUDIT_DIM='\033[2m'
    AUDIT_NC='\033[0m'
else
    AUDIT_RED=''; AUDIT_GREEN=''; AUDIT_YELLOW=''
    AUDIT_BOLD=''; AUDIT_DIM=''; AUDIT_NC=''
fi

audit_pass_count=0
audit_fail_count=0
audit_id="${AUDIT_ID:-?}"
audit_title="${AUDIT_TITLE:-Audit}"

audit_header() {
    audit_id="$1"
    audit_title="$2"
    printf "${AUDIT_BOLD}[%s] %s${AUDIT_NC}\n" "$audit_id" "$audit_title"
    printf "${AUDIT_DIM}========================================================================${AUDIT_NC}\n"
}

pass() {
    printf "  ${AUDIT_GREEN}PASS${AUDIT_NC}  %s\n" "$1"
    audit_pass_count=$((audit_pass_count + 1))
}

fail() {
    printf "  ${AUDIT_RED}FAIL${AUDIT_NC}  %s\n" "$1"
    audit_fail_count=$((audit_fail_count + 1))
}

skip() {
    printf "  ${AUDIT_YELLOW}SKIP${AUDIT_NC}  %s\n" "$1"
}

audit_finish() {
    local total=$((audit_pass_count + audit_fail_count))
    printf '%s\n' "${AUDIT_DIM}------------------------------------------------------------------------${AUDIT_NC}"
    printf '  %d/%d checks passed\n' "$audit_pass_count" "$total"
    if [ $audit_fail_count -eq 0 ] && [ $audit_pass_count -gt 0 ]; then
        printf '%s\n' "${AUDIT_BOLD}AUDIT RESULT: ${AUDIT_GREEN}PASS${AUDIT_NC}  [${audit_id}]${AUDIT_NC}"
        return 0
    else
        printf '%s\n' "${AUDIT_BOLD}AUDIT RESULT: ${AUDIT_RED}FAIL${AUDIT_NC}  [${audit_id}]${AUDIT_NC}"
        return 1
    fi
}

# Locate b3chain build directory (sets BINDIR if not already set)
audit_find_bindir() {
    if [ -n "$BINDIR" ] && [ -x "$BINDIR/b3chaind" ]; then
        return 0
    fi
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
    if [ -x "$script_dir/build/bin/b3chaind" ]; then
        BINDIR="$script_dir/build/bin"
    elif [ -x "$script_dir/build/src/b3chaind" ]; then
        BINDIR="$script_dir/build/src"
    else
        echo "ERROR: cannot find b3chaind. Build the project or set BINDIR." >&2
        return 1
    fi
    export BINDIR
}
