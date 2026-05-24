#!/usr/bin/env bash
#
# Two-tier trademark audit for the B3Chain Live Explorer fork.
#
# Aligns with the project's "Trademark posture" (see plan §"Trademark
# sanitization checklist"):
#
#   TIER 1 (HARD BAN — anywhere in the tree):
#     - https://mempool.space (canonical upstream domain)
#     - "Mempool Goggles" / "Mempool Accelerator" (trademarked features)
#     - "The Mempool Open Source Project" (entity name)
#     - upstream brand asset filenames (logo / icon / og-image / half-block)
#     - upstream integrator HTML templates index.mempool.*.html
#     Carve-out: a single AGPL §5 attribution line containing
#     "AGPLv3 source at https://github.com/mempool/mempool" is allowed.
#
#   TIER 2 (USER-VISIBLE BAN):
#     The standalone capitalized word "Mempool" in user-visible text:
#     *.html, *.scss, *.css, *.svg (only those serving as og-image / icons),
#     and any text inside og:* meta tags / <title>. Code identifiers and
#     internal source filenames are allowed (renaming class names like
#     MempoolBlock would fork the codebase needlessly; the plan permits
#     this for AGPL-inherited internal identifiers).
#     Carve-outs: AGPL attribution; bitcoind RPC method names.
#
# Run modes:
#   tm-audit.sh                  audit cwd (the b3chain/explorer-ng repo)
#   tm-audit.sh <dir>            audit specific directory
#   tm-audit.sh --staged         audit staged files only (pre-commit hook)
#
# Auto-skips when run inside the b3chain bitcoin-core mono-repo, which
# legitimately contains the technical term "mempool" in protocol code/docs.
set -euo pipefail
export LC_ALL=C

MODE="dir"
TARGET="."
case "${1:-}" in
    --staged) MODE="staged" ;;
    "") ;;
    *) TARGET="$1" ;;
esac

fail=0
report() { echo "TM AUDIT FAIL: $*" >&2; fail=1; }

is_explorer_ng_tree() {
    local root
    root=$(git rev-parse --show-toplevel 2>/dev/null) || return 1
    [ -f "$root/frontend/package.json" ] && [ -f "$root/backend/package.json" ]
}

# --- file-path exclusions --------------------------------------------------
path_exclude_re='(^|/)(\.cursor/plans/[^/]+\.plan\.md|doc/MEMPOOL-SPACE-REPLICATION-SPEC\.md|contrib/testnet/explorer-ng/(README\.md|install\.sh|verify\.sh|bootstrap-fork\.sh|mariadb-schema\.sh|tools/[^/]+\.sh|patches/[^/]+\.sh|nginx/[^/]+\.conf|systemd/[^/]+\.service|config/[^/]+)|LICENSE|COPYING|\.b3chain/.*)$'

# --- file list -------------------------------------------------------------
if [ "$MODE" = "staged" ]; then
    mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACMR \
                          | grep -v -E '\.(png|jpg|jpeg|gif|webp|woff2?|ttf|eot|ico|map)$' \
                          | grep -vE "$path_exclude_re" || true)
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
    # Use git ls-files if it returns a non-empty list (the repo has commits);
    # otherwise (fresh import before first git add) fall back to find. This
    # is critical: bootstrap-fork.sh calls tm-audit immediately after the
    # codemod, before "git add -A".
    mapfile -t TRACKED < <(git ls-files 2>/dev/null || true)
    if [ "${#TRACKED[@]}" -gt 0 ]; then
        SOURCE_LIST=$(printf '%s\n' "${TRACKED[@]}")
    else
        SOURCE_LIST=$(find . -type f \
                  -not -path './node_modules/*' \
                  -not -path './.git/*' \
                  -not -path './dist/*' \
                  -not -path './cache/*' \
                  -not -name '*.png' -not -name '*.jpg' -not -name '*.jpeg' \
                  -not -name '*.gif' -not -name '*.webp' -not -name '*.woff' \
                  -not -name '*.woff2' -not -name '*.ttf' -not -name '*.eot' \
                  -not -name '*.ico' -not -name '*.map')
    fi
    mapfile -t FILES < <(
        printf '%s\n' "$SOURCE_LIST" \
        | sed 's|^\./||' \
        | grep -vE "$path_exclude_re" || true
    )
