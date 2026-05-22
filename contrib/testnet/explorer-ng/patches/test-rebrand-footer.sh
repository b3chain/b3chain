#!/usr/bin/env bash
set -euo pipefail
SCRIPT="$(cd "$(dirname "$0")" && pwd)/rebrand-footer.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
F="$TMP/frontend/src/app/shared/components/global-footer/global-footer.component.html"
mkdir -p "$(dirname "$F")"

# Test 1: corrupted inline marker
cat > "$F" <<'EOF'
<footer <!-- B3CHAIN_FOOTER_REBRAND --> [class]="{'services': isServicesPage}">
  <div class="container-fluid">
    <ng-container i18n="shared.be-your-own-explorer">Be your own explorer</ng-container>
  </div>
</footer>
EOF
bash "$SCRIPT" "$TMP"
head -3 "$F"
grep -q '<footer <!--' "$F" && { echo "FAIL: still has inline marker"; exit 1; }
grep -q 'Explore the B3Chain testnet' "$F"
grep -q '^<!-- B3CHAIN_FOOTER_REBRAND' "$F" || grep -q '^[[:space:]]*<!-- B3CHAIN_FOOTER_REBRAND' "$F"
echo "test1 OK"

# Test 2: idempotent re-run
out=$(bash "$SCRIPT" "$TMP")
echo "$out" | grep -q 'already patched'
echo "test2 OK"

echo "all tests passed"
