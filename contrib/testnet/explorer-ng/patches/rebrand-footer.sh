#!/usr/bin/env bash
#
# B3Chain footer rebrand (global-footer.component.html).
# Run after replace-header-logo.sh. Idempotent.
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
F="$ROOT/frontend/src/app/shared/components/global-footer/global-footer.component.html"

if [ ! -f "$F" ]; then
    echo "rebrand-footer: skip ($F missing)" >&2
    exit 0
fi

if grep -qE '\*ngIf="false"[a-zA-Z]' "$F" 2>/dev/null; then
    echo "rebrand-footer: corrupted footer detected, restoring from git"
    git -C "$ROOT" checkout -- "$F"
fi

if grep -q '<footer <!--' "$F" 2>/dev/null; then
    perl -i -pe 's#<footer <!-- B3CHAIN_FOOTER_REBRAND --> #<!-- B3CHAIN_FOOTER_REBRAND -->\n<footer #g' "$F"
    echo "rebrand-footer: fixed invalid footer marker placement"
fi

if grep -q 'B3CHAIN_FOOTER_REBRAND' "$F" && grep -q 'Explore the B3Chain testnet' "$F"; then
    echo "rebrand-footer: already patched"
    exit 0
fi

perl -i -pe '
    s#^<footer #<!-- B3CHAIN_FOOTER_REBRAND -->\n<footer #;

    s#<ng-container i18n="shared\.be-your-own-explorer">Be your own explorer</ng-container>#<ng-container i18n="shared.be-your-own-explorer">Explore the B3Chain testnet in real time</ng-container>#g;

    s#fragment="what-is-a-mempool"#fragment="what-is-a-block-explorer"#g;
    s#fragment="what-is-a-mempool-explorer"#fragment="what-is-a-block-explorer"#g;
    s#i18n="faq\.what-is-a-mempool">What is a mempool\?#i18n="faq.what-is-a-block-explorer">What is the transaction pool?#g;
    s#i18n="faq\.what-is-a-mempool-exlorer">What is a mempool explorer\?#i18n="faq.what-is-a-block-explorer">What is a block explorer?#g;

    s#\*ngIf="\(officialMempoolSpace \|\| \(env\.BASE_MODULE === '\''mempool'\''\)\) && \(currentNetwork !== '\'''\''\) && \(currentNetwork !== '\''mainnet'\''\)"#*ngIf="false"#g;
    s#\*ngIf="\(officialMempoolSpace \|\| \(env\.BASE_MODULE === '\''mempool'\''\)\) && \(currentNetwork !== '\''testnet'\''\) && env\.TESTNET_ENABLED"#*ngIf="false"#g;
    s#\*ngIf="\(officialMempoolSpace \|\| \(env\.BASE_MODULE === '\''mempool'\''\)\) && \(currentNetwork !== '\''testnet4'\''\) && env\.TESTNET4_ENABLED"#*ngIf="false"#g;
    s#\*ngIf="\(officialMempoolSpace \|\| \(env\.BASE_MODULE === '\''mempool'\''\)\) && \(currentNetwork !== '\''signet'\''\) && env\.SIGNET_ENABLED"#*ngIf="false"#g;
    s#\*ngIf="\(officialMempoolSpace \|\| \(env\.BASE_MODULE === '\''mempool'\''\)\) && \(currentNetwork !== '\''regtest'\''\) && env\.REGTEST_ENABLED"#*ngIf="false"#g;
    s#i18n="footer\.testnet3-explorer">Testnet3 Explorer#i18n="footer.testnet3-explorer">B3Chain Testnet Explorer#g;
    s#i18n="footer\.mainnet-explorer">Mainnet Explorer#i18n="footer.mainnet-explorer">Mainnet Explorer (not available)#g;
    s#>Clock \(Mempool\)<#>Clock (Tx Pool)<#g;
    s#/clock/mempool/#/clock/mempool/#g;

    s#<a href="https://x\.com/mempool"#<a hidden *ngIf="false" href="https://x.com/mempool"#g;
    s#<a href="nostr:#<a hidden *ngIf="false" href="nostr:#g;
    s#<a href="https://primal\.net/mempool"#<a hidden *ngIf="false" href="https://primal.net/mempool"#g;
    s#<a href="https://youtube\.com/@mempool"#<a hidden *ngIf="false" href="https://youtube.com/@mempool"#g;
    s#<a href="https://bitcointv\.com/c/mempool/videos"#<a hidden *ngIf="false" href="https://bitcointv.com/c/mempool/videos"#g;
    s#<a href="https://mempool\.chat"#<a hidden *ngIf="false" href="https://mempool.chat"#g;
' "$F"

if ! grep -q 'b3chain.org' "$F"; then
    perl -i -0777 -pe '
        s#(github\.com/b3chain/b3chain[^<]*</a>\n)#$1        <a href="https://b3chain.org" target="_blank" rel="noopener noreferrer" aria-label="B3Chain website">b3chain.org</a>\n#s;
    ' "$F" 2>/dev/null || true
fi

echo "rebrand-footer: patched $F"
mkdir -p "$ROOT/.b3chain"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$ROOT/.b3chain/rebrand-footer.last-run.txt"