fi

# --- TIER 1: hard ban ------------------------------------------------------
allowlist_re='AGPLv3 source at https://github\.com/mempool/mempool|getrawmempool|testmempoolaccept|getmempoolentry|getmempoolinfo|getmempoolancestors|getmempooldescendants|savemempool|importmempool'

tier1_patterns=(
    'mempool\.space'
    '\bMempool Goggles\b'
    '\bMempool Accelerator\b'
    'The Mempool Open Source Project'
    'twitter\.com/mempool'
)

for pat in "${tier1_patterns[@]}"; do
    matches=$(printf '%s\n' "${FILES[@]+"${FILES[@]}"}" \
              | xargs -d '\n' -r grep -InE "$pat" -- 2>/dev/null \
              | grep -vE "$allowlist_re" || true)
    if [ -n "$matches" ]; then
        report "[TIER 1] '$pat':"
        echo "$matches" | head -20 >&2
    fi
done

# --- TIER 1: upstream brand asset / integrator template files -------------
# Banned by file *name pattern* (regardless of path). AGPL-inherited
# component source files (mempool-blocks.component.ts etc.) are allowed
# per the plan's "internal source filenames" carve-out and do NOT match
# any of these patterns.
if [ "$MODE" = "dir" ]; then
    branded=$(find . -type f \( \
                    -iname '*mempool*-logo*' \
                 -o -iname '*mempool*-icon*' \
                 -o -iname 'mempool-space-*' \
                 -o -iname 'mempool-preview*' \
                 -o -iname 'mempool-tube*' \
                 -o -iname 'mempool-research*' \
                 -o -iname 'mempool-holdings*' \
                 -o -iname 'mempool-transaction*' \
                 -o -iname 'mempool-promo*' \
                 -o -iname 'mempool-accelerator*' \
                 -o -iname '*-accelerator-sparkle*' \
                 -o -iname 'og-image*' \
                 -o -iname 'half-block*' \
                 -o -iname 'index.mempool.*.html' \
              \) -not -path './.git/*' -not -path './node_modules/*' 2>/dev/null || true)
    if [ -n "$branded" ]; then
        report "[TIER 1] upstream brand asset / integrator files present:"
        echo "$branded" | head -30 >&2
    fi
fi

# --- TIER 2: standalone "Mempool" in user-visible channels ----------------
# User-visible channels: HTML, SCSS/CSS, manifest, og-image SVG content,
# README.md (top-level only). Code (.ts/.js) is exempt: AGPL-inherited
# class identifiers like MempoolBlock are allowed.
declare -a USER_VISIBLE=()
for f in "${FILES[@]+"${FILES[@]}"}"; do
    case "$f" in
        *.html|*.scss|*.css|*.svg|*.xlf|*.md|*manifest*.json|*og-tags*)
            USER_VISIBLE+=("$f") ;;
    esac
done

if [ "${#USER_VISIBLE[@]}" -gt 0 ]; then
    matches=$(printf '%s\n' "${USER_VISIBLE[@]}" \
              | xargs -d '\n' -r grep -InE '\bMempool\b' -- 2>/dev/null \
              | grep -vE "$allowlist_re" || true)
    if [ -n "$matches" ]; then
        report "[TIER 2] standalone 'Mempool' in user-visible files:"
        echo "$matches" | head -40 >&2
    fi
fi

if [ "$fail" -eq 0 ]; then
    echo "tm-audit: PASS"
    exit 0
else
    echo "tm-audit: FAIL (resolve before deploy)" >&2
    exit 1
fi
