#!/usr/bin/env bash
echo "=== package.json scripts ==="
sed -n '/"scripts": {/,/}/p' /tmp/upstream-check/frontend/package.json | head -50
echo
echo "=== sync-assets script ==="
ls /tmp/upstream-check/frontend/sync-assets.* 2>&1 | head -10
echo
echo "=== generate-config script ==="
ls /tmp/upstream-check/frontend/generate-config* /tmp/upstream-check/frontend/scripts/ 2>&1 | head -20
echo
echo "=== MEMPOOL_BRAND in scripts ==="
grep -rn MEMPOOL_BRAND /tmp/upstream-check/frontend/*.js /tmp/upstream-check/frontend/scripts/ 2>/dev/null | head -10
echo
echo "=== how does ng build choose index.html? ==="
grep -n -E '"index"|"index":' /tmp/upstream-check/frontend/angular.json
