#!/usr/bin/env bash
#
# Replace upstream mempoolSpace inline SVG logo with B3Chain logo image.
#
# When OFFICIAL=false (our default), master-page shows app-svg-images
# name="mempoolSpace" — the half-block icon + "mempool" wordmark.
# This patch swaps those for /resources/b3chain-explorer-ng-logo.svg.
#
# Run after rebrand-b3chain-copy.sh. Idempotent.
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
cd "$ROOT"

if [ ! -f frontend/package.json ]; then
    echo "replace-header-logo: '$ROOT' does not look like explorer-ng" >&2
    exit 2
fi

LOGO_SRC="$ROOT/frontend/src/resources/b3chain-explorer-ng-logo.svg"
if [ ! -f "$LOGO_SRC" ]; then
    CONTRIB_LOGO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/assets/b3chain-explorer-ng-logo.svg"
    if [ -f "$CONTRIB_LOGO" ]; then
        mkdir -p "$(dirname "$LOGO_SRC")"
        cp "$CONTRIB_LOGO" "$LOGO_SRC"
        echo "    installed logo -> $LOGO_SRC"
    else
        echo "replace-header-logo: missing b3chain-explorer-ng-logo.svg" >&2
        exit 3
    fi
fi

# Safe replacement: never capture $1 with *ngIf inside (perl treats * as quantifier).
replace_mempool_logo() {
    local f="$1"
    [ -f "$f" ] || return 0
    if grep -q 'b3chain-explorer-ng-logo.svg' "$f" 2>/dev/null \
       && ! grep -q 'name="mempoolSpace"' "$f" 2>/dev/null; then
        return 0
    fi
    perl -i -pe '
        s|<app-svg-images \*ngIf="!officialMempoolSpace" name="mempoolSpace" viewBox="0 0 500 126" class="mempool-logo" (\[ngStyle\]="\{'\''opacity'\'': connectionState\.val === 2 \? 1 : 0.5 \}")\s*></app-svg-images>|<img *ngIf="!officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo mempool-logo" $1 />|g;
        s|<app-svg-images \*ngIf="!officialMempoolSpace" name="mempoolSpace" viewBox="0 0 500 126" class="mempool-logo" style="[^"]*"\s*></app-svg-images>|<img *ngIf="!officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo mempool-logo" style="width: 200px; height: 50px" />|g;
        s|<app-svg-images \*ngIf="!officialMempoolSpace" name="mempoolSpace" viewBox="0 0 500 126" width="500" height="126" class="mempool-logo" style="[^"]*"\s*></app-svg-images>|<img *ngIf="!officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo mempool-logo" style="width: 200px; height: 50px" />|g;
        s|<app-svg-images \*ngIf="!officialMempoolSpace" name="mempoolSpace" viewBox="0 0 500 126" class="mempool-logo"\s*></app-svg-images>|<img *ngIf="!officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo mempool-logo" />|g;
        s|<app-svg-images \*ngIf="officialMempoolSpace" name="officialMempoolSpace" viewBox="0 0 500 126"\s*></app-svg-images>|<img *ngIf="officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo mempool-logo" />|g;
        s|<app-svg-images \*ngIf="!officialMempoolSpace" name="mempoolSpace" viewBox="0 0 500 126"\s*></app-svg-images>|<img *ngIf="!officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo mempool-logo" />|g;
    ' -- "$f"
    echo "    edit: $f"
}

echo "==> replacing mempoolSpace header/footer logos"
replace_mempool_logo frontend/src/app/components/master-page/master-page.component.html
replace_mempool_logo frontend/src/app/components/master-page-preview/master-page-preview.component.html
replace_mempool_logo frontend/src/app/components/tracker/tracker.component.html
# Footer uses simple self-closing svg-images tags (no extra attrs).
F=frontend/src/app/shared/components/global-footer/global-footer.component.html
if [ -f "$F" ] && grep -q 'name="mempoolSpace"' "$F" 2>/dev/null; then
    perl -i -pe '
        s|<app-svg-images \*ngIf="officialMempoolSpace" name="officialMempoolSpace" viewBox="0 0 500 126"></app-svg-images>|<img *ngIf="officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo" style="height:50px;width:auto;" />|g;
        s|<app-svg-images \*ngIf="!officialMempoolSpace" name="mempoolSpace" viewBox="0 0 500 126"></app-svg-images>|<img *ngIf="!officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo" style="height:50px;width:auto;" />|g;
    ' -- "$F"
    echo "    edit: $F"
fi

for f in frontend/src/app/components/master-page/master-page.component.scss \
         frontend/src/app/components/master-page-preview/master-page-preview.component.scss \
         frontend/src/app/shared/components/global-footer/global-footer.component.scss; do
    [ -f "$f" ] || continue
    if ! grep -q 'b3chain-logo' "$f" 2>/dev/null; then
        cat >>"$f" <<'SCSS'

.b3chain-logo {
  height: 36px;
  width: auto;
  max-width: 220px;
  object-fit: contain;
}
SCSS
        echo "    edit: $f (b3chain-logo styles)"
    fi
done

mkdir -p .b3chain
date -u +"%Y-%m-%dT%H:%M:%SZ" > .b3chain/replace-header-logo.last-run.txt
echo "==> replace-header-logo finished at $(cat .b3chain/replace-header-logo.last-run.txt)"
