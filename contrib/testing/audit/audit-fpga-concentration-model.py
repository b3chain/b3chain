#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[A-6] FPGA-vendor concentration model for B3Miner-1 launch (V-6).

GPU-hostile design + a reference FPGA board (B3Miner-1 / KU5P) means
that on day 1 the only economic mining hardware is the b3chain reference
board.  The b3chain team and the contract manufacturer control the
initial supply.  This is structurally identical to "Bitmain making most
SHA-256d hashrate in 2014-2017", just on a faster timescale.

This script is an *analytical* model -- no live chain or hardware -- of
the hashrate-ownership Gini coefficient at T + 0 / 3 / 6 / 12 months
after genesis under three demand curves:

  - Sluggish : few buyers, supply lingers with first-mover operator
  - Linear   : steady ramp, gradual distribution
  - Hype     : fast ramp, multiple competing distributors

The model:
  * Initial inventory at T=0 owned by one principal operator (P0).
  * Each month, `monthly_production` new boards arrive.
  * Boards are distributed across `N_operators` operators following the
    demand curve (a probability mass over operator slots).
  * After distribution we compute the Gini coefficient on per-operator
    board counts.

Outputs:
  - CSV   : contrib/testing/audit/results/r0/fpga_concentration.csv
  - SVG   : doc/security/figures/fpga-gini-curve.svg
            (simple plain-SVG line chart, no external deps)
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import AuditResult, BOLD, DIM  # type: ignore


# Default parameters
N_OPERATORS         = 50
INITIAL_BOARDS_P0   = 100         # first-mover principal operator
MONTHLY_PRODUCTION  = 200         # boards arriving each month


def gini(values: list[float]) -> float:
    """Gini coefficient of a discrete distribution of non-negative values.

    G = (sum_i sum_j |x_i - x_j|) / (2 * n * sum x)
    """
    if not values:
        return 0.0
    total = sum(values)
    if total <= 0:
        return 0.0
    sv = sorted(values)
    n = len(sv)
    cum = 0.0
    for i, v in enumerate(sv, start=1):
        cum += i * v
    return (2 * cum) / (n * total) - (n + 1) / n


def demand_distribution(kind: str, n_operators: int) -> list[float]:
    """Return a probability mass over n_operators describing how new
    boards are distributed each month."""
    if kind == "sluggish":
        # Heavy concentration: ~70% to top 3 operators, rest spread thin.
        m = [0.0] * n_operators
        m[0], m[1], m[2] = 0.40, 0.20, 0.10
        tail = (1.0 - sum(m)) / (n_operators - 3)
        for i in range(3, n_operators):
            m[i] = tail
        return m
    if kind == "linear":
        # Gradually diversifying: top operator still gets more, but
        # everyone gets a slice.
        m = [(n_operators - i) for i in range(n_operators)]
        s = sum(m)
        return [x / s for x in m]
    if kind == "hype":
        # Many competing buyers; near-uniform distribution.
        return [1.0 / n_operators for _ in range(n_operators)]
    raise ValueError(f"unknown demand kind: {kind}")


def simulate_inventory(kind: str, *,
                       n_operators: int = N_OPERATORS,
                       initial_p0: int = INITIAL_BOARDS_P0,
                       monthly_production: int = MONTHLY_PRODUCTION,
                       months: int = 12) -> list[dict]:
    """Simulate per-operator board counts month-by-month."""
    boards = [0] * n_operators
    boards[0] = initial_p0
    rows = []
    for m in range(months + 1):
        # Record state
        g = gini([float(b) for b in boards])
        top_share = boards[0] / max(sum(boards), 1)
        rows.append({"month": m, "demand_kind": kind, "gini": g,
                     "top1_share": top_share,
                     "total_boards": sum(boards)})
        if m == months:
            break
        # Distribute next month's production.
        masses = demand_distribution(kind, n_operators)
        for i, frac in enumerate(masses):
            boards[i] += int(round(frac * monthly_production))
    return rows


