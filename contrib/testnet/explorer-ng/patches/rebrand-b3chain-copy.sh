#!/usr/bin/env bash
#
# B3Chain user-visible copy + outbound link fixes for explorer-ng.
#
# Run after tools/strip-upstream-brand.sh on every install/rebase.
# Idempotent.
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
cd "$ROOT"

if [ ! -f frontend/package.json ]; then
    echo "rebrand-b3chain-copy: '$ROOT' does not look like explorer-ng" >&2
    exit 2
fi

echo "==> B3Chain copy + link rebrand"

is_text_file() { LC_ALL=C grep -Iq . "$1" 2>/dev/null; }

if command -v rg >/dev/null 2>&1; then
    LIST_COPY() { rg --files --hidden --no-ignore-vcs \
        -g '!.git' -g '!node_modules' -g '!dist' -g '!cache' \
        frontend backend \
        -g '*.html' -g '*.scss' -g '*.css' -g '*.ts' -g '*.xlf' -g '*.md' \
        -g '*.json'; }
else
    LIST_COPY() { find frontend backend -type f \
        \( -name '*.html' -o -name '*.scss' -o -name '*.css' \
           -o -name '*.ts' -o -name '*.xlf' -o -name '*.md' -o -name '*.json' \) \
        -not -path '*/node_modules/*' -not -path '*/dist/*'; }
fi

LIST_COPY | while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
        */LICENSE|*/LICENSE.md|*/COPYING|*/package-lock.json) continue ;;
    esac
    is_text_file "$f" || continue
    perl -i -pe '
        s/Explore the full Bitcoin ecosystem/Explore the B3Chain network/g;
        s/explore the full Bitcoin ecosystem/explore the B3Chain network/g;
        s/B3Chain Live Explorer Project(?:\xC2?\xAE|&reg;|\xAE)?/B3Chain Live Explorer/g;
        s/B3Chain Live Explorer Holdings S\.A\. de C\.V\./B3Chain/g;
        s/B3Chain Live Explorer Enterprise(?:\xC2?\xAE|&reg;|\xAE)?/B3Chain Enterprise/g;
        s/B3Chain Live Explorer Wallet/B3Chain Wallet/g;
        s|<title>mempool - Bitcoin Explorer</title>|<title>B3Chain Live Explorer</title>|g;
        s|Mempool - Bitcoin Explorer|B3Chain Live Explorer|g;
        s/content="@mempool"/content="@b3chain"/g;
        s/"@mempool"/"@b3chain"/g;
        s|https://github\.com/mempool/mempool(?!/blob/master/LICENSE)|https://github.com/b3chain/explorer-ng|g;
        s|https://github\.com/mempool\b|https://github.com/b3chain|g;
        s|https://explorer\.b3chain\.org/about|https://explorer.b3chain.org/v2/about|g;
        s|https://explorer\.b3chain\.org/enterprise|https://explorer.b3chain.org/v2/about|g;
        s|href="https://explorer\.b3chain\.org/"|href="https://explorer.b3chain.org/v2/"|g;
        s|content="https://explorer\.b3chain\.org"|content="https://explorer.b3chain.org/v2/"|g;
        s|\x27LIQUID_WEBSITE_URL\x27: \x27https://liquid\.network\x27|\x27LIQUID_WEBSITE_URL\x27: \x27https://explorer.b3chain.org/v2/\x27|g;
        s|"LIQUID_WEBSITE_URL": "https://liquid\.network"|"LIQUID_WEBSITE_URL": "https://explorer.b3chain.org/v2/"|g;
        s|<a href="https://liquid\.network/">liquid\.network</a>|liquid.network (not used on B3Chain)|g;
        s|<a href="https://bitcoin\.gob\.sv/">bitcoin\.gob\.sv</a>|bitcoin.gob.sv (not used on B3Chain)|g;
        s/The mempool open-source project aims to implement a high quality explorer and visualization website for the entire Bitcoin ecosystem/B3Chain Live Explorer is a block explorer for the B3Chain network/g;
        s/without distractions like altcoins, advertising, or third-party trackers/without third-party trackers/g;
    ' -- "$f" || true
done

for f in frontend/src/index.mempool.html frontend/src/index.html frontend/src/index.liquid.html; do
    [ -f "$f" ] || continue
    perl -i -pe '
        s/Explore the full Bitcoin ecosystem with B3Chain Live Explorer Project(?:\xC2?\xAE|&reg;|\xAE)?\./Explore the B3Chain testnet in real time with B3Chain Live Explorer./g;
        s/content="Explore the full Bitcoin ecosystem[^"]*"/content="Explore the B3Chain testnet in real time. See blocks, transactions, and network status."/g;
        s/content="B3Chain Live Explorer Project(?:\xC2?\xAE|&reg;|\xAE)?"/content="B3Chain Live Explorer"/g;
        s|<title>mempool - Bitcoin Explorer</title>|<title>B3Chain Live Explorer</title>|g;
        s|rel="canonical" href="https://explorer\.b3chain\.org"|rel="canonical" href="https://explorer.b3chain.org/v2/"|g;
    ' -- "$f"
    echo "    edit: $f"
done

f="frontend/src/app/shared/components/global-footer/global-footer.component.html"
if [ -f "$f" ]; then
    perl -i -pe '
        s|href="https://github\.com/mempool"|href="https://github.com/b3chain"|g;
        s|aria-label="mempool on GitHub"|aria-label="B3Chain on GitHub"|g;
    ' -- "$f"
    echo "    edit: $f"
fi

mkdir -p .b3chain
date -u +"%Y-%m-%dT%H:%M:%SZ" > .b3chain/rebrand-b3chain-copy.last-run.txt
echo "==> rebrand-b3chain-copy finished at $(cat .b3chain/rebrand-b3chain-copy.last-run.txt)"
