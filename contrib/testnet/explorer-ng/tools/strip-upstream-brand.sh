#!/usr/bin/env bash
#
# Codemod: strip upstream brand from a fresh clone of mempool/mempool.
#
# Used by:
#   - bootstrap-fork.sh (one-shot during fork creation)
#   - operator on every upstream rebase
#
# Idempotent. After this script, `tools/tm-audit.sh` should pass.
#
# Strategy (aligned with the plan's "Trademark posture"):
#
#   AGGRESSIVE on the public surface (assets, HTML user-visible text,
#   marketing copy, og-image, integrator templates, page titles).
#
#   CONSERVATIVE in the code surface — keep TypeScript class names
#   (MempoolBlock, MempoolBlocksRepository, etc.), config namespace
#   (`MEMPOOL` / `MEMPOOL_X` env vars), and internal source filenames.
#   The plan explicitly permits these as AGPL-inherited internal
#   identifiers; rebranding them would require a costly fork that we
#   couldn't keep in sync with upstream.
#
#   The trademark line we don't cross: capital "Mempool" / brand assets /
#   "Mempool Goggles" / "Mempool Accelerator" / "The Mempool Open Source
#   Project" / mempool.space domain in user-visible channels.
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
cd "$ROOT"

if [ ! -f frontend/package.json ] && [ ! -f backend/package.json ]; then
    echo "strip-upstream-brand: '$ROOT' does not look like a mempool/mempool clone" >&2
    exit 2
fi

echo "==> stripping upstream brand assets, marketing copy, integrator templates"

# 1. Delete upstream marketing / brand pages (we replace with our own).
rm -rf \
    frontend/src/app/components/about \
    frontend/src/app/components/trademark-policy \
    frontend/src/app/components/terms-of-service \
    frontend/src/app/components/privacy-policy \
    frontend/cypress \
    frontend/src/index.mempool.*.html \
    docker/.github 2>/dev/null || true

# 2. Brand asset files: delete by *name pattern* (any path).
find . -type f \( \
        -iname '*mempool*-logo*' \
     -o -iname '*mempool*-icon*' \
     -o -iname 'mempool-space-*' \
     -o -iname 'mempool-blocks-2-*' \
     -o -iname 'mempool-blocks-3-*' \
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
     \) \
     -not -path './.git/*' \
     -not -path './node_modules/*' \
     -delete 2>/dev/null || true

# 3. Other brand-only files at root or top level.
rm -f \
    frontend/mempool-frontend-config.sample.json \
    docker/backend/mempool-config.json \
    nginx-mempool.conf \
    frontend/src/resources/bimi.svg \
    2>/dev/null || true

# 4. Source-level token rewrites (USER-VISIBLE channels only:
#    HTML, SCSS, CSS, manifest JSON, top-level README files,
#    SVG title-tag content). We do NOT touch TS/JS class names,
#    config namespace, or internal identifiers.
echo "==> rewriting user-visible brand tokens (HTML/SCSS/CSS/manifest/README/SVG)"

if command -v rg >/dev/null 2>&1; then
    LIST_VISIBLE() { rg --files --hidden --no-ignore-vcs \
                       -g '!.git' -g '!node_modules' -g '!dist' -g '!cache' \
                       -g '*.html' -g '*.scss' -g '*.css' \
                       -g 'manifest*.json' -g '*og-tags*' \
                       -g 'README.md' -g '*/README.md' \
                       -g '*.svg'; }
else
    LIST_VISIBLE() { find . -type f \
                  -not -path './.git/*' -not -path './node_modules/*' \
                  -not -path './dist/*' -not -path './cache/*' \
                  \( -name '*.html' -o -name '*.scss' -o -name '*.css' \
                     -o -name 'manifest*.json' -o -name '*og-tags*' \
                     -o -name 'README.md' -o -name '*.svg' \); }
fi

is_text_file() { LC_ALL=C grep -Iq . "$1" 2>/dev/null; }

