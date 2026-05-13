#!/usr/bin/env bash
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# Run every empirical comparison in the BLAKE3-vs-SHA-256 suite.
# Saves JSON to results/, prints a one-line headline per comparison.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

BOLD=$'\033[1m'; GREEN=$'\033[32m'; RED=$'\033[31m'; NC=$'\033[0m'

echo
printf "%sB3Chain comparative suite (BLAKE3 vs SHA-256)%s\n" "$BOLD" "$NC"
printf "results: %s/results/\n" "$SCRIPT_DIR"
echo

overall=0

run() {
    local name="$1"; shift
    printf "%s>>> %s%s\n" "$BOLD" "$name" "$NC"
    if "$@"; then
        printf "  %sok%s\n\n" "$GREEN" "$NC"
    else
        printf "  %sfailed (rc=$?)%s\n\n" "$RED" "$NC"
        overall=1
    fi
}

run "throughput"        python3 compare-pow-throughput.py    "$@"
run "block-validation"  python3 compare-block-validation.py
run "length-extension"  python3 compare-length-extension.py

echo
if [ $overall -eq 0 ]; then
    printf "%s%sAll comparisons completed.%s\n" "$BOLD" "$GREEN" "$NC"
else
    printf "%s%sOne or more comparisons failed.%s\n" "$BOLD" "$RED" "$NC"
fi
exit $overall
