#!/usr/bin/env bash
#
# Smoke verification for B3Chain Live Explorer on seed1.
#
# Checks (each must pass):
#   1. tm-audit.sh on the deployed source tree.
#   2. systemd unit b3chain-explorer-ng is active.
#   3. RPC tip (from b3chaind) == backend's exposed tip on /v2/api/v1/blocks/tip/height.
#   4. Frontend index.html renders at https://explorer.b3chain.org/v2/.
#   5. WebSocket upgrade succeeds at /v2/api/v1/ws.
#   6. No upstream brand string is HTML-served at /v2/.
set -euo pipefail
export LC_ALL=C

EXPLORER_NG_SRC="${EXPLORER_NG_SRC:-/opt/b3chain-explorer-ng/explorer-ng}"
EXPLORER_HOST="${EXPLORER_HOST:-https://explorer.b3chain.org}"
THIS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

fail=0
ok() { echo "    OK   - $*"; }
bad() { echo "    FAIL - $*" >&2; fail=1; }

echo "==> 1. trademark audit"
if bash "$THIS_DIR/tools/tm-audit.sh" "$EXPLORER_NG_SRC" >/tmp/tm-audit.log 2>&1; then
    ok "tm-audit clean"
else
    bad "tm-audit failed; see /tmp/tm-audit.log"
fi

echo "==> 2. systemd unit"
if systemctl is-active --quiet b3chain-explorer-ng.service; then
    ok "service active"
else
    bad "service not active"
fi

echo "==> 3. RPC tip == backend tip"
RPC_TIP=$(b3chain-cli -chain=test \
    -conf=/etc/b3chain/b3chain.conf \
    -datadir=/var/lib/b3chain/.b3chain \
    getblockcount 2>/dev/null || echo "")
HTTP_TIP=$(curl -fsS "$EXPLORER_HOST/v2/api/v1/blocks/tip/height" 2>/dev/null || echo "")
if [ -n "$RPC_TIP" ] && [ "$RPC_TIP" = "$HTTP_TIP" ]; then
    ok "tip matches: $RPC_TIP"
else
    bad "tip mismatch: rpc=$RPC_TIP backend=$HTTP_TIP"
fi

echo "==> 4. frontend index.html served"
if curl -fsS "$EXPLORER_HOST/v2/" >/tmp/v2-index.html 2>/dev/null \
   && grep -q '<title>' /tmp/v2-index.html; then
    ok "index served"
else
    bad "index not served"
fi

echo "==> 5. websocket upgrade"
# Force HTTP/1.1 — the WebSocket Upgrade protocol does not work over
# HTTP/2 (which nginx negotiates by default), so without --http1.1 the
# request is treated as a plain GET and 404s.
WS_STATUS=$(curl -s -o /dev/null -w '%{http_code}' --http1.1 \
    -H 'Connection: Upgrade' \
    -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
    -H 'Sec-WebSocket-Version: 13' \
    --max-time 5 \
    "$EXPLORER_HOST/v2/api/v1/ws" || true)
case "$WS_STATUS" in
    101|400|426) ok "ws upgrade response: $WS_STATUS" ;;
    *) bad "ws upgrade unexpected status: $WS_STATUS" ;;
esac

echo "==> 6. served HTML free of upstream brand"
if [ -f /tmp/v2-index.html ]; then
    if grep -E '\bMempool\b|mempool\.space|Mempool Goggles|Mempool Accelerator' \
            /tmp/v2-index.html >/dev/null; then
        bad "served HTML contains upstream brand string"
    else
        ok "no upstream brand string"
    fi
fi

echo
if [ "$fail" = 0 ]; then
    echo "verify: PASS"
    exit 0
else
    echo "verify: FAIL" >&2
    exit 1
fi
