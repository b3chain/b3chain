#!/bin/bash
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# [B-2] Rebranding regression audit.
#
# Greps the codebase for forbidden Bitcoin-branded patterns in user-visible
# files (excluding upstream attribution, copyright, protocol constants, and
# the test suite which intentionally references upstream behaviour).
#
# Optionally reruns the unit + functional + regtest-simulation suites to
# confirm zero regressions from the rebranding pass.
#
# Usage:
#     bash contrib/testing/audit/audit-rebranding.sh           # grep only
#     RERUN_TESTS=1 bash contrib/testing/audit/audit-rebranding.sh

set -uo pipefail

# Locate repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

# shellcheck source=lib/audit_common.sh
source "$SCRIPT_DIR/lib/audit_common.sh"

audit_header "B-2" "Rebranding regression audit"

# Pick the right grep tool
if command -v rg >/dev/null 2>&1; then
    GREP_CMD="rg --color=never --no-heading -n"
else
    GREP_CMD="grep -rn --color=never"
fi

# -----------------------------------------------------------------------------
# Forbidden-pattern table.
#
# Each entry: <label>|<regex>|<exclude_globs (comma-separated)>
# An exclude entry of "test" excludes test directories; "doc/release-notes"
# excludes historical release notes.
# -----------------------------------------------------------------------------

EXCLUDES_DEFAULT=(
    --glob '!**/test/**'
    --glob '!**/tests/**'
    --glob '!**/release-notes/**'
    --glob '!**/release-notes-*.md'
    --glob '!**/secp256k1/**'      # upstream submodule
    --glob '!**/leveldb/**'         # upstream submodule
    --glob '!**/minisketch/**'
    --glob '!**/crc32c/**'
    --glob '!**/crypto/blake3/**'
    --glob '!**/COPYING*'
    --glob '!**/CHANGELOG*.md'
    --glob '!**/SECURITY-AUDIT.md'  # this audit may name patterns
    --glob '!**/contrib/testing/audit/**'  # the audit scripts themselves
    --glob '!**/*.po'
    --glob '!**/*.pot'
    --glob '!**/*.ts'
    --glob '!**/extract_strings_qt.py'
    --glob '!**/clientversion.cpp'  # contains attribution-detection literals
)

# Use ripgrep when available (much faster), else fall back to grep -r
run_search() {
    local pattern="$1"; shift
    if command -v rg >/dev/null 2>&1; then
        rg --color=never --no-heading -n "${EXCLUDES_DEFAULT[@]}" "$pattern" 2>/dev/null
    else
        # plain grep fallback (slower; mirrors the rg excludes)
        grep -rnE --color=never \
             --exclude-dir=test --exclude-dir=tests \
             --exclude-dir=release-notes \
             --exclude-dir=secp256k1 --exclude-dir=leveldb \
             --exclude-dir=minisketch --exclude-dir=crc32c \
             --exclude-dir=blake3 \
             --exclude-dir=audit \
             --exclude="release-notes-*.md" \
             --exclude="*.po" --exclude="*.pot" \
             --exclude="*.ts" --exclude="*.xlf" \
             --exclude="CHANGELOG*.md" --exclude="SECURITY-AUDIT.md" \
             --exclude="audit-*.sh" --exclude="audit-*.py" \
             --exclude="extract_strings_qt.py" \
             --exclude="clientversion.cpp" \
             "$pattern" "$REPO_ROOT" 2>/dev/null
    fi
}

# -----------------------------------------------------------------------------
# Patterns to flag.
# Each pattern is paired with allowed contexts. Hits outside those allowed
# contexts mean a leftover Bitcoin reference in user-visible code.
# -----------------------------------------------------------------------------

check_pattern() {
    local label="$1"
    local pattern="$2"

    local hits
    hits="$(run_search "$pattern" || true)"
    # Filter out comment-only lines marked as upstream attribution.
    if [ -n "$hits" ]; then
        # Heuristic: ignore lines that look like "Copyright" or "Bitcoin Core developers"
        hits="$(echo "$hits" | grep -v -E "Copyright|developers|Original (file|code)|Adapted from|forked from|Based on|upstream|@bitcoincore" || true)"
    fi
    if [ -n "$hits" ]; then
        local count
        count="$(echo "$hits" | wc -l | tr -d ' ')"
        fail "$label  ($count hits)"
        echo "$hits" | head -5 | sed 's/^/         /'
        if [ "$count" -gt 5 ]; then
            echo "         ... and $((count - 5)) more"
        fi
    else
        pass "$label"
    fi
}

