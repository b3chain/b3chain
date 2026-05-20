#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Idempotent injector for audit-page tutorials.

Reads markdown files under contrib/testing/audit/tutorials/ and weaves
each one into the corresponding HTML page in
b3chain-website/testing/audit-*.html (and 51-attack.html).

Idempotent: re-running with unchanged markdown produces zero diff.
Non-destructive: only touches the region between two HTML comments
(`<!-- TUTORIAL -->` / `<!-- /TUTORIAL -->`); if those markers don't
exist, inserts a `<section class="tutorial">` block just before the
final `<div class="page-nav">` / `</div></div>` closing structure.

Usage:
    python3 inject-tutorial.py [--website ../b3chain-website] [--only NAME] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Tutorials defined here; map the markdown filename (without .md) to the
# HTML page basename (without .html).
TUTORIAL_TO_PAGE = {
    "audit-supply-cap":         "audit-supply-cap",
    # B3PoW-Scratch v1.1 rename: the tutorial moved to
    # `audit-b3pow-isolation.md` but the website page kept its
    # historical filename so external links resolve.
    "audit-b3pow-isolation":    "audit-pow-isolation",
    "audit-network-isolation":  "audit-network-isolation",
    "audit-address-rejection":  "audit-address-rejection",
    "audit-simd-blake3":        "audit-simd-blake3",
    "audit-rebranding":         "audit-rebranding",
    "audit-hd-coin-type":       "audit-hd-coin-type",
    "audit-51-attack":          "51-attack",
}


def md_to_html(md: str) -> str:
    """
    Tiny markdown -> HTML converter, just enough for our tutorial format.
    Handles: H1/H2/H3, paragraphs, bullet lists, ordered lists, code blocks,
    inline `code`, and **bold** / *emph*. Not a general-purpose converter.
    """
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            block = "\n".join(lines[i+1:j])
            out.append("<pre>" + _escape(block) + "</pre>")
            i = j + 1
            continue
        if line.startswith("# "):
            out.append(f"<h2>{_inline(line[2:].strip())}</h2>")
            i += 1
            continue
        if line.startswith("## "):
            out.append(f"<h3>{_inline(line[3:].strip())}</h3>")
            i += 1
            continue
        if line.startswith("### "):
            out.append(f"<h4>{_inline(line[4:].strip())}</h4>")
            i += 1
            continue
        if re.match(r"^\s*[-*]\s", line):
            j = i
            items = []
            while j < len(lines) and re.match(r"^\s*[-*]\s", lines[j]):
                items.append(re.sub(r"^\s*[-*]\s", "", lines[j]))
                j += 1
            out.append("<ul>")
            for it in items:
                out.append(f"  <li>{_inline(it)}</li>")
            out.append("</ul>")
            i = j
            continue
        if re.match(r"^\s*\d+\.\s", line):
            j = i
            items = []
            while j < len(lines) and re.match(r"^\s*\d+\.\s", lines[j]):
                items.append(re.sub(r"^\s*\d+\.\s", "", lines[j]))
                j += 1
            out.append("<ol>")
            for it in items:
                out.append(f"  <li>{_inline(it)}</li>")
            out.append("</ol>")
            i = j
            continue
        if line.strip() == "":
            i += 1
            continue
        # paragraph (consume until blank line). Stop on a structural line
        # (heading, fence, list-item) — but only when those are full
        # list/heading markers, NOT when the line just *starts* with `*`
        # (which would also match inline emphasis like `*format*`).
        j = i
        para = []
        while j < len(lines):
            cur = lines[j]
            if cur.strip() == "":
                break
            if cur.startswith("#") or cur.startswith("```"):
                break
            if re.match(r"^\s*[-*]\s", cur):
                break
            if re.match(r"^\s*\d+\.\s", cur):
                break
            para.append(cur)
            j += 1
        # Defensive: always advance, even if `cur` was a structural line we
        # somehow reached without a paragraph body — this prevents the
        # infinite loop seen on lines starting with `*emph*`.
        if j == i:
            j = i + 1
            para.append(line)
        out.append(f"<p>{_inline(' '.join(para))}</p>")
        i = j
    return "\n".join(out)


