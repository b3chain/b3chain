#!/usr/bin/env bash
# Restore corrupted footer, re-apply patches, rebuild, rsync, verify.
set -euo pipefail
export LC_ALL=C

H=/tmp/explorer-ng-rebrand
CONTRIB="$H/contrib/testnet/explorer-ng"
EXPLORER_NG_SRC=/opt/b3chain-explorer-ng/explorer-ng
EXPLORER_NG_WEB=/var/www/b3chain-explorer-ng
EXPLORER_NG_USER=b3chain-explorer-ng

# Stop competing installs / builds (best-effort)
pkill -f 'b3chain-explorer-ng-ops/install.sh' 2>/dev/null || true
pkill -f 'ng build --configuration production' 2>/dev/null || true
sleep 3

cd "$EXPLORER_NG_SRC"
FOOTER=frontend/src/app/shared/components/global-footer/global-footer.component.html
if grep -qE '\*ngIf="false"[a-zA-Z]' "$FOOTER" 2>/dev/null; then
    git checkout -- "$FOOTER"
fi
# Re-run footer rebrand if marker missing or tagline still upstream
if grep -q 'Be your own explorer' "$FOOTER" 2>/dev/null; then
    perl -i -pe 's# <!-- B3CHAIN_FOOTER_REBRAND --> ##' "$FOOTER" 2>/dev/null || true
fi

bash "$CONTRIB/patches/rebrand-b3chain-copy.sh" "$EXPLORER_NG_SRC"
bash "$CONTRIB/patches/apply-chain-params.sh" "$EXPLORER_NG_SRC"
bash "$CONTRIB/patches/disable-matomo.sh" "$EXPLORER_NG_SRC"
bash "$CONTRIB/patches/replace-header-logo.sh" "$EXPLORER_NG_SRC"
bash "$CONTRIB/patches/rebrand-footer.sh" "$EXPLORER_NG_SRC"

install -m 0644 "$CONTRIB/config/b3chain-frontend-config.json" \
    "$EXPLORER_NG_SRC/frontend/mempool-frontend-config.json"

echo "==> frontend rebuild"
sudo -u "$EXPLORER_NG_USER" -H bash -lc "
    set -e
    cd '$EXPLORER_NG_SRC/frontend'
    node generate-themes.js
    node generate-config.js
    npx ng build --configuration production --base-href /v2/
"

SRC_DIST=
for d in dist/mempool/browser dist/mempool dist/explorer/browser dist/explorer dist; do
    if [ -d "$EXPLORER_NG_SRC/frontend/$d" ] && [ -f "$EXPLORER_NG_SRC/frontend/$d/index.html" ]; then
        SRC_DIST="$EXPLORER_NG_SRC/frontend/$d"
        break
    fi
done
[ -n "$SRC_DIST" ] || { echo "no dist"; exit 5; }

rsync -a --delete "$SRC_DIST/" "$EXPLORER_NG_WEB/"
rsync -a "$EXPLORER_NG_SRC/frontend/src/resources/" "$EXPLORER_NG_WEB/resources/"
install -d -m 0755 -o root -g www-data "$EXPLORER_NG_WEB/resources/mining-pools"
install -m 0644 -o root -g www-data \
    "$CONTRIB/assets/mining-pools/"*.svg \
    "$EXPLORER_NG_WEB/resources/mining-pools/" 2>/dev/null || true
chown -R root:www-data "$EXPLORER_NG_WEB"

bash "$CONTRIB/verify.sh"
echo fix-remote-footer OK
