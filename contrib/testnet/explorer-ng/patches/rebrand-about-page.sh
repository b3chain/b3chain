#!/usr/bin/env bash
#
# B3Chain about/legal page rebrand.
#
# strip-upstream-brand.sh deletes mempool-promo*, mempool-logo-bigger*,
# mempool-holdings* assets but the About page still references them and
# calls upstream-only APIs (sponsors/donations/translators/contributors).
# This patch fixes logos, removes upstream marketing blocks, stubs frontend
# observables, and makes backend about.routes return empty JSON when no
# upstream data server is configured.
#
# Run after rebrand-footer.sh. Idempotent.
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
cd "$ROOT"
MARKER='B3CHAIN_ABOUT_REBRAND'

if [ ! -f frontend/package.json ]; then
    echo "rebrand-about-page: '$ROOT' does not look like explorer-ng" >&2
    exit 2
fi

LOGO='/resources/b3chain-explorer-ng-logo.svg'

about_html() {
    local F="$ROOT/frontend/src/app/components/about/about.component.html"
    [ -f "$F" ] || return 0
    if grep -q "$MARKER" "$F" 2>/dev/null; then
        echo "rebrand-about-page: about.component.html already patched"
        return 0
    fi

    python3 - "$F" "$LOGO" "$MARKER" <<'PY'
import re, sys
path, logo, marker = sys.argv[1:4]
text = open(path, encoding='utf-8').read()

# Logo (light/dark blocks -> single SVG)
text = re.sub(
    r'@if \(isLightMode\) \{\s*\n\s*<img class="logo" src="/resources/mempool-logo-bigger-light\.png" />\s*\n\s*\} @else \{\s*\n\s*<img class="logo" src="/resources/mempool-logo-bigger\.png" />\s*\n\s*\}',
    f'<img class="logo b3chain-about-logo" src="{logo}" alt="B3Chain Live Explorer" />',
    text,
    count=1,
)

# Upstream promo video (assets deleted by strip-upstream-brand)
text = re.sub(r'\n  <video #promoVideo.*?</video>\n', '\n', text, count=1, flags=re.S)

# Child sponsor widget + enterprise sponsor wall
text = re.sub(r'\n  <ng-container>\s*\n    <app-about-sponsors></app-about-sponsors>\s*\n  </ng-container>\n', '\n', text, count=1)
text = re.sub(
    r'\n  <div class="enterprise-sponsor" id="enterprise-sponsors">.*?(?=\n  <div class="community-integrations-sponsor")',
    '\n',
    text,
    count=1,
    flags=re.S,
)

# Community / OG sponsors (remote APIs)
text = re.sub(
    r'\n  <ng-container>\s*\n    <div \*ngIf="profiles\$ \| async as profiles".*?(?=\n  <div class="community-integrations-sponsor")',
    '\n',
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r'\n  <div class="community-sponsor" style="margin-bottom: 68px">\s*\n    <h3 i18n="about\.sponsors\.withHeart">OG Sponsors.*?</div>\n',
    '\n',
    text,
    count=1,
    flags=re.S,
)

# Translators + contributors (remote APIs)
text = re.sub(
    r'\n  <ng-container \*ngIf="translators\$ \| async \| keyvalue as translators else loadingSponsors">.*?(?=\n  <div class="managers")',
    '\n',
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r'\n  <ng-container \*ngIf="allContributors\$ \| async as contributors else loadingSponsors">.*?(?=\n  <div class="managers")',
    '\n',
    text,
    count=1,
    flags=re.S,
)

# "Managed By" upstream holdings logo (asset deleted)
text = re.sub(
    r'\n    <br>\s*\n    <br>\s*\n    <h3 i18n="about\.managed-by">Managed By</h3>\s*\n    <div class="wrapper">\s*\n        <a href="https://mempool\.holdings".*?</div>\n',
    '\n    <br>\n    <h3>Project</h3>\n    <div class="wrapper">\n        <a href="https://b3chain.org/" target="_blank" rel="noopener" title="B3Chain">\n          <span>B3Chain</span>\n        </a>\n    </div>\n',
    text,
    count=1,
    flags=re.S,
)

# About blurb: B3Chain testnet copy
text = text.replace(
    'Our mempool and blockchain explorer for the Bitcoin community, focusing on the transaction fee market and multi-layer ecosystem, completely self-hosted without any trusted third-parties.',
    'Block explorer for the B3Chain testnet: blocks, transactions, mempool charts, and network status — self-hosted on explorer.b3chain.org.',
    1,
)

if marker not in text:
    text = text.replace(
        '<div class="container-xl about-page">',
        f'<!-- {marker} -->\n<div class="container-xl about-page">',
        1,
    )

open(path, 'w', encoding='utf-8').write(text)
print(f"    edit: {path}")
PY
}