# 1) "Bitcoin Signed Message" — should be "B3Chain Signed Message" everywhere.
check_pattern "no leftover 'Bitcoin Signed Message' string" \
              '"Bitcoin Signed Message'

# 2) "bitcoin:" URI scheme outside protocol constants
check_pattern "no leftover 'bitcoin:' URI scheme literals" \
              '"bitcoin:'

# 3) bitcoind / bitcoin-cli in non-historical .md files
echo
md_hits="$(run_search '\bbitcoind\b|\bbitcoin-cli\b|\bbitcoin-qt\b|\bbitcoin-tx\b|\bbitcoin-util\b|\bbitcoin-wallet\b' || true)"
# Filter to .md files and remove lines that legitimately mention the old names:
#   * Copyright / attribution lines
#   * External URLs (e.g. flathub paths)
#   * Source-file references like "src/bitcoin-util.cpp" (the file itself is
#     intentionally not renamed)
#   * Tables/lines that contrast the old and new names (contain both)
md_hits="$(echo "$md_hits" \
    | grep '\.md:' \
    | grep -v -E "Copyright|upstream|forked from|Original" \
    | grep -v -E "://" \
    | grep -v -E "src/bitcoin-[a-z]+\.cpp" \
    | grep -v -E "bitcoind?.*b3chain" \
    || true)"
if [ -n "$md_hits" ]; then
    count="$(echo "$md_hits" | wc -l | tr -d ' ')"
    fail "no leftover bitcoind / bitcoin-cli in .md docs  ($count hits)"
    echo "$md_hits" | head -5 | sed 's/^/         /'
else
    pass "no leftover bitcoind / bitcoin-cli in .md docs"
fi

# 4) RPC help strings — these are user-visible
check_pattern "no 'Bitcoin' in RPC help strings (HelpExampleCli/HelpExampleRpc)" \
              'HelpExample(Cli|Rpc)\([^)]*"bitcoin'

# 5) Qt translatable strings still saying "Bitcoin"
check_pattern "no 'Bitcoin' in Qt tr() strings (user-visible)" \
              'tr\("[^"]*Bitcoin'

# 6) "Bitcoin Core" in non-attribution context (project name in --help, banners)
echo
bc_hits="$(run_search '"Bitcoin Core"' || true)"
bc_hits="$(echo "$bc_hits" | grep -v -E "Copyright|Bitcoin Core developers|forked|Original|upstream|secp256k1" || true)"
if [ -n "$bc_hits" ]; then
    count="$(echo "$bc_hits" | wc -l | tr -d ' ')"
    fail "no \"Bitcoin Core\" string outside attribution  ($count hits)"
    echo "$bc_hits" | head -5 | sed 's/^/         /'
else
    pass "no \"Bitcoin Core\" string outside attribution context"
fi

# -----------------------------------------------------------------------------
# Optional: rerun the test suites to verify zero regressions
# -----------------------------------------------------------------------------

if [ "${RERUN_TESTS:-0}" = "1" ]; then
    echo
    echo "  Rerunning test suites (RERUN_TESTS=1)..."

    if [ -d "$REPO_ROOT/build" ]; then
        if (cd "$REPO_ROOT/build" && ctest --output-on-failure -j2 2>&1 | tail -3); then
            pass "ctest suite passed"
        else
            fail "ctest suite reported failures"
        fi
    else
        skip "ctest skipped: $REPO_ROOT/build does not exist"
    fi

    if [ -x "$REPO_ROOT/build/bin/b3chaind" ] || [ -x "$REPO_ROOT/build/src/b3chaind" ]; then
        if bash "$REPO_ROOT/contrib/testing/regtest-simulation.sh" >/tmp/b3chain_regtest.log 2>&1; then
            pass "contrib/testing/regtest-simulation.sh passed"
        else
            fail "contrib/testing/regtest-simulation.sh failed (see /tmp/b3chain_regtest.log)"
        fi
    else
        skip "regtest simulation skipped: b3chaind not built"
    fi
else
    skip "test reruns skipped (set RERUN_TESTS=1 to enable)"
fi

audit_finish
