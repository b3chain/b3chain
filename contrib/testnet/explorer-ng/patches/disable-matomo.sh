#!/usr/bin/env bash
# Disable Matomo analytics — B3Chain has no stats.explorer.b3chain.org host.
# Idempotent. Run from install.sh after rebrand codemods.
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
F="$ROOT/frontend/src/app/services/enterprise.service.ts"

if [ ! -f "$F" ]; then
    echo "disable-matomo: skip ($F missing)" >&2
    exit 0
fi

if grep -q 'B3Chain: analytics disabled' "$F"; then
    echo "disable-matomo: already patched"
    exit 0
fi

perl -i -0777 -pe '
    s/(insertMatomo\(siteId\?: number\): void \{\n)/$1    return; \/\/ B3Chain: analytics disabled (no stats host)\n/s
' "$F"
echo "disable-matomo: patched $F"