about_ts() {
    local F="$ROOT/frontend/src/app/components/about/about.component.ts"
    [ -f "$F" ] || return 0
    if grep -q "$MARKER" "$F" 2>/dev/null; then
        echo "rebrand-about-page: about.component.ts already patched"
        return 0
    fi

    python3 - "$F" "$MARKER" <<'PY'
import re, sys
path, marker = sys.argv[1:3]
text = open(path, encoding='utf-8').read()

if "from 'rxjs'" in text and ' of,' not in text and ', of,' not in text:
    text = text.replace(
        "import { Observable, Subscription } from 'rxjs';",
        "import { Observable, of, Subscription } from 'rxjs';",
        1,
    )

text = re.sub(
    r"    this\.profiles\$ = this\.apiService\.getAboutPageProfiles\$\(\)\.pipe\([\s\S]*?      share\(\),\n    \);",
    f"    // {marker}: no upstream sponsor feeds on self-hosted B3Chain explorer\n    this.profiles$ = of({{ whales: [], chads: [] }});",
    text,
    count=1,
)

text = re.sub(
    r"    this\.translators\$ = this\.apiService\.getTranslators\$\(\)\n      \.pipe\([\s\S]*?      \);",
    "    this.translators$ = of({});",
    text,
    count=1,
)

text = re.sub(
    r"    this\.ogs\$ = this\.apiService\.getOgs\$\(\);",
    "    this.ogs$ = of([]);",
    text,
    count=1,
)

text = re.sub(
    r"    this\.allContributors\$ = this\.apiService\.getContributor\$\(\)\.pipe\([\s\S]*?    \);",
    "    this.allContributors$ = of({ regular: [], core: [] });",
    text,
    count=1,
)

open(path, 'w', encoding='utf-8').write(text)
print(f"    edit: {path}")
PY
}

legal_logos() {
    local logo_img="<img src=\"$LOGO\" alt=\"B3Chain Live Explorer\" class=\"b3chain-about-logo\" style=\"width:250px;height:auto;max-height:63px;\" />"
    for F in \
        frontend/src/app/components/terms-of-service/terms-of-service.component.html \
        frontend/src/app/components/privacy-policy/privacy-policy.component.html; do
        [ -f "$ROOT/$F" ] || continue
        if grep -q "$MARKER" "$ROOT/$F" 2>/dev/null; then
            continue
        fi
        perl -0777 -i -pe "
            s|<div class=\"logo\">\s*@if \(isLightMode\) \{.*?</div>|<!-- $MARKER -->\n    <div class=\"logo\">\n      $logo_img\n    </div>|s;
        " -- "$ROOT/$F"
        echo "    edit: $F"
    done

    F=frontend/src/app/components/trademark-policy/trademark-policy.component.html
    [ -f "$ROOT/$F" ] || return 0
    if grep -q "$MARKER" "$ROOT/$F" 2>/dev/null; then
        return 0
    fi
    perl -i -pe "
        s|src=\"/resources/mempool-logo-bigger\.png\"|src=\"$LOGO\"|g;
        s|src=\"/resources/mempool-space-logo-bigger\.png\"|src=\"$LOGO\"|g;
        s|src=\"/resources/mempool-space-logo-horizontal\.png\"|src=\"$LOGO\"|g;
    " -- "$ROOT/$F"
    sed -i "1i<!-- $MARKER -->" "$ROOT/$F" 2>/dev/null || \
        perl -i -pe "s|^|<!-- $MARKER -->\n| unless \$.==1 && /$MARKER/;" -- "$ROOT/$F"
    echo "    edit: $F"
}

