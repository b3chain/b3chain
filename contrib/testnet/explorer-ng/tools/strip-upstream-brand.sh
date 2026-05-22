#!/usr/bin/env bash
#
# Codemod: strip upstream brand from a fresh clone of mempool/mempool.
#
# Used by:
#   - bootstrap-fork.sh (one-shot during fork creation)
#   - operator on every upstream rebase
#
# Idempotent: running twice is a no-op.
#
# After this script, `tools/tm-audit.sh` should pass on the same tree.
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
cd "$ROOT"

if [ ! -f frontend/package.json ] && [ ! -f backend/package.json ]; then
    echo "strip-upstream-brand: '$ROOT' does not look like a mempool/mempool clone" >&2
    exit 2
fi

echo "==> stripping upstream brand assets and naming"

# 1. Delete upstream brand pages, integrator HTMLs, brand-only feature dirs,
#    and the entire upstream cypress test suite (it targets mempool.space's
#    specific RBF history fixtures and is irrelevant to B3Chain).
rm -rf \
    frontend/src/app/components/about \
    frontend/src/app/components/trademark-policy \
    frontend/src/app/components/terms-of-service \
    frontend/src/app/components/privacy-policy \
    frontend/src/app/components/acceleration \
    frontend/src/app/components/accelerate-* \
    frontend/src/app/components/accelerator-* \
    frontend/src/app/components/acceleration-* \
    frontend/src/app/services/accelerat* \
    backend/src/api/services/accelerat* \
    backend/src/api/services/mempool-acceleration* \
    frontend/cypress \
    frontend/src/index.mempool.*.html \
    docker/.github 2>/dev/null || true

# 2. Brand asset filenames (any path, broad glob).
find . -type f \( \
        -iname '*mempool*logo*' \
     -o -iname '*mempool*icon*' \
     -o -iname 'mempool-space-*' \
     -o -iname '*mempool*-blocks-*' \
     -o -iname 'mempool-preview*' \
     -o -iname 'mempool-tube*' \
     -o -iname 'mempool-research*' \
     -o -iname 'mempool-holdings*' \
     -o -iname 'mempool-transaction*' \
     -o -iname 'mempool-promo*' \
     -o -iname '*-accelerator-*' \
     -o -iname 'og-image*' \
     -o -iname 'half-block*' \
     \) \
     -not -path './.git/*' \
     -not -path './node_modules/*' \
     -delete 2>/dev/null || true

# 3. Drop frontend integrator config templates (mempool.space-specific).
rm -f \
    frontend/mempool-frontend-config.sample.json \
    docker/backend/mempool-config.json \
    nginx-mempool.conf \
    frontend/src/resources/bimi.svg \
    2>/dev/null || true

# 2. Rename internal files where the rename is mechanical and free.
move_safe() {
    local from=$1 to=$2
    if [ -e "$from" ] && [ ! -e "$to" ]; then
        mkdir -p "$(dirname "$to")"
        git mv -f "$from" "$to" 2>/dev/null || mv "$from" "$to"
    fi
}
move_safe backend/src/api/mempool-blocks.ts backend/src/api/pending-blocks.ts
move_safe backend/src/api/mempool.ts backend/src/api/tx-pool.ts
move_safe backend/src/repositories/MempoolBlocksRepository.ts backend/src/repositories/PendingBlocksRepository.ts
move_safe production/nginx-mempool-frontend.conf production/nginx-explorer-ng-frontend.conf
move_safe production/nginx-mempool-backend.conf production/nginx-explorer-ng-backend.conf
move_safe mempool-config.sample.json explorer-ng-config.sample.json
move_safe backend/mempool-config.sample.json backend/explorer-ng-config.sample.json
move_safe backend/mempool-config.sample-dev.json backend/explorer-ng-config.sample-dev.json

# 3. Source-level token rewrites. Targets text files only (rg --files).
echo "==> rewriting tokens in source"

if command -v rg >/dev/null 2>&1; then
    LIST() { rg --files --hidden --no-ignore-vcs \
                -g '!.git' -g '!node_modules' -g '!dist' -g '!cache' -g '!*.svg' \
                -g '!*.png' -g '!*.jpg' -g '!*.jpeg' -g '!*.gif' -g '!*.webp' \
                -g '!*.woff' -g '!*.woff2' -g '!*.ttf' -g '!*.eot' -g '!*.ico' \
                -g '!*.map' -g '!*.lock' -g '!package-lock.json'; }
else
    LIST() { find . -type f \
                  -not -path './.git/*' -not -path './node_modules/*' \
                  -not -path './dist/*' -not -path './cache/*' \
                  -not -name '*.svg' -not -name '*.png' -not -name '*.jpg' \
                  -not -name '*.jpeg' \
                  -not -name '*.gif' -not -name '*.webp' -not -name '*.woff' \
                  -not -name '*.woff2' -not -name '*.ttf' -not -name '*.eot' \
                  -not -name '*.ico' -not -name '*.map' \
                  -not -name '*.lock' -not -name 'package-lock.json'; }