def write_csv(out_path: Path, all_rows: list[list[dict]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["demand_kind", "month", "gini", "top1_share", "total_boards"])
        for series in all_rows:
            for r in series:
                w.writerow([r["demand_kind"], r["month"],
                            f"{r['gini']:.6f}", f"{r['top1_share']:.6f}",
                            r["total_boards"]])
    print(BOLD(f"Wrote concentration CSV -> {out_path}"))


# ---------------------------------------------------------------------------
# Plain-SVG line chart (no external dependencies)
# ---------------------------------------------------------------------------
def write_gini_svg(out_path: Path, series_map: dict[str, list[dict]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    width, height = 720, 420
    margin_l, margin_r, margin_t, margin_b = 60, 30, 40, 50

    months_axis = sorted({r["month"] for s in series_map.values() for r in s})
    x_min, x_max = min(months_axis), max(months_axis)
    y_min, y_max = 0.0, 1.0

    def px(month: float) -> float:
        if x_max == x_min:
            return margin_l
        return margin_l + (width - margin_l - margin_r) * (month - x_min) / (x_max - x_min)

    def py(g: float) -> float:
        if y_max == y_min:
            return margin_t
        return margin_t + (height - margin_t - margin_b) * (1 - (g - y_min) / (y_max - y_min))

    palette = {
        "sluggish": "#c0392b",
        "linear":   "#2980b9",
        "hype":     "#27ae60",
    }

    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                 f'viewBox="0 0 {width} {height}">')
    parts.append('<style>'
                 'text { font-family: -apple-system, system-ui, sans-serif; font-size: 12px; }'
                 '.title { font-size: 14px; font-weight: 700; }'
                 '.axis { stroke: #444; stroke-width: 1; }'
                 '.grid { stroke: #ccc; stroke-width: 0.5; stroke-dasharray: 2,3; }'
                 '.line { fill: none; stroke-width: 2.5; }'
                 '.legend { font-size: 12px; }'
                 '</style>')

    parts.append(f'<text class="title" x="{width/2}" y="22" '
                 f'text-anchor="middle">B3Miner-1 hashrate-ownership Gini coefficient by month</text>')

    # Gridlines
    for g in [0.0, 0.25, 0.5, 0.75, 1.0]:
        y = py(g)
        parts.append(f'<line class="grid" x1="{margin_l}" y1="{y}" '
                     f'x2="{width-margin_r}" y2="{y}"/>')
        parts.append(f'<text x="{margin_l-8}" y="{y+4}" text-anchor="end">'
                     f'{g:.2f}</text>')

    # X axis ticks
    for m in months_axis:
        x = px(m)
        if m % 3 == 0 or m == x_min or m == x_max:
            parts.append(f'<line class="grid" x1="{x}" y1="{margin_t}" '
                         f'x2="{x}" y2="{height-margin_b}"/>')
            parts.append(f'<text x="{x}" y="{height-margin_b+14}" '
                         f'text-anchor="middle">T+{m}m</text>')

    # Axes
    parts.append(f'<line class="axis" x1="{margin_l}" y1="{margin_t}" '
                 f'x2="{margin_l}" y2="{height-margin_b}"/>')
    parts.append(f'<line class="axis" x1="{margin_l}" y1="{height-margin_b}" '
                 f'x2="{width-margin_r}" y2="{height-margin_b}"/>')

    # Plot series
    for kind, series in series_map.items():
        pts = " ".join(f"{px(r['month']):.1f},{py(r['gini']):.1f}" for r in series)
        col = palette.get(kind, "#444")
        parts.append(f'<polyline class="line" stroke="{col}" points="{pts}"/>')

    # Legend
    legend_y = margin_t + 8
    for i, (kind, _) in enumerate(series_map.items()):
        col = palette.get(kind, "#444")
        x = width - margin_r - 130
        y = legend_y + i * 18
        parts.append(f'<rect x="{x}" y="{y-9}" width="14" height="3" fill="{col}"/>')
        parts.append(f'<text class="legend" x="{x+22}" y="{y-1}">{kind}</text>')

    # Axis labels
    parts.append(f'<text x="{margin_l-45}" y="{margin_t-12}" font-weight="700">Gini</text>')
    parts.append(f'<text x="{width-margin_r}" y="{height-margin_b+34}" '
                 f'text-anchor="end" font-weight="700">months since genesis</text>')

    parts.append('</svg>')
    out_path.write_text("\n".join(parts), encoding="utf-8")
    print(BOLD(f"Wrote Gini SVG -> {out_path}"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--operators", type=int, default=N_OPERATORS)
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--initial-p0", type=int, default=INITIAL_BOARDS_P0)
    p.add_argument("--monthly-production", type=int, default=MONTHLY_PRODUCTION)
    p.add_argument("--output-csv", type=Path, default=None)
    p.add_argument("--output-svg", type=Path, default=None)
    return p.parse_args()


def banner(text: str) -> None:
    print()
    print(BOLD("=" * 72))
    print(BOLD(f"  {text}"))
    print(BOLD("=" * 72))


def main() -> int:
    args = parse_args()
    r = AuditResult("A-6", "B3Miner-1 hashrate concentration over time (V-6)")

    banner("FPGA CONCENTRATION (B3Miner-1 supply) -- 12-month projection")
    print(DIM(f"""
        n_operators        = {args.operators}
        initial_P0 boards  = {args.initial_p0}
        monthly production = {args.monthly_production} boards
        horizon            = {args.months} months
    """).strip())

    series_map = {}
    all_rows = []
    for kind in ("sluggish", "linear", "hype"):
        s = simulate_inventory(kind,
            n_operators=args.operators,
            initial_p0=args.initial_p0,
            monthly_production=args.monthly_production,
            months=args.months)
        series_map[kind] = s
        all_rows.append(s)

    print()
    print(BOLD("Gini coefficient by month (lower = more decentralised)"))
    print(f"{'month':>7} | " + " | ".join(f"{kind:>10}" for kind in series_map))
    print("-" * 50)
    for m in range(args.months + 1):
        cells = " | ".join(
            f"{series_map[kind][m]['gini']:>10.4f}" for kind in series_map
        )
        print(f"{m:>7} | {cells}")

    # Sanity: hype should be the most decentralised at T+12.
    hype_final = series_map["hype"][-1]["gini"]
    slug_final = series_map["sluggish"][-1]["gini"]
    r.expect(hype_final < slug_final,
             "[A-6] hype demand curve yields lower Gini than sluggish at T+12",
             f"hype={hype_final:.4f}  sluggish={slug_final:.4f}")

    if args.output_csv:
        write_csv(args.output_csv, all_rows)
    if args.output_svg:
        write_gini_svg(args.output_svg, series_map)

    print()
    print(BOLD("Interpretation"))
    print(DIM("""
        The Gini coefficient drops fastest under the 'hype' curve (many
        competing buyers) and slowest under 'sluggish' (one major buyer).
        Under all three curves the network starts highly concentrated
        because the first-mover principal operator holds the initial
        inventory.

        The fix is not algorithmic but supply-side: open RTL allows
        third parties to fabricate competing boards, and the
        max_reorg_depth (M-4) plus depth-aware ban (M-5) cap the blast
        radius even under monopoly.
    """).strip())

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