about_scss() {
    local F="$ROOT/frontend/src/app/components/about/about.component.scss"
    [ -f "$F" ] || return 0
    if grep -q 'b3chain-about-logo' "$F" 2>/dev/null; then
        return 0
    fi
    cat >>"$F" <<'SCSS'

.b3chain-about-logo {
  width: 280px;
  max-width: 90%;
  height: auto;
}
SCSS
    echo "    edit: $F (b3chain-about-logo)"
}

about_routes() {
    local F="$ROOT/backend/src/api/about.routes.ts"
    [ -f "$F" ] || return 0
    if grep -q "$MARKER" "$F" 2>/dev/null; then
        echo "rebrand-about-page: about.routes.ts already patched"
        return 0
    fi

    python3 - "$F" "$MARKER" <<'PY'
import sys
path, marker = sys.argv[1:3]
text = open(path, encoding='utf-8').read()

helper = '''
// ''' + marker + ''': self-hosted B3Chain has no upstream data servers
function b3chainAboutUpstreamConfigured(): boolean {
  const api = (config.EXTERNAL_DATA_SERVER?.MEMPOOL_API || '').trim();
  const services = (config.MEMPOOL_SERVICES?.API || '').trim();
  return api.length > 0 || services.length > 0;
}
'''

if helper.strip() not in text:
    text = text.replace(
        'class AboutRoutes {',
        helper + '\nclass AboutRoutes {',
        1,
    )

replacements = [
    (
        ".get(config.MEMPOOL.API_URL_PREFIX + 'donations', async (req, res) => {",
        ".get(config.MEMPOOL.API_URL_PREFIX + 'donations', async (req, res) => {\n"
        "        if (!b3chainAboutUpstreamConfigured()) {\n"
        "          return res.json([]);\n"
        "        }",
    ),
    (
        ".get(config.MEMPOOL.API_URL_PREFIX + 'contributors', async (req, res) => {",
        ".get(config.MEMPOOL.API_URL_PREFIX + 'contributors', async (req, res) => {\n"
        "        if (!b3chainAboutUpstreamConfigured()) {\n"
        "          return res.json([]);\n"
        "        }",
    ),
    (
        ".get(config.MEMPOOL.API_URL_PREFIX + 'translators', async (req, res) => {",
        ".get(config.MEMPOOL.API_URL_PREFIX + 'translators', async (req, res) => {\n"
        "        if (!b3chainAboutUpstreamConfigured()) {\n"
        "          return res.json({});\n"
        "        }",
    ),
    (
        ".get(config.MEMPOOL.API_URL_PREFIX + 'services/sponsors', async (req, res) => {",
        ".get(config.MEMPOOL.API_URL_PREFIX + 'services/sponsors', async (req, res) => {\n"
        "        if (!b3chainAboutUpstreamConfigured()) {\n"
        "          return res.json([]);\n"
        "        }",
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"missing expected route block in {path}: {old!r}")
    text = text.replace(old, new, 1)

open(path, 'w', encoding='utf-8').write(text)
print(f"    edit: {path}")
PY
}

echo "==> rebrand-about-page (logos, upstream blocks, API stubs)"
about_html
about_ts
legal_logos
about_scss
about_routes

mkdir -p .b3chain
date -u +"%Y-%m-%dT%H:%M:%SZ" > .b3chain/rebrand-about-page.last-run.txt
echo "==> rebrand-about-page finished at $(cat .b3chain/rebrand-about-page.last-run.txt)"
