#!/usr/bin/env bash
#
# Trademark audit for the B3Chain Live Explorer fork.
#
# Refuses to pass when upstream "Mempool" branding leaks into the tree
# (or into a built /var/www/b3chain-explorer-ng deploy directory).
#
# Run modes:
#   tm-audit.sh                  # audit cwd (the b3chain/explorer-ng repo)
#   tm-audit.sh <dir>            # audit specific directory
#   tm-audit.sh --staged         # audit staged files only (pre-commit hook mode)
#
# Carve-outs (whitelisted): exactly two strings.
#   1. AGPL attribution: "AGPLv3 source at https://github.com/mempool/mempool"
#      may appear in /v2/about and the repo README/LICENSE.
#   2. The bitcoind RPC method names which form part of bitcoin-core's
#      public API (these are protocol names, not branding):
#         getrawmempool, testmempoolaccept, getmempoolentry,
#         getmempoolinfo, getmempoolancestors, getmempooldescendants,
#         savemempool, importmempool
#
# Everything else containing the substring "mempool" (any case) is treated
# as a trademark leak and fails the audit.
set -euo pipefail
export LC_ALL=C

MODE="dir"
TARGET="."
case "${1:-}" in
    --staged)
        MODE="staged"
        ;;
    "")
        ;;
    *)
        TARGET="$1"
        ;;
esac

fail=0
report() { echo "TM AUDIT FAIL: $*" >&2; fail=1; }

# Detect whether the current repo root is an explorer-ng tree (Angular SPA
# + Node backend + production nginx configs). This flag changes which paths
# are considered "interesting" by --staged mode.
is_explorer_ng_tree() {
    local root
    root=$(git rev-parse --show-toplevel 2>/dev/null) || return 1
    [ -f "$root/frontend/package.json" ] && [ -f "$root/backend/package.json" ]
}

# --- file-path exclusions --------------------------------------------------
# These paths legitimately mention the upstream trademark because they are
# planning / specification / tooling docs in the b3chain mono-repo, OR they
# *are* this audit script itself. They are never present in a deployed
# explorer-ng tree; this exclusion only matters when the audit is run inside
# the b3chain-main repo (pre-commit / CI guard).
path_exclude_re='(^|/)(\.cursor/plans/[^/]+\.plan\.md|doc/MEMPOOL-SPACE-REPLICATION-SPEC\.md|contrib/testnet/explorer-ng/(README\.md|install\.sh|verify\.sh|bootstrap-fork\.sh|mariadb-schema\.sh|tools/[^/]+\.sh|patches/[^/]+\.sh|nginx/[^/]+\.conf|systemd/[^/]+\.service|config/[^/]+)|LICENSE|COPYING|\.b3chain/.*)$'

# --- file list -------------------------------------------------------------
if [ "$MODE" = "staged" ]; then
    mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACMR \
                          | grep -v -E '\.(png|jpg|jpeg|gif|webp|woff2?|ttf|eot|ico|map)$' \
                          | grep -vE "$path_exclude_re" || true)

    # When invoked inside the b3chain mono-repo (which is bitcoin core and
    # legitimately contains the term "mempool" in protocol code/docs), only
    # audit staged files that live under contrib/testnet/explorer-ng/ -- the
    # explorer-ng GitHub repo gets the full audit on its own pre-commit.
    if ! is_explorer_ng_tree; then
        TMP=()
        for f in "${FILES[@]+"${FILES[@]}"}"; do
            case "$f" in
                contrib/testnet/explorer-ng/*) TMP+=("$f") ;;
            esac
        done
        FILES=("${TMP[@]+"${TMP[@]}"}")
    fi

    if [ "${#FILES[@]}" -eq 0 ]; then
        echo "tm-audit: no staged explorer-ng text files (after exclusions); pass"
        exit 0
    fi
else
    cd "$TARGET"
    if ! is_explorer_ng_tree; then
        echo "tm-audit: '$TARGET' does not look like an explorer-ng tree" >&2
        echo "         (need frontend/package.json + backend/package.json)" >&2
        echo "         skipping audit"
        exit 0
    fi
    mapfile -t FILES < <(
        ( git ls-files 2>/dev/null \
        || find . -type f \
                  -not -path './node_modules/*' \
                  -not -path './.git/*' \
                  -not -path './dist/*' \
                  -not -path './cache/*' \
                  -not -name '*.png' \
                  -not -name '*.jpg' \
                  -not -name '*.jpeg' \
                  -not -name '*.gif' \
                  -not -name '*.webp' \
                  -not -name '*.woff' \
                  -not -name '*.woff2' \
                  -not -name '*.ttf' \
                  -not -name '*.eot' \
                  -not -name '*.ico' \
                  -not -name '*.map' ) \
        | sed 's|^\./||' \
        | grep -vE "$path_exclude_re" || true
    )
fi

# --- strict block patterns -------------------------------------------------
strict_patterns=(
    '\bMempool\b'                              # capitalized brand
    '\bMempool Goggles\b'                      # TM feature
    '\bMempool Accelerator\b'                  # TM feature
    'The Mempool Open Source Project'          # entity
    'mempool\.space'                           # canonical domain
    'donate\.[a-z.-]*mempool'                  # donate marketing
    'twitter\.com/BitcoinExplorer'             # upstream twitter
    'mempool-logo'                             # upstream asset filename
    'mempool-icon'                             # upstream asset filename
    'mempool-explorer\.svg'                    # upstream asset filename
)

# --- whitelist line filter -------------------------------------------------
# A line is allowed if it matches BOTH "mempool" AND one of the carve-outs.
allowlist_re='AGPLv3 source at https://github\.com/mempool/mempool|getrawmempool|testmempoolaccept|getmempoolentry|getmempoolinfo|getmempoolancestors|getmempooldescendants|savemempool|importmempool'

for pat in "${strict_patterns[@]}"; do
    if matches=$(printf '%s\n' "${FILES[@]}" \
                | xargs -d '\n' -r grep -InE "$pat" -- 2>/dev/null \
                | grep -vE "$allowlist_re" || true) \
       && [ -n "$matches" ]; then
        report "pattern '$pat':"
        echo "$matches" | head -20 >&2
    fi
done

# --- catch-all: any "mempool" (case-insensitive) outside the allowlist -----
if matches=$(printf '%s\n' "${FILES[@]}" \
            | xargs -d '\n' -r grep -InEi 'mempool' -- 2>/dev/null \
            | grep -vE "$allowlist_re" || true) \
   && [ -n "$matches" ]; then
    report "stray 'mempool' outside allowlist (RPC names):"
    echo "$matches" | head -40 >&2
fi

# --- upstream brand asset filenames ----------------------------------------
if [ "$MODE" = "dir" ]; then
    if branded=$(find . -type f \
                      \( -iname '*mempool*logo*' \
                       -o -iname '*mempool*icon*' \
                       -o -iname 'og-image*' \
                       -o -iname 'half-block*' \) \
                      -not -path './.git/*' \
                      -not -path './node_modules/*' 2>/dev/null) \
       && [ -n "$branded" ]; then
        report "upstream brand asset files present:"
        echo "$branded" >&2
    fi
fi

if [ "$fail" -eq 0 ]; then
    echo "tm-audit: PASS"
    exit 0
else
    echo "tm-audit: FAIL (see above; resolve before deploy)" >&2
    exit 1
fi