LIST_VISIBLE | while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
        */LICENSE|*/LICENSE.md|*/COPYING) continue ;;
    esac
    is_text_file "$f" || continue
    perl -i -pe '
        # Trademark feature / entity strings (multi-word, brand-only)
        s/\bThe Mempool Open Source Project\b/B3Chain Live Explorer Project/g;
        s/\bMempool Open Source Project\b/B3Chain Live Explorer Project/g;
        s/\bMempool Goggles\xC2?\xAE?\b/Tx Filters/g;
        s/\bMempool Accelerator\b/Transaction Accelerator (disabled)/g;
        # Specific upstream UI labels
        s/\bMempool by vBytes\b/Pending Pool by vBytes/g;
        s/\bMempool Block\b/Pending Block/g;
        s/\bMempool size\b/Pending pool size/g;
        s/Visualize the Mempool/Visualize the Pending Pool/g;
        s/Mempool - Bitcoin Explorer/B3Chain Live Explorer/g;
        # Domain references (canonical upstream brand domain)
        s|https?://(?:www\.)?mempool\.space|https://explorer.b3chain.org|g
            unless m{AGPLv3 source at https://github\.com/mempool/mempool};
        s|\bmempool\.space\b|explorer.b3chain.org|g
            unless m{AGPLv3 source at https://github\.com/mempool/mempool};
        # Standalone brand word in user-visible text
        s/\bMempool\b/B3Chain Live Explorer/g
            unless m{AGPLv3 source at https://github\.com/mempool/mempool};
    ' -- "$f" || true
done

# 5. Code-surface pass: replace `mempool.space` URL references (the canonical
#    upstream brand domain) in ALL text files. This narrow rule does NOT
#    rename class names or config namespace; it just stops production code
#    from pointing at upstream's servers.
echo "==> rewriting mempool.space references in all text files"
if command -v rg >/dev/null 2>&1; then
    LIST_ALL() { rg --files --hidden --no-ignore-vcs \
                    -g '!.git' -g '!node_modules' -g '!dist' -g '!cache' \
                    -g '!*.png' -g '!*.jpg' -g '!*.jpeg' -g '!*.gif' \
                    -g '!*.webp' -g '!*.woff' -g '!*.woff2' -g '!*.ttf' \
                    -g '!*.eot' -g '!*.ico' -g '!*.map' \
                    -g '!*.lock' -g '!package-lock.json'; }
else
    LIST_ALL() { find . -type f \
                  -not -path './.git/*' -not -path './node_modules/*' \
                  -not -path './dist/*' -not -path './cache/*' \
                  -not -name '*.png' -not -name '*.jpg' -not -name '*.jpeg' \
                  -not -name '*.gif' -not -name '*.webp' -not -name '*.woff' \
                  -not -name '*.woff2' -not -name '*.ttf' -not -name '*.eot' \
                  -not -name '*.ico' -not -name '*.map' \
                  -not -name '*.lock' -not -name 'package-lock.json'; }
fi

LIST_ALL | while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
        */LICENSE|*/LICENSE.md|*/COPYING) continue ;;
    esac
    is_text_file "$f" || continue
    perl -i -pe '
        s|https?://(?:www\.)?mempool\.space|https://explorer.b3chain.org|g
            unless m{AGPLv3 source at https://github\.com/mempool/mempool};
        s|\bmempool\.space\b|explorer.b3chain.org|g
            unless m{AGPLv3 source at https://github\.com/mempool/mempool};
    ' -- "$f" || true
done

# 6. Final marker: write a stamp so re-runs are visibly idempotent.
mkdir -p .b3chain
date -u +"%Y-%m-%dT%H:%M:%SZ" > .b3chain/strip-upstream-brand.last-run.txt
echo "$0 finished at $(cat .b3chain/strip-upstream-brand.last-run.txt)"
echo "==> run tools/tm-audit.sh to verify"
