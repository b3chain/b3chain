#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Render comparison charts from contrib/testing/bench/results/<run-id>/.

Inputs (CSV):
    bench-b3pow-cpu.csv     (python-ref, several thread counts)
    bench-b3pow-cpp.csv     (cpp-consensus, cold + warm)
    bench-b3pow-fpga.csv    (fpga-live or fpga-dry)
    bench-b3pow-verify.csv  (per-impl verifier latency)

Outputs (SVG + PNG, plus a Markdown table dump):
    out/<run-id>/hashrate-by-backend.svg
    out/<run-id>/hashrate-by-backend.png
    out/<run-id>/verify-latency.svg
    out/<run-id>/verify-latency.png
    out/<run-id>/jhash-by-backend.svg              (only when J/hash is populated)
    out/<run-id>/summary.md

Dependencies:
    matplotlib (graceful skip if missing -- prints actionable install hint)

Usage:
    python3 render-charts.py
    python3 render-charts.py --run-id r0
    python3 render-charts.py --run-id r0 --no-png
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent.parent
RESULTS = BENCH_DIR / "results"
OUT = BENCH_DIR / "charts" / "out"


def have_mpl() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def load_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def fnum(x: str | float | None, default: float = float("nan")) -> float:
    if x in (None, "", "NaN", "nan"):
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def render_hashrate(rows_by_bench: dict[str, list[dict]], out_dir: Path,
                    save_png: bool) -> Path | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bars: list[tuple[str, str, float]] = []  # (backend-label, group, H/s)
    # Pick a representative row per bench.
    for cpu_row in rows_by_bench.get("bench-b3pow-cpu", []):
        if cpu_row.get("label", "").startswith("warm-1t"):
            bars.append(("python-ref (warm, 1T)", "CPU",
                         fnum(cpu_row.get("hashes_per_s"))))
        if cpu_row.get("label", "").startswith("warm-") and \
                int(fnum(cpu_row.get("threads", "0"), 0)) > 1:
            bars.append((f"python-ref (warm, {int(fnum(cpu_row['threads'], 0))}T)",
                         "CPU",
                         fnum(cpu_row.get("hashes_per_s"))))
    for cpp_row in rows_by_bench.get("bench-b3pow-cpp", []):
        bars.append((f"cpp-consensus ({cpp_row.get('label')})", "CPU",
                     fnum(cpp_row.get("hashes_per_s"))))
    for f_row in rows_by_bench.get("bench-b3pow-fpga", []):
        bars.append((f"fpga ({f_row.get('label')})", "FPGA",
                     fnum(f_row.get("hashes_per_s"))))
    if not bars:
        return None

    bars.sort(key=lambda b: b[2])
    labels = [b[0] for b in bars]
    hps = [max(b[2], 1e-3) for b in bars]  # guard log(0)
    groups = [b[1] for b in bars]
    colors = ["#2b7bba" if g == "CPU" else "#bb7c2b" for g in groups]

    fig, ax = plt.subplots(figsize=(10, 1.0 + 0.4 * len(bars)))
    ax.barh(range(len(bars)), hps, color=colors)
    ax.set_yticks(range(len(bars)))
    ax.set_yticklabels(labels)
    ax.set_xscale("log")
    ax.set_xlabel("hashes per second (log)")
    ax.set_title("B3PoW-Scratch v1.1 — full-PoW throughput by backend")
    ax.grid(True, axis="x", linestyle=":", alpha=0.6)
    for i, v in enumerate(hps):
        ax.text(v * 1.05, i, f"{v:,.1f}", va="center", fontsize=8)
    fig.tight_layout()
    svg = out_dir / "hashrate-by-backend.svg"
    fig.savefig(svg, format="svg", bbox_inches="tight")
    if save_png:
        fig.savefig(out_dir / "hashrate-by-backend.png", format="png",
                    dpi=160, bbox_inches="tight")
    plt.close(fig)
    return svg


def render_verify(rows_by_bench: dict[str, list[dict]], out_dir: Path,
                  save_png: bool) -> Path | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = rows_by_bench.get("bench-b3pow-verify", [])
    if not rows:
        return None

    labels = []
    p50s, p95s, p99s = [], [], []
    for r in rows:
        labels.append(f"{r.get('backend')}  {r.get('label')}")
        p50s.append(fnum(r.get("p50_ms")))
        p95s.append(fnum(r.get("p95_ms")))
        p99s.append(fnum(r.get("p99_ms")))

    x = range(len(labels))
    width = 0.27

    fig, ax = plt.subplots(figsize=(10, 1.5 + 0.5 * len(labels)))
    bars50 = ax.bar([i - width for i in x], p50s, width, label="p50",
                    color="#3b8ed0")
    bars95 = ax.bar(x, p95s, width, label="p95", color="#d09a3b")
    bars99 = ax.bar([i + width for i in x], p99s, width, label="p99",
                    color="#d04b3b")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("verify latency (ms)")
    ax.set_title("B3PoW-Scratch verifier latency  (lower is better)")
    ax.axhline(50.0, linestyle="--", color="#666",
               label="SPEC §8.E target (50 ms)")
    ax.legend()
    ax.grid(True, axis="y", linestyle=":", alpha=0.6)

    for b in (*bars50, *bars95, *bars99):
        h = b.get_height()
        if math.isfinite(h):
            ax.text(b.get_x() + b.get_width() / 2, h, f"{h:.1f}",
                    ha="center", va="bottom", fontsize=7)
    fig.tight_layout()
    svg = out_dir / "verify-latency.svg"
    fig.savefig(svg, format="svg", bbox_inches="tight")
    if save_png:
        fig.savefig(out_dir / "verify-latency.png", format="png",
                    dpi=160, bbox_inches="tight")
    plt.close(fig)
    return svg


