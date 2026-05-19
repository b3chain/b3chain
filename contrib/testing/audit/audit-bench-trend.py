#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[A-8] Benchmark-trend regression gate for B3PoW-Scratch v1.1.

Consumes two CSV files produced by `bench_bitcoin --output-csv=...`
(one for the proposed commit, one for the baseline) and reports the
per-benchmark median-elapsed delta as a markdown table.  Fails (exit
1) if any tracked benchmark regresses by more than the per-run
`--threshold` percentage (default 5%).

The B3Chain SECURITY-ROADMAP §3 "Continuous benchmark CI" deliverable
calls for catching silent performance regressions in the consensus-
critical hot path: any change that makes a CheckBlock / ConnectBlock
/ B3PoW verifier benchmark >5% slower is by definition either an
accidental performance bug (must be fixed before merge) or an
intentional security trade-off (must be called out in CHANGELOG).

CSV input format (matches src/bench/bench.cpp:167):
    # Benchmark, evals, iterations, total, min, max, median

Times are in seconds.  We compare on the `median` column because
median is the most stable single-run statistic the framework emits
(less noise-sensitive than min/total).

Usage:
    python3 contrib/testing/audit/audit-bench-trend.py \\
        --baseline bench-prev.csv \\
        --head bench-head.csv \\
        --threshold 5.0 \\
        [--markdown-out summary.md]

Exit codes:
    0  -- all tracked benchmarks within threshold (or improved)
    1  -- at least one regression exceeds threshold
    2  -- input error (missing file / empty intersection / parse error)
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Re-use the shared colour helpers if the lib/ dir is importable, but
# don't make it a hard dep -- this script is meant to also run inside
# a minimal CI container where only python3-stdlib is guaranteed.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    from audit_common import BOLD, DIM, GREEN, RED, YELLOW  # type: ignore
except Exception:
    BOLD = lambda s: s
    DIM = lambda s: s
    GREEN = lambda s: s
    RED = lambda s: s
    YELLOW = lambda s: s


def parse_csv(path: Path) -> dict[str, dict[str, float]]:
    """
    Parse a bench_bitcoin --output-csv file into a {name: row} dict.

    The header line is:
        # Benchmark, evals, iterations, total, min, max, median
    Times are in seconds (per ankerl::nanobench).
    """
    if not path.is_file():
        raise FileNotFoundError(f"benchmark CSV not found: {path}")

    rows: dict[str, dict[str, float]] = {}
    with path.open("r") as fh:
        reader = csv.reader(fh)
        for raw in reader:
            row = [c.strip() for c in raw if c.strip()]
            if not row:
                continue
            if row[0].startswith("#"):
                continue  # header
            if len(row) < 7:
                continue  # malformed
            name = row[0]
            try:
                rows[name] = {
                    "evals":      float(row[1]),
                    "iterations": float(row[2]),
                    "total":      float(row[3]),
                    "min":        float(row[4]),
                    "max":        float(row[5]),
                    "median":     float(row[6]),
                }
            except ValueError:
                continue  # non-numeric / weird row -- skip
    return rows


def fmt_seconds(s: float) -> str:
    """Pretty-print a wall-clock seconds value with the natural unit."""
    if s >= 1.0:
        return f"{s:7.3f} s"
    if s >= 1e-3:
        return f"{s * 1e3:7.3f} ms"
    if s >= 1e-6:
        return f"{s * 1e6:7.3f} us"
    return f"{s * 1e9:7.3f} ns"


def status_marker(delta_pct: float, threshold_pct: float) -> str:
    """Returns OK / WARN / REGRESS based on signed % delta."""
    # Small FP slack so a benchmark that's exactly at the threshold
    # (e.g. 5.000000000000004% due to (h - b)/b rounding noise) is not
    # flagged.  Crosses ~+5e-13 percent of the threshold, well below
    # measurement noise.
    if delta_pct <= -1.0:
        return "FASTER"
    if delta_pct <= threshold_pct * (1.0 + 1e-9):
        return "OK"
    return "REGRESS"


