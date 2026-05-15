#!/usr/bin/env bash
# One-shot patch script to apply the two btc-rpc-explorer fixes (see
# install.sh sections "Rate-limiter skip list" and "Defensive patch for
# an upstream empty-mempool crash") to a deployed explorer without a
# full reinstall. Idempotent.
set -euo pipefail

APPJS=/var/lib/b3chain-explorer/node_modules/btc-rpc-explorer/app.js
COREAPI=/var/lib/b3chain-explorer/node_modules/btc-rpc-explorer/app/api/coreApi.js

# 1. app.js: skip /internal-api/ in the rate-limit middleware
if [ -f "$APPJS" ] && ! grep -q 'req.originalUrl.includes("/internal-api/")' "$APPJS"; then
    sed -i 's#req\.originalUrl\.includes("/api/")#req.originalUrl.includes("/api/") || req.originalUrl.includes("/internal-api/")#' "$APPJS"
    echo "app.js: patched"
else
    echo "app.js: already patched (or missing)"
fi

# 2. coreApi.js: guard buildMempoolSummary against empty-mempool topIndex=-1
if [ -f "$COREAPI" ] && grep -qF 'if (topIndex < satoshiPerByteBuckets.length) {' "$COREAPI"; then
    sed -i 's|if (topIndex < satoshiPerByteBuckets.length) {|if (topIndex >= 0 \&\& topIndex < satoshiPerByteBuckets.length) {|' "$COREAPI"
    echo "coreApi.js: patched"
else
    echo "coreApi.js: already patched (or missing)"
fi

echo "--- verify ---"
grep -n 'internal-api' "$APPJS" | head -5
grep -n 'topIndex >= 0' "$COREAPI" | head -5

systemctl restart b3chain-explorer.service
echo "--- service status ---"
systemctl is-active b3chain-explorer.service
