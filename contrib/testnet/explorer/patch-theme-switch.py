#!/usr/bin/env python3
"""Make the explorer theme buttons change the painted theme.

btc-rpc-explorer swaps a stylesheet in activateTheme(), but the overlay
CSS forces one palette. Tag <html> with data-b3-theme and keep that
attribute in sync so the overlay can switch tokens.
"""
import os
import sys
import base64
import hashlib
import re
from pathlib import Path

EXP = Path(os.environ.get("EXP_DIR", "/var/lib/b3chain-explorer"))
ROOT = EXP / "node_modules/btc-rpc-explorer"
LAYOUT = ROOT / "views/layout.pug"
SITE = ROOT / "public/js/site.js"
INTEGRITY = ROOT / "app/resourceIntegrityHashes.js"
SHARED = ROOT / "views/includes/shared-mixins.pug"
MARKER = "B3Chain-theme-attr"


def patch_layout(text: str) -> str:
    old = 'html(lang="en")'
    new = 'html(lang="en", data-b3-theme=(userSettings.uiTheme || "dark"))'
    if "data-b3-theme" not in text:
        if old not in text:
            raise SystemExit("layout.pug: html tag not found")
        text = text.replace(old, new, 1)

    # Let the handler own both painting and persistence; no partial inline switch.
    old_click = "onclick=`document.documentElement.setAttribute('data-b3-theme','${themeName}'); activateTheme('${themeName}'); return false;`"
    text = text.replace(old_click, "onclick=`activateTheme('${themeName}'); return false;`")
    if "onclick=`activateTheme('${themeName}'); return false;`" not in text:
        raise SystemExit("layout.pug: theme button onclick not found")
    theme_id = 'id=`theme-toggler-${themeName}`'
    if 'aria-label=`${themeName} theme`' not in text:
        text = text.replace(theme_id, theme_id + ', role="button", aria-label=`${themeName} theme`, aria-pressed=(userSettings.uiTheme == themeName ? "true" : "false")', 1)

    old_css = 'link(rel="stylesheet", href=assetUrl("./css/b3-theme.css"))'
    new_css = 'link(rel="stylesheet", href="./css/b3-theme.css?v=20260926h")'
    text = re.sub(r'b3-theme\.css\?v=[^"\s]+', 'b3-theme.css?v=20260926h', text)
    if "b3-theme.css?v=20260926h" not in text:
        if old_css not in text:
            raise SystemExit("layout.pug: b3-theme.css link not found")
        text = text.replace(old_css, new_css, 1)
    return text


def patch_site(text: str) -> str:
    needle = '\t$(`#${themeName}-theme-link-tag`).attr("rel", "stylesheet");\n'
    insert = needle + '\tdocument.documentElement.setAttribute("data-b3-theme", themeName); // B3Chain-theme-attr\n'
    if 'setAttribute("data-b3-theme"' not in text:
        if text.count(needle) != 1:
            raise SystemExit("site.js: activateTheme stylesheet line not unique")
        text = text.replace(needle, insert, 1)
    active = '$(`#theme-toggler-${themeName}`).addClass(activeClass).removeClass(inactiveClass);'
    if '// B3Chain-theme-accessibility' not in text:
        if active not in text:
            raise SystemExit("site.js: theme indicator not found")
        text = text.replace(active, active + '\n\tthemeNames.forEach(x => document.getElementById(`theme-toggler-${x}`)?.setAttribute("aria-pressed", String(x === themeName))); // B3Chain-theme-accessibility', 1)
    return text


def patch_integrity(text: str, site_bytes: bytes) -> str:
    digest = "sha384-" + base64.b64encode(hashlib.sha384(site_bytes).digest()).decode("ascii")
    updated, count = re.subn(r'("site\.js"\s*:\s*")[^"]+(")', lambda m: m[1] + digest + m[2], text)
    if count != 1:
        raise SystemExit("integrity manifest: site.js entry not unique")
    return updated


def patch_shared(text: str, site_bytes: bytes) -> str:
    version = hashlib.sha256(site_bytes).hexdigest()[:16]
    updated, count = re.subn(
        r'script\(src=(?:assetUrl\(`\./js/site\.js`\)|"\./js/site\.js\?v=[^"]+")',
        'script(src="./js/site.js?v=' + version + '"', text,
    )
    if count != 1:
        raise SystemExit("shared-mixins.pug: site.js include not unique")
    return updated


def patch_quote_layout(text: str) -> str:
    if 'section.b3-footer-quote' in text:
        return text
    pattern = r'(?m)^([ \t]*)iframe\(id="quoteIframe"[^\n]+$'
    def inline(match):
        indent = match[1]
        return (indent + '- var b3Footer = b3FooterQuote();\n'
                + indent + 'if (b3Footer)\n'
                + indent + '\tsection.b3-footer-quote(aria-label="Quote")\n'
                + indent + '\t\t+quote(b3Footer.quote, b3Footer.index, {fontSize: 4, align: "center", includeQuotes: true})')
    updated, count = re.subn(pattern, inline, text)
    if count != 1:
        raise SystemExit("layout.pug: quote iframe not unique")
    return updated


def main() -> int:
    # Validate every input before writing any output. Hash the exact LF bytes written.
    updates = {}
    for path, fn in ((LAYOUT, patch_layout), (SITE, patch_site)):
        if not path.is_file():
            print(f"missing {path}", file=sys.stderr)
            return 1
        original = path.read_text(encoding="utf-8")
        updated = fn(original)
        updates[path] = updated
    if not INTEGRITY.is_file():
        raise SystemExit(f"missing {INTEGRITY}")
    updates[INTEGRITY] = patch_integrity(INTEGRITY.read_text(encoding="utf-8"), updates[SITE].encode("utf-8"))
    updates[SHARED] = patch_shared(SHARED.read_text(encoding="utf-8"), updates[SITE].encode("utf-8"))
    css_version = hashlib.sha256((ROOT / "public/css/b3-theme.css").read_bytes()).hexdigest()[:16]
    updates[LAYOUT] = patch_quote_layout(updates[LAYOUT]).replace('b3-theme.css?v=20260926h', 'b3-theme.css?v=' + css_version)
    for path, updated in updates.items():
        if path.read_bytes() != updated.encode("utf-8"):
            path.write_bytes(updated.encode("utf-8"))
            print(f"patched {path.name}")
        else:
            print(f"already patched {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
