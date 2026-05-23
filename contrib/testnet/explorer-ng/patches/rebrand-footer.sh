#!/usr/bin/env bash
#
# B3Chain footer rebrand (global-footer.component.html).
# Run after replace-header-logo.sh. Idempotent.
#
# MARKER SAFETY (2026-05-22): Never inject HTML comments inside the <footer>
# opening tag. A prior perl s#^<footer #...# that wrote the marker without a
# guaranteed newline, or a bad re-run, produced:
#   <footer <!-- B3CHAIN_FOOTER_REBRAND --> [class]=...
# which breaks Angular's template parser (NG5002 / NG6001 on GlobalFooterComponent).
# Marker insertion uses awk to print ONE comment line immediately BEFORE the
# first line that opens <footer>; validate_footer_template() fails the script
# if any corruption pattern remains.
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
F="$ROOT/frontend/src/app/shared/components/global-footer/global-footer.component.html"
MARKER='<!-- B3CHAIN_FOOTER_REBRAND v2 -->'

if [ ! -f "$F" ]; then
    echo "rebrand-footer: skip ($F missing)" >&2
    exit 0
fi

# --- repair known corruption from older marker logic -------------------------
repair_footer_marker_placement() {
    local repaired=0

    # Inline marker inside <footer ...> opening tag (fatal for ng build).
    if grep -qE '<footer[[:space:]]+<!--' "$F" 2>/dev/null; then
        perl -i -0777 -pe '
            s/<footer[[:space:]]+<!--[[:space:]]*B3CHAIN_FOOTER_REBRAND[^>]*-->[[:space:]]*/'"$MARKER"'\n<footer /g;
        ' -- "$F"
        echo "rebrand-footer: repaired inline B3CHAIN_FOOTER_REBRAND inside <footer> tag"
        repaired=1
    fi

    # Legacy fix for the exact broken pattern (space after --> before [class]).
    if grep -q '<footer <!--' "$F" 2>/dev/null; then
        perl -i -pe 's#<footer <!-- B3CHAIN_FOOTER_REBRAND --> #'"$MARKER"'\n<footer #g' -- "$F"
        echo "rebrand-footer: repaired legacy <footer <!-- ... --> placement"
        repaired=1
    fi

    return "$repaired"
}

# ngIf=false jammed against the next attribute (e.g. *ngIf="false"href) breaks TS.
if grep -qE '\*ngIf="false"[a-zA-Z]' "$F" 2>/dev/null; then
    echo "rebrand-footer: corrupted footer detected (*ngIf=false attribute glue), restoring from git"
    if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git -C "$ROOT" checkout -- "$F"
    else
        echo "rebrand-footer: ERROR: cannot restore $F (not a git checkout)" >&2
        exit 3
    fi
fi

repair_footer_marker_placement || true

footer_marker_ok() {
    grep -qE '^[[:space:]]*<!--[[:space:]]*B3CHAIN_FOOTER_REBRAND' "$F" \
        && ! grep -qE '<footer[[:space:]]+<!--' "$F"
}

validate_footer_template() {
    local err=0

    if grep -qE '<footer[[:space:]]+<!--' "$F"; then
        echo "rebrand-footer: ERROR: HTML comment inside <footer> opening tag" >&2
        err=1
    fi
    if grep -qE '<footer[^>]*<!--' "$F"; then
        echo "rebrand-footer: ERROR: comment token before closing > of <footer> tag" >&2
        err=1
    fi
    if ! grep -qE '^[[:space:]]*<footer[[:space:]]' "$F"; then
        echo "rebrand-footer: ERROR: missing well-formed <footer ...> opening line" >&2
        err=1
    fi
    if ! grep -qE '^[[:space:]]*<!--[[:space:]]*B3CHAIN_FOOTER_REBRAND' "$F"; then
        echo "rebrand-footer: ERROR: B3CHAIN_FOOTER_REBRAND marker not on its own line" >&2
        err=1
    fi
    if grep -qE '\*ngIf="false"[a-zA-Z]' "$F"; then
        echo "rebrand-footer: ERROR: *ngIf=\"false\" glued to next attribute" >&2
        err=1
    fi

    if [ "$err" -ne 0 ]; then
        echo "rebrand-footer: validation failed for $F" >&2
        return 1
    fi
    return 0
}

