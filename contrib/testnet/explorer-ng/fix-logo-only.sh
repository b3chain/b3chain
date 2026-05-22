#!/usr/bin/env bash
# Minimal: fix footer if needed, apply logo patches, one ng build, rsync. For 4GB VPS.
set -euo pipefail
export LC_ALL=C

H=/tmp/explorer-ng-rebrand
CONTRIB="$H/contrib/testnet/explorer-ng"
EXPLORER_NG_SRC=/opt/b3chain-explorer-ng/explorer-ng
EXPLORER_NG_WEB=/var/www/b3chain-explorer-ng
EXPLORER_NG_USER=b3chain-explorer-ng

pkill -f 'ng build --configuration production' 2>/dev/null || true
sleep 3

cd "$EXPLORER_NG_SRC"
git checkout -- frontend/src/app/shared/components/global-footer/global-footer.component.html 2>/dev/null || true

bash "$CONTRIB/patches/replace-header-logo.sh" "$EXPLORER_NG_SRC"
bash "$CONTRIB/patches/rebrand-footer.sh" "$EXPLORER_NG_SRC"

install -m 0644 "$CONTRIB/assets/b3chain-explorer-ng-logo.svg" \
    "$EXPLORER_NG_SRC/frontend/src/resources/b3chain-explorer-ng-logo.svg"

echo "==> ng build"
sudo -u "$EXPLORER_NG_USER" -H bash -lc "
    set -e
    export NODE_OPTIONS='--max-old-space-size=1536'
    cd '$EXPLORER_NG_SRC/frontend'
    node generate-themes.js
    node generate-config.js
    npx ng build --configuration production --base-href /v2/
"

SRC_DIST=
for d in dist/mempool/browser dist/mempool; do
    if [ -d "$EXPLORER_NG_SRC/frontend/$d" ] && [ -f "$EXPLORER_NG_SRC/frontend/$d/index.html" ]; then
        SRC_DIST="$EXPLORER_NG_SRC/frontend/$d"
        break
    fi
done
[ -n "$SRC_DIST" ] || { echo "no dist"; exit 5; }

rsync -a --delete "$SRC_DIST/" "$EXPLORER_NG_WEB/"
rsync -a "$EXPLORER_NG_SRC/frontend/src/resources/" "$EXPLORER_NG_WEB/resources/"
chown -R root:www-data "$EXPLORER_NG_WEB"

bash "$CONTRIB/verify.sh"
echo fix-logo-only OK