def render_jhash(rows_by_bench: dict[str, list[dict]], out_dir: Path,
                 save_png: bool) -> Path | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pairs: list[tuple[str, float]] = []
    for bench, rows in rows_by_bench.items():
        for r in rows:
            j = fnum(r.get("j_per_hash"))
            if math.isfinite(j) and j > 0:
                pairs.append((f"{r.get('backend')}  {r.get('label')}", j))
    if not pairs:
        return None

    pairs.sort(key=lambda p: p[1])
    labels = [p[0] for p in pairs]
    js = [p[1] for p in pairs]

    fig, ax = plt.subplots(figsize=(10, 1.0 + 0.4 * len(pairs)))
    ax.barh(range(len(pairs)), js, color="#5da25d")
    ax.set_yticks(range(len(pairs)))
    ax.set_yticklabels(labels)
    ax.set_xlabel("joules per hash (lower is better)")
    ax.set_title("B3PoW-Scratch — energy per hash by backend")
    ax.grid(True, axis="x", linestyle=":", alpha=0.6)
    for i, v in enumerate(js):
        ax.text(v * 1.02, i, f"{v:.3f}", va="center", fontsize=8)
    fig.tight_layout()
    svg = out_dir / "jhash-by-backend.svg"
    fig.savefig(svg, format="svg", bbox_inches="tight")
    if save_png:
        fig.savefig(out_dir / "jhash-by-backend.png", format="png",
                    dpi=160, bbox_inches="tight")
    plt.close(fig)
    return svg


def write_summary_md(rows_by_bench: dict[str, list[dict]],
                     out_dir: Path) -> Path:
    lines = ["# B3PoW-Scratch bench results summary",
             "",
             "Auto-generated by `render-charts.py`. See per-bench CSVs in "
             "this directory for raw rows.",
             ""]
    for bench, rows in rows_by_bench.items():
        if not rows:
            continue
        lines.append(f"## {bench}")
        lines.append("")
        lines.append("| label | backend | threads | H/s | p50 ms | p95 ms | "
                     "p99 ms | J/hash | note |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            j = fnum(r.get("j_per_hash"))
            lines.append(
                f"| {r.get('label','')} "
                f"| {r.get('backend','')} "
                f"| {r.get('threads','')} "
                f"| {fnum(r.get('hashes_per_s')):.2f} "
                f"| {fnum(r.get('p50_ms')):.2f} "
                f"| {fnum(r.get('p95_ms')):.2f} "
                f"| {fnum(r.get('p99_ms')):.2f} "
                f"| {'n/a' if not math.isfinite(j) else f'{j:.3f}'} "
                f"| {r.get('note','')} |"
            )
        lines.append("")
    path = out_dir / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", default="r0",
                    help="results bucket name (default: r0)")
    ap.add_argument("--no-png", action="store_true",
                    help="emit only SVG (skip PNG to save space)")
    args = ap.parse_args()

    in_dir = RESULTS / args.run_id
    if not in_dir.is_dir():
        print(f"error: no results bucket at {in_dir}\n"
              "       run a bench first (e.g. python3 bench-b3pow-cpu.py)",
              file=sys.stderr)
        return 2

    rows_by_bench: dict[str, list[dict]] = {}
    for name in ("bench-b3pow-cpu", "bench-b3pow-cpp",
                 "bench-b3pow-fpga", "bench-b3pow-verify"):
        rows_by_bench[name] = load_csv(in_dir / f"{name}.csv")

    out_dir = OUT / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = write_summary_md(rows_by_bench, out_dir)
    print(f"  wrote {summary.relative_to(BENCH_DIR)}")

    if not have_mpl():
        print("\nmatplotlib not installed; skipping SVG/PNG renders.\n"
              "  install: pip3 install matplotlib\n"
              f"  text summary written to {summary}\n", file=sys.stderr)
        return 0

    for name, fn in (
        ("hashrate-by-backend", render_hashrate),
        ("verify-latency",      render_verify),
        ("jhash-by-backend",    render_jhash),
    ):
        try:
            p = fn(rows_by_bench, out_dir, not args.no_png)
            if p:
                print(f"  wrote {p.relative_to(BENCH_DIR)}")
            else:
                print(f"  skipped {name} (no input rows)")
        except Exception as exc:  # noqa: BLE001
            print(f"  error rendering {name}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