def render_markdown(rows: list[tuple[str, float, float, float, str]],
                    threshold_pct: float,
                    baseline_path: Path,
                    head_path: Path) -> str:
    """Render the comparison as a GitHub-flavoured markdown table."""
    lines: list[str] = []
    lines.append(f"## Benchmark trend (threshold: +{threshold_pct:.1f}%)")
    lines.append("")
    lines.append(f"- baseline: `{baseline_path}`")
    lines.append(f"- head:     `{head_path}`")
    lines.append("")
    lines.append("| Benchmark | baseline median | head median | Δ% | status |")
    lines.append("|---|---:|---:|---:|---|")
    for name, base, head, delta_pct, status in rows:
        emoji = (":white_check_mark:" if status in ("OK", "FASTER")
                 else ":x:")
        sign = "+" if delta_pct >= 0 else ""
        lines.append(
            f"| `{name}` | {fmt_seconds(base)} | {fmt_seconds(head)} | "
            f"{sign}{delta_pct:.2f}% | {status} {emoji} |"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline", type=Path, required=True,
                   help="CSV from the baseline commit (HEAD~1)")
    p.add_argument("--head", type=Path, required=True,
                   help="CSV from the proposed commit (HEAD)")
    p.add_argument("--threshold", type=float, default=5.0,
                   help="regression threshold in %% (default: 5.0)")
    p.add_argument("--markdown-out", type=Path, default=None,
                   help="if set, also write the markdown table to this path")
    p.add_argument("--only", default=None,
                   help="optional regex filter on benchmark names "
                        "(passed through to Python re.search)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        baseline = parse_csv(args.baseline)
        head = parse_csv(args.head)
    except FileNotFoundError as e:
        print(RED(f"ERROR: {e}"))
        return 2

    if not baseline:
        print(RED(f"ERROR: baseline CSV {args.baseline} parsed to 0 rows"))
        return 2
    if not head:
        print(RED(f"ERROR: head CSV {args.head} parsed to 0 rows"))
        return 2

    common = sorted(set(baseline) & set(head))
    if args.only:
        import re
        pat = re.compile(args.only)
        common = [n for n in common if pat.search(n)]

    if not common:
        print(RED("ERROR: no benchmarks in common between baseline and head"))
        return 2

    rows: list[tuple[str, float, float, float, str]] = []
    any_regress = False

    for name in common:
        b = baseline[name]["median"]
        h = head[name]["median"]
        if b == 0.0:
            delta_pct = 0.0 if h == 0.0 else float("inf")
        else:
            delta_pct = (h - b) / b * 100.0
        status = status_marker(delta_pct, args.threshold)
        if status == "REGRESS":
            any_regress = True
        rows.append((name, b, h, delta_pct, status))

    # Plain-text table for the terminal.
    print(BOLD(f"Benchmark trend (threshold: +{args.threshold:.1f}%)"))
    print(DIM(f"  baseline: {args.baseline}"))
    print(DIM(f"  head:     {args.head}"))
    print()
    print(f"{'Benchmark':40} | {'baseline':>12} | {'head':>12} | "
          f"{'delta':>9} | status")
    print("-" * 96)
    for name, base, head_val, delta_pct, status in rows:
        sign = "+" if delta_pct >= 0 else ""
        col = (RED if status == "REGRESS"
               else GREEN if status in ("OK", "FASTER")
               else YELLOW)
        print(
            f"{name:40} | {fmt_seconds(base):>12} | "
            f"{fmt_seconds(head_val):>12} | "
            f"{sign}{delta_pct:>7.2f}% | {col(status)}"
        )

    if args.markdown_out is not None:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        # Explicit utf-8 so the delta symbol (U+0394) survives on
        # Windows runners that default to cp1252.  GitHub Actions
        # Linux runners are utf-8 by default but explicit is safer.
        args.markdown_out.write_text(
            render_markdown(rows, args.threshold, args.baseline, args.head),
            encoding="utf-8",
        )
        print()
        print(DIM(f"Wrote markdown summary -> {args.markdown_out}"))

    print()
    if any_regress:
        regressors = [r[0] for r in rows if r[4] == "REGRESS"]
        print(RED(BOLD(
            f"FAIL: {len(regressors)} benchmark(s) regressed by "
            f">{args.threshold:.1f}%: " + ", ".join(regressors)
        )))
        return 1
    print(GREEN(BOLD(
        f"PASS: all {len(rows)} tracked benchmark(s) within "
        f"+{args.threshold:.1f}% of baseline"
    )))
    return 0


if __name__ == "__main__":
    sys.exit(main())