_CODE_RE   = re.compile(r"`([^`\n]+?)`")
_STRONG_RE = re.compile(r"\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*")
_EMPH_RE   = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\w)")
_LINK_RE   = re.compile(r"\[([^\]\n]{1,200})\]\(([^)\s]{1,500})\)")


def _inline(text: str) -> str:
    text = _escape(text)
    text = _CODE_RE.sub(lambda m: "<code>" + m.group(1) + "</code>", text)
    text = _STRONG_RE.sub(lambda m: "<strong>" + m.group(1) + "</strong>", text)
    text = _EMPH_RE.sub(lambda m: "<em>" + m.group(1) + "</em>", text)
    text = _LINK_RE.sub(
        lambda m: '<a href="' + m.group(2) + '">' + m.group(1) + "</a>", text)
    return text


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


# Marker constants.
START = "<!-- TUTORIAL -->"
END   = "<!-- /TUTORIAL -->"


def inject(html: str, tutorial_html: str) -> str:
    block = (
        f"{START}\n"
        f'<section class="tutorial">\n'
        f"{tutorial_html}\n"
        f"</section>\n"
        f"{END}"
    )
    if START in html and END in html:
        return re.sub(
            re.escape(START) + r".*?" + re.escape(END),
            lambda m: block,
            html,
            count=1,
            flags=re.DOTALL,
        )
    # Insert before the page-nav (or footer) if marker absent.
    # Use callable replacement to avoid backref expansion of `\1`, `\g`, etc.
    # in `block` itself.
    def _replace_with_block(match: "re.Match") -> str:
        return block + "\n\n" + match.group(0)

    pivot_re = re.compile(r'<div class="page-nav">', re.IGNORECASE)
    if pivot_re.search(html):
        return pivot_re.sub(_replace_with_block, html, count=1)
    pivot_re = re.compile(r"<footer", re.IGNORECASE)
    if pivot_re.search(html):
        return pivot_re.sub(_replace_with_block, html, count=1)
    # Fallback: append before </body>.
    return html.replace("</body>", block + "\n</body>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--website", default=None,
                    help="path to b3chain-website (default: ../b3chain-website)")
    ap.add_argument("--only", default=None,
                    help="inject only into this tutorial id (e.g. audit-supply-cap)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be written, don't modify files")
    args = ap.parse_args()

    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent.parent
    if args.website:
        web = Path(args.website).resolve()
    else:
        web = (repo_root / ".." / "b3chain-website").resolve()
        if not web.is_dir():
            web = (repo_root.parent / "b3chain-website").resolve()
    if not web.is_dir():
        print(f"error: website not found at {web}", file=sys.stderr)
        return 2

    tutorials_dir = here.parent / "tutorials"
    pages_dir = web / "testing"

    n_changed = 0
    n_unchanged = 0
    n_missing = 0

    for tut_id, page_id in TUTORIAL_TO_PAGE.items():
        if args.only and args.only != tut_id:
            continue
        md_path = tutorials_dir / f"{tut_id}.md"
        page_path = pages_dir / f"{page_id}.html"
        if not md_path.is_file():
            print(f"  missing tutorial: {md_path}")
            n_missing += 1
            continue
        if not page_path.is_file():
            print(f"  missing page: {page_path}")
            n_missing += 1
            continue
        md_text = md_path.read_text(encoding="utf-8")
        # Skip the level-1 heading (we already have an <h1> on the page);
        # render starting from the first '## ' instead.
        body = re.sub(r"^# .*?\n", "", md_text, count=1)
        html = md_to_html(body)

        page_text = page_path.read_text(encoding="utf-8")
        new_text = inject(page_text, html)
        if new_text == page_text:
            print(f"  unchanged: {page_path.relative_to(web)}")
            n_unchanged += 1
            continue
        if args.dry_run:
            print(f"  would update: {page_path.relative_to(web)}")
        else:
            page_path.write_text(new_text, encoding="utf-8")
            print(f"  updated: {page_path.relative_to(web)}")
        n_changed += 1

    print(f"\nInjected: {n_changed} changed, {n_unchanged} unchanged, {n_missing} missing")
    return 0 if n_missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