fi

# Helper: skip binary / non-UTF8 files which choke perl -CSD.
is_text_file() {
    LC_ALL=C grep -Iq . "$1" 2>/dev/null
}

# We allow the AGPL attribution line and the bitcoind RPC method names to stay.
# Everything else: rewrite.
LIST | while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
        */LICENSE|*/LICENSE.md|*/COPYING) continue ;;
    esac
    is_text_file "$f" || continue
    # Use perl WITHOUT -CSD (we let perl treat input as bytes; rewrites are
    # ASCII-safe). Multi-pattern atomic in-place edit.
    #
    # The catchall `\bMempool\b` rule must produce a SINGLE-WORD identifier
    # because `Mempool` appears in TypeScript class names like
    # `class Mempool { ... }` and replacing with a multi-word phrase
    # ("B3Chain Live Explorer") would corrupt the source. We use `TxPool`,
    # which is a valid TS identifier and an acceptable user-visible label.
    # The full brand name "B3Chain Live Explorer" is set elsewhere, in
    # specific page titles / og-tags via apply-chain-params.sh.
    perl -i -pe '
        # 1) Trademark feature / entity strings (multi-word; safe everywhere)
        s/\bThe Mempool Open Source Project\b/B3Chain Live Explorer Project/g;
        s/\bMempool Open Source Project\b/B3Chain Live Explorer Project/g;
        s/\bMempool Goggles\xC2?\xAE?\b/Tx Filters/g;
        s/\bMempool Accelerator\b/Transaction Accelerator (disabled)/g;
        # 2) Specific UI labels first (more specific than the catchall)
        s/\bMempool by vBytes\b/TxPool by vBytes/g;
        s/\bMempool Block\b/Pending Block/g;
        s/\bMempool size\b/TxPool size/g;
        s/Visualize the Mempool/Visualize the Pending Pool/g;
        s/Mempool - Bitcoin Explorer/B3Chain Live Explorer/g;
        # 3) Domain references (canonical upstream brand domain).
        s|https?://(?:www\.)?mempool\.space|https://explorer.b3chain.org|g
            unless m{AGPLv3 source at https://github\.com/mempool/mempool};
        s|\bmempool\.space\b|explorer.b3chain.org|g
            unless m{AGPLv3 source at https://github\.com/mempool/mempool};
        # 4) Standalone brand word -> single-word identifier "TxPool".
        s/\bMempool\b/TxPool/g
            unless m{getrawmempool|testmempoolaccept|getmempoolentry|getmempoolinfo|getmempoolancestors|getmempooldescendants|savemempool|importmempool|AGPLv3 source at https://github\.com/mempool/mempool};
    ' -- "$f" || true
done

# 4. Backend env namespace: MEMPOOL_X / MEMPOOL.X -> B3CHAIN_X / B3CHAIN.X.
LIST | while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
        */LICENSE|*/LICENSE.md|*/COPYING) continue ;;
    esac
    is_text_file "$f" || continue
    perl -i -pe '
        # ENV vars at start of line or after whitespace
        s/(^|[\s\W])MEMPOOL_(?=[A-Z_]+)/$1B3CHAIN_/g;
        # Config namespace key "MEMPOOL" before "."
        s/"MEMPOOL"(\s*:)/"B3CHAIN"$1/g;
        s/\bconfig\.MEMPOOL\b/config.B3CHAIN/g;
        s/\bMEMPOOL\.([A-Z_]+)/B3CHAIN.$1/g
            unless m{MEMPOOL_BLOCKS|MEMPOOL_TX};  # leave ngrx-style code names alone for now
    ' -- "$f" || true
done

# 5. Drop accelerator routes from frontend routing if a residue remained.
for f in \
    frontend/src/app/graphs/graphs.routing.module.ts \
    frontend/src/app/master-page.module.ts ; do
    [ -f "$f" ] || continue
    perl -i -0777 -pe '
        s/,?\s*\{\s*path:\s*[^\}]*acceleration[^\}]*\}//g;
        s/,?\s*\{\s*path:\s*[^\}]*accelerator[^\}]*\}//gi;
    ' -- "$f" || true
done

# 6. Final marker: write a stamp so re-runs are visibly idempotent.
mkdir -p .b3chain
date -u +"%Y-%m-%dT%H:%M:%SZ" > .b3chain/strip-upstream-brand.last-run.txt
echo "$0 finished at $(cat .b3chain/strip-upstream-brand.last-run.txt)"
echo "==> run tools/tm-audit.sh to verify"
