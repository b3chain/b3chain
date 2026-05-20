#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
On-disk link checker for the b3chain website.

Walks every *.html under the given root (default: ../b3chain-website),
extracts every href / src attribute, and resolves it against the file
tree. External URLs (http://, https://, mailto:, etc.) are skipped.
Anchor-only references (#section) are skipped. Prints a report of
broken references and exits non-zero on any miss.

Usage:
    python3 verify_links.py [WEBSITE_ROOT]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ATTR_RE = re.compile(
    r"""(?:href|src)\s*=\s*["']([^"'#?][^"']*)["']""",
    re.IGNORECASE,
)

EXTERNAL_SCHEMES = {"http", "https", "ftp", "ftps", "mailto", "tel", "data", "javascript"}


def find_root(arg: str | None) -> Path:
    if arg:
        p = Path(arg).resolve()
        if p.is_dir():
            return p
        sys.exit(f"verify_links: not a directory: {arg}")
    here = Path(__file__).resolve()
    for guess in [
        here.parent.parent.parent.parent / "b3chain-website",  # sibling repo
        here.parent.parent.parent.parent.parent / "b3chain-website",
        Path.cwd().parent / "b3chain-website",
    ]:
        if guess.is_dir():
            return guess.resolve()
    sys.exit(
        "verify_links: could not find b3chain-website. "
        "Pass the path explicitly or set $B3CHAIN_WEBSITE."
    )


def is_external(href: str) -> bool:
    try:
        scheme = urlparse(href).scheme.lower()
    except ValueError:
        return False
    return scheme in EXTERNAL_SCHEMES


def resolve(root: Path, page: Path, href: str) -> Path:
    """Resolve an href to an on-disk path according to the website's serving rules."""
    href = unquote(href.split("#", 1)[0].split("?", 1)[0])
    if not href:
        return page
    if href.startswith("/"):
        return (root / href.lstrip("/")).resolve()
    return (page.parent / href).resolve()


def main() -> int:
    root_arg = sys.argv[1] if len(sys.argv) > 1 else None
    root = find_root(root_arg)
    pages = sorted(root.rglob("*.html"))
    if not pages:
        print(f"verify_links: no html pages found under {root}")
        return 1

    broken: list[tuple[Path, str, Path]] = []
    skipped_external = 0
    checked = 0

    for page in pages:
        try:
            text = page.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            broken.append((page, "<file read error>", Path(str(e))))
            continue
        for m in ATTR_RE.finditer(text):
            href = m.group(1).strip()
            if not href or href.startswith("#"):
                continue
            if is_external(href):
                skipped_external += 1
                continue
            target = resolve(root, page, href)
            checked += 1
            if not target.exists():
                broken.append((page, href, target))

    print(f"verify_links: scanned {len(pages)} pages, "
          f"checked {checked} on-disk refs ({skipped_external} external skipped)")
    if broken:
        print(f"verify_links: {len(broken)} broken reference(s):")
        for page, href, target in broken:
            rel_page = page.relative_to(root)
            try:
                rel_target = target.relative_to(root)
            except ValueError:
                rel_target = target
            print(f"  - {rel_page}: '{href}' -> {rel_target}")
        return 1
    print("verify_links: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
