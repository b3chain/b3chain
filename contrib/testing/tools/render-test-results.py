#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Render b3chain-website/testing/test-results.html from a corpus run.

Reads a ``summary.json`` produced by ``run-full-corpus.sh`` and rewrites
the corpus-results table in ``b3chain-website/testing/test-results.html``
in-place.  The other sections (Phase 11 table, performance markers,
reproduction snippet) are left untouched so editorial copy stays under
human control.

Usage:
    python3 render-test-results.py <summary.json> [<test-results.html>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARKER_BEGIN = "<!-- BEGIN auto-generated corpus rows -->"
MARKER_END = "<!-- END auto-generated corpus rows -->"

# Friendly descriptions per id, applied when summary.json's `note` is
# blank.  Keep in sync with run-full-corpus.sh's ids.
DEFAULT_DESCRIPTIONS = {
    "cpp_pow":           "C++ pow_tests (b3chain-specific cases)",
    "cpp_b3pow_scratch": "C++ b3pow_scratch_tests",
    "cpp_b3pow_cache":   "C++ b3pow_cache_tests",
    "cpp_crypto":        "C++ crypto_tests",
    "cpp_validation":    "C++ validation_tests",
    "phase11_master":    "Phase 11 master audit (run-all.sh)",
    "verify_b3pow":      "B3PoW reference verifier (offline vectors)",
    "feature_b3pow":     "Functional test feature_b3pow.py",
    "stratum_pool":      "Stratum pool audit",
    "stratum_v2":        "Stratum V2 audit",
    "bitcoin_inh":       "Bitcoin inheritance audit",
    "compare_all":       "BLAKE3 vs SHA-256d compare suite",
}


def _badge(result: str) -> str:
    label = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}.get(result, result)
    cls = {"PASS": "badge badge-pass",
           "FAIL": "badge badge-fail",
           "SKIP": "badge"}.get(result, "badge")
    return f'<span class="{cls}">{label}</span>'


def _fmt_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms} ms"
    if ms < 60_000:
        return f"{ms/1000:.1f} s"
    minutes = ms // 60_000
    seconds = (ms % 60_000) // 1000
    if minutes < 60:
        return f"{minutes} m {seconds:02d} s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours} h {minutes:02d} m"


def render_rows(entries: list[dict]) -> str:
    rows: list[str] = []
    for e in entries:
        note = e.get("note") or DEFAULT_DESCRIPTIONS.get(e["id"], "")
        rows.append(
            f'      <tr><td>{e["id"]}</td>'
            f'<td>{DEFAULT_DESCRIPTIONS.get(e["id"], e["script"])}</td>'
            f'<td>{_badge(e["result"])}</td>'
            f'<td>{_fmt_duration(int(e["duration_ms"]))}</td>'
            f'<td>{note}</td></tr>'
        )
    return "\n".join(rows)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("summary", help="path to summary.json")
    p.add_argument("html", nargs="?",
                   default="b3chain-website/testing/test-results.html")
    args = p.parse_args()

    summary_path = Path(args.summary)
    if not summary_path.is_file():
        print(f"error: {summary_path} not found", file=sys.stderr)
        return 2

    entries = json.loads(summary_path.read_text(encoding="utf-8"))

    html_path = Path(args.html)
    html = html_path.read_text(encoding="utf-8")

    if MARKER_BEGIN not in html or MARKER_END not in html:
        print(f"error: {html_path} missing auto-generated markers "
              f"({MARKER_BEGIN!r} / {MARKER_END!r}); aborting "
              "(add them once around the corpus <tbody> rows to enable "
              "auto-rendering).", file=sys.stderr)
        return 3

    rows = render_rows(entries)
    new_html = re.sub(
        re.escape(MARKER_BEGIN) + r"[\s\S]*?" + re.escape(MARKER_END),
        f"{MARKER_BEGIN}\n{rows}\n      {MARKER_END}",
        html,
        count=1,
    )

    html_path.write_text(new_html, encoding="utf-8")
    print(f"updated {html_path} with {len(entries)} rows from "
          f"{summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
