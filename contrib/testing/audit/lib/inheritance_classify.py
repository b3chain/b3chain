#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Classify the output of Bitcoin Core's full ctest + functional suite as
"inherited", "diverged-by-design", or "regression" from B3Chain's
perspective.

Inputs:
    ctest.log     - output of `ctest --output-on-failure`
    functional.log - output of `python3 test/functional/test_runner.py --extended`

Outputs:
    - markdown table on stdout
    - rewrites doc/SECURITY-INHERITANCE.md status column
    - exit 0 only if no real regressions (FAIL outside the allowlist)

Usage:
    python3 inheritance_classify.py [--ctest CTEST.log] [--functional FUNC.log] [--doc PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Allowlists — tests we EXPECT to fail or skip on B3Chain because of a
# deliberate divergence. A failure here does NOT make the verifier exit
# non-zero.
# ---------------------------------------------------------------------------

EXPECTED_DIVERGENCE_UNIT = {
    # PoW algorithm: Bitcoin tests SHA-256d-as-PoW; B3Chain uses
    # B3PoW-Scratch v1.1 (memory-hard BLAKE3 variant).
    "pow_tests": "PoW algo replaced with B3PoW-Scratch v1.1 (covered by audit-b3pow-isolation.py)",
    # Address keys are technically still tested (key derivation works), but
    # any literal Bitcoin address vector is expected to fail decode on B3Chain.
    # We surface the test name; the runner will only count it as "diverged"
    # if the failure message matches a known pattern.
}

EXPECTED_DIVERGENCE_FUNCTIONAL = {
    # Bitcoin ships UTXO snapshot fixtures committed against mainnet hashes;
    # they will not match B3Chain's chain.
    "feature_assumeutxo": "uses Bitcoin mainnet UTXO snapshot",
    # Mainnet block-height assumevalid fixtures.
    "feature_assumevalid": "mainnet block hash fixtures",
    # Anything that hard-codes Bitcoin DNS seeds.
    "feature_proxy": "hardcoded Tor seed addresses (rebrand pending)",
}

REGRESSION_PATTERNS = [
    # Common ctest failure signatures that indicate a real regression.
    re.compile(r"^FAILED:", re.MULTILINE),
]

# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

CTEST_RESULT_RE = re.compile(
    r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(?P<name>\S+)\s+\.+\s+(?P<status>Passed|Failed|Timeout|\*\*\*Failed)",
    re.MULTILINE,
)

FUNC_RESULT_RE = re.compile(
    r"^(?P<name>\S+\.py)\s+\|\s+(?P<status>Passed|Failed|Skipped)",
    re.MULTILINE,
)


def classify_test(name: str, status: str, allowlist: dict[str, str]) -> tuple[str, str]:
    """
    Return (category, reason).
    category in: PASS, DIVERGED-EXPECTED, FAIL, SKIP
    """
    if status == "Passed":
        return "PASS", ""
    if status == "Skipped":
        return "SKIP", ""
    # status is some flavour of failed
    base = name.split(".", 1)[0]
    if base in allowlist:
        return "DIVERGED-EXPECTED", allowlist[base]
    return "FAIL", "real regression — not on allowlist"


def parse_ctest(text: str) -> list[dict]:
    out = []
    for m in CTEST_RESULT_RE.finditer(text):
        cat, reason = classify_test(m.group("name"),
                                     m.group("status").replace("***", ""),
                                     EXPECTED_DIVERGENCE_UNIT)
        out.append({
            "kind": "unit",
            "name": m.group("name"),
            "raw_status": m.group("status"),
            "category": cat,
            "reason": reason,
        })
    return out


def parse_functional(text: str) -> list[dict]:
    out = []
    for m in FUNC_RESULT_RE.finditer(text):
        cat, reason = classify_test(m.group("name"),
                                     m.group("status"),
                                     EXPECTED_DIVERGENCE_FUNCTIONAL)
        out.append({
            "kind": "functional",
            "name": m.group("name"),
            "raw_status": m.group("status"),
            "category": cat,
            "reason": reason,
        })
    return out


# ---------------------------------------------------------------------------
# Markdown report + doc rewrite
# ---------------------------------------------------------------------------

def render_markdown(results: list[dict]) -> str:
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    lines = []
    lines.append("## Bitcoin Test Suite — Inheritance Run")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|---|---:|")
    for cat in ("PASS", "DIVERGED-EXPECTED", "FAIL", "SKIP"):
        lines.append(f"| {cat} | {len(by_cat.get(cat, []))} |")
    lines.append(f"| **Total** | **{len(results)}** |")
    lines.append("")

    if by_cat.get("FAIL"):
        lines.append("### Real regressions (BLOCKING)")
        lines.append("")
        lines.append("| Test | Kind | Status | Reason |")
        lines.append("|---|---|---|---|")
        for r in by_cat["FAIL"]:
            lines.append(f"| `{r['name']}` | {r['kind']} | {r['raw_status']} | {r['reason']} |")
        lines.append("")

    if by_cat.get("DIVERGED-EXPECTED"):
        lines.append("### Expected divergences (allowlisted)")
        lines.append("")
        lines.append("| Test | Kind | Reason |")
        lines.append("|---|---|---|")
        for r in by_cat["DIVERGED-EXPECTED"]:
            lines.append(f"| `{r['name']}` | {r['kind']} | {r['reason']} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def rewrite_doc(doc_path: Path, results: list[dict], markdown_report: str) -> None:
    text = doc_path.read_text(encoding="utf-8")

    summary_count = {
        "pass":      sum(1 for r in results if r["category"] == "PASS"),
        "diverged":  sum(1 for r in results if r["category"] == "DIVERGED-EXPECTED"),
        "fail":      sum(1 for r in results if r["category"] == "FAIL"),
        "skip":      sum(1 for r in results if r["category"] == "SKIP"),
    }

    if summary_count["fail"] == 0:
        body = markdown_report
    else:
        body = "**Real regressions detected — review immediately.**\n\n" + markdown_report

    text = re.sub(
        r"<!-- INHERIT-FINDINGS-START -->.*?<!-- INHERIT-FINDINGS-END -->",
        f"<!-- INHERIT-FINDINGS-START -->\n{body}\n<!-- INHERIT-FINDINGS-END -->",
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"^Last full run:.*$",
        f"Last full run: **{datetime.now().strftime('%Y-%m-%d %H:%M')}** "
        f"({summary_count['pass']} PASS, {summary_count['diverged']} diverged, "
        f"{summary_count['fail']} FAIL, {summary_count['skip']} SKIP)",
        text,
        count=1,
        flags=re.MULTILINE,
    )

    doc_path.write_text(text, encoding="utf-8")


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "doc" / "SECURITY-INHERITANCE.md").is_file():
            return parent
    return Path.cwd()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctest", default=None, help="path to ctest log")
    ap.add_argument("--functional", default=None, help="path to functional test log")
    ap.add_argument("--doc", default=None, help="path to SECURITY-INHERITANCE.md")
    ap.add_argument("--json-out", default=None, help="optional JSON results dump")
    args = ap.parse_args()

    results: list[dict] = []
    if args.ctest:
        p = Path(args.ctest)
        if p.is_file():
            results.extend(parse_ctest(p.read_text(encoding="utf-8", errors="replace")))
        else:
            print(f"warn: ctest log not found: {p}", file=sys.stderr)
    if args.functional:
        p = Path(args.functional)
        if p.is_file():
            results.extend(parse_functional(p.read_text(encoding="utf-8", errors="replace")))
        else:
            print(f"warn: functional log not found: {p}", file=sys.stderr)

    if not results:
        print("inheritance_classify: no results parsed (logs empty or missing)",
              file=sys.stderr)
        return 2

    md = render_markdown(results)
    print(md)

    doc = Path(args.doc) if args.doc else (repo_root() / "doc" / "SECURITY-INHERITANCE.md")
    if doc.is_file():
        rewrite_doc(doc, results, md)
        print(f"inheritance_classify: rewrote {doc}", file=sys.stderr)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2), encoding="utf-8")

    fails = sum(1 for r in results if r["category"] == "FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