ensure_footer_marker_above_opening_tag() {
    if footer_marker_ok; then
        return 0
    fi

    awk -v marker="$MARKER" '
        /^[[:space:]]*<footer([[:space:]>]|\/)/ && !done {
            print marker
            done = 1
        }
        { print }
    ' "$F" > "$F.b3chain-marker.tmp"
    mv "$F.b3chain-marker.tmp" "$F"
    echo "rebrand-footer: inserted marker line above <footer>"
}

# --- idempotency: marker + B3Chain copy + logo + social links hidden ------
social_links_hidden() {
    grep -q 'class="d-none" href="https://x.com/mempool"' "$F" 2>/dev/null
}

footer_logo_ok() {
    grep -q 'b3chain-explorer-ng-logo.svg' "$F" 2>/dev/null \
        && ! grep -q 'name="mempoolSpace"' "$F" 2>/dev/null
}

if footer_marker_ok && grep -q 'Explore the B3Chain testnet' "$F" && social_links_hidden && footer_logo_ok; then
    echo "rebrand-footer: already patched"
    validate_footer_template
    exit 0
fi

if footer_marker_ok && grep -q 'Explore the B3Chain testnet' "$F" && ! footer_logo_ok; then
    echo "rebrand-footer: copy/marker ok; applying footer logo swap"
fi

if footer_marker_ok && grep -q 'Explore the B3Chain testnet' "$F" && footer_logo_ok && ! social_links_hidden; then
    echo "rebrand-footer: copy/marker ok; applying social-link hide only"
fi

# --- user-visible copy / link tweaks (never touch the <footer> opening line) ---
perl -i -pe '
    s|<app-svg-images \*ngIf="officialMempoolSpace" name="officialMempoolSpace" viewBox="0 0 500 126"></app-svg-images>|<img *ngIf="officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo" style="height:50px;width:auto;" />|g;
    s|<app-svg-images \*ngIf="!officialMempoolSpace" name="mempoolSpace" viewBox="0 0 500 126"></app-svg-images>|<img *ngIf="!officialMempoolSpace" src="/resources/b3chain-explorer-ng-logo.svg" alt="B3Chain Live Explorer" class="b3chain-logo" style="height:50px;width:auto;" />|g;

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

    s#<a href="https://x\.com/mempool"#<a class="d-none" href="https://x.com/mempool" tabindex="-1" aria-hidden="true"#g;
    s#<a href="(nostr:[^"]+)"#<a class="d-none" href="$1" tabindex="-1" aria-hidden="true"#g;
    s#<a href="https://primal\.net/mempool"#<a class="d-none" href="https://primal.net/mempool" tabindex="-1" aria-hidden="true"#g;
    s#<a href="https://youtube\.com/@mempool"#<a class="d-none" href="https://youtube.com/@mempool" tabindex="-1" aria-hidden="true"#g;
    s#<a href="https://bitcointv\.com/c/mempool/videos"#<a class="d-none" href="https://bitcointv.com/c/mempool/videos" tabindex="-1" aria-hidden="true"#g;
    s#<a href="https://mempool\.chat"#<a class="d-none" href="https://mempool.chat" tabindex="-1" aria-hidden="true"#g;
' -- "$F"

if ! grep -q 'b3chain.org' "$F"; then
    perl -i -0777 -pe '
        s#(github\.com/b3chain/b3chain[^<]*</a>\n)#$1        <a href="https://b3chain.org" target="_blank" rel="noopener noreferrer" aria-label="B3Chain website">b3chain.org</a>\n#s;
    ' -- "$F" 2>/dev/null || true
fi

ensure_footer_marker_above_opening_tag

SCSS="$ROOT/frontend/src/app/shared/components/global-footer/global-footer.component.scss"
if [ -f "$SCSS" ] && ! grep -q 'b3chain-logo' "$SCSS" 2>/dev/null; then
    cat >>"$SCSS" <<'SCSS'

.b3chain-logo {
  height: 36px;
  width: auto;
  max-width: 220px;
  object-fit: contain;
}
SCSS
    echo "rebrand-footer: added .b3chain-logo styles to global-footer.component.scss"
fi

echo "rebrand-footer: patched $F"
mkdir -p "$ROOT/.b3chain"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$ROOT/.b3chain/rebrand-footer.last-run.txt"

validate_footer_template
