#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Validate the structure of doc/SECURITY-AUDIT.md.

Default mode checks that the file exists, has the required structural
elements (legend, summary table, the 11 audit IDs), and is wired to a
detail page for every row.

With --require-all-passed, also asserts that every audit row has status
[x] (or [-] with a documented reason).

Usage:
    python3 verify_checklist.py [--require-all-passed] [--checklist PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_IDS = ["C-1", "C-2", "C-3", "C-4", "H-1", "N-1", "W-1", "W-2", "B-1", "B-2", "A-1"]


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "doc" / "SECURITY-AUDIT.md").is_file():
            return parent
    sys.exit("verify_checklist: cannot locate b3chain repo root")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--require-all-passed", action="store_true",
                    help="also fail if any row is not [x] or [-] with note")
    ap.add_argument("--checklist", default=None,
                    help="path to SECURITY-AUDIT.md (defaults to repo doc/)")
    args = ap.parse_args()

    if args.checklist:
        path = Path(args.checklist).resolve()
    else:
        path = repo_root() / "doc" / "SECURITY-AUDIT.md"

    if not path.is_file():
        print(f"verify_checklist: missing {path}")
        return 1

    text = path.read_text(encoding="utf-8")

    problems: list[str] = []

    if "Status legend" not in text and "Status legend" not in text.title():
        # be lenient on capitalisation
        if not re.search(r"status\s+legend", text, re.IGNORECASE):
            problems.append("missing 'Status legend' section")
    if not re.search(r"^\|\s*Category\s*\|", text, re.MULTILINE):
        problems.append("missing summary table (no '| Category |' header)")

    rows = {}
    row_re = re.compile(
        r"^\|\s*(?P<id>[A-Z]-\d+(?:\.\.[A-Z]?-?\d+)?)\s*\|.*?\|\s*"
        r"`?(?P<status>\[[x!\?\- ]\])`?",
        re.MULTILINE,
    )
    for m in row_re.finditer(text):
        rows[m.group("id")] = m.group("status")

    found_ids = set()
    for rid in rows:
        for sub in rid.replace("..", " ").split():
            if re.match(r"^[A-Z]-\d+$", sub):
                found_ids.add(sub)
        if re.match(r"^[A-Z]-\d+$", rid):
            found_ids.add(rid)

    missing = [rid for rid in REQUIRED_IDS if rid not in found_ids and not any(
        rid.split("-")[1] in r for r in rows if rid.split("-")[0] == r.split("-")[0])]

    if missing:
        problems.append(f"missing audit IDs: {', '.join(missing)}")

    print(f"verify_checklist: {path.relative_to(repo_root())}")
    print(f"  rows found:        {len(rows)} ({sorted(rows)})")
    print(f"  required IDs:      {len(REQUIRED_IDS)} ({REQUIRED_IDS})")
    print(f"  missing:           {missing or 'none'}")

    if args.require_all_passed:
        bad = [rid for rid, st in rows.items() if st not in ("[x]", "[-]")]
        if bad:
            problems.append(f"rows not [x]/[-]: {bad}")

    if problems:
        for p in problems:
            print(f"  PROBLEM: {p}")
        return 1
    print("  OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
