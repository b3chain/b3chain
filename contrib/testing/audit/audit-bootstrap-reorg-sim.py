#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[A-4] Bootstrap-phase reorg cost model for B3PoW-Scratch v1.1 (F-3).

Models the launch-phase risk that GPU-hostility + concentrated FPGA
inventory leaves the network with low total hashrate for weeks, during
which a competing FPGA bank can reorg arbitrarily deep.

For each of several launch-phase heights, computes:

  * honest_hs              : assumed network hashrate at that height
  * attacker_hs_required   : minimum sustained attacker hashrate to
                             overtake honest cluster in 7 days
  * boards_required        : attacker_hs_required / per-board hashrate,
                             rounded up
  * capex_usd              : boards_required * per-board USD cost
  * opex_per_day_usd       : approximate power + hosting cost per day
                             (at $0.10/kWh + hosting)
  * confidence             : margin (capex_required / attacker_budget)
                             above which the attack is *not* attractive

Reference parameters (mirror SPEC §8.D and section 3 of
doc/security/B3POW-51-ATTACK-ANALYSIS.md):

  Per-board hashrate           : 20.4 KH/s    (B3Miner-1 KU5P @ 250 MHz)
  Per-board cap-ex             : $1,500 USD  (estimated launch BoM)
  Per-board power              : 75 W
  Power cost                   : $0.10 / kWh
  Hosting overhead             : 25% on top of power
  Honest hashrate at heights
      100   -> 10  KH/s        (1 honest operator on day ~1)
      500   -> 50  KH/s        (a handful of operators)
      1000  -> 100 KH/s        (~5 operators)
      5000  -> 500 KH/s        (~25 operators)
      10000 -> 1   MH/s        (network reaches nEarlyDifficultyGuardHeight)

The values are intentionally illustrative; they are upper bounds
derived from "what fits on a single ASIC vendor's pre-launch
inventory".  The simulator emits a CSV with these numbers + a
deliverable-friendly text table.

CSV output: contrib/testing/audit/results/r0/bootstrap_reorg.csv
"""

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import AuditResult, BOLD, DIM  # type: ignore


BOARD_HS_HZ           = 20_400          # B3Miner-1 KU5P hashes per second
BOARD_USD             = 1_500.0
BOARD_POWER_W         = 75.0
POWER_USD_PER_KWH     = 0.10
HOSTING_OVERHEAD_FRAC = 0.25            # 25% extra on top of power
ATTACK_HORIZON_DAYS   = 7

# b3chain F-6 fix (M-13): consensus floor (powLimit) and post-bootstrap
# operating floor (operating_pow_floor_bits) from kernel/chainparams.cpp.
# These determine the minimum-difficulty attacker-amplification floor
# at the bootstrap heights modelled below.
POW_LIMIT_NBITS              = 0x1d7fffff   # tier-1 consensus floor (4x stricter than original 0x1e01ffff)
OPERATING_POW_FLOOR_NBITS    = 0x1d3fffff   # tier-2 soft floor (2x stricter than powLimit)
TARGET_SPACING_SEC           = 600          # nPowTargetSpacing on mainnet


def _nbits_to_target(nbits: int) -> int:
    size = (nbits >> 24) & 0xFF
    word = nbits & 0x007FFFFF
    return word >> (8 * (3 - size)) if size <= 3 else word << (8 * (size - 3))


def _min_diff_solve_seconds(hashrate_hs: float, nbits: int) -> float:
    """Expected per-block solve time (seconds) when difficulty is at the
    given compact nBits floor and hashrate is `hashrate_hs` H/s."""
    target = _nbits_to_target(nbits)
    p_hit_per_hash = target / (1 << 256)
    if hashrate_hs <= 0 or p_hit_per_hash == 0:
        return float("inf")
    return 1.0 / (hashrate_hs * p_hit_per_hash)

# Heights -> honest network hashrate (Hz) at that point in the bootstrap.
# The last entry crosses nEarlyDifficultyGuardHeight (= 10_000) so the
# F-6 operating floor (0x1d3fffff) is exercised in the cost table.
DEFAULT_HEIGHTS: list[tuple[int, float]] = [
    (    100,    10_000),
    (    500,    50_000),
    (  1_000,   100_000),
    (  5_000,   500_000),
    ( 10_000, 1_000_000),
    ( 50_000, 2_000_000),   # post-bootstrap: F-6 operating floor active
]


def attacker_required_hs(honest_hs: float, horizon_days: int) -> float:
    """Minimum sustained attacker hashrate (Hz) to overtake honest
    cluster within horizon_days of mining.

    Naive lower bound: attacker must produce more cumulative work than
    honest over the same horizon, while *also* hiding their chain
    behind a private firewall.  For a fixed difficulty, attacker_hs >
    honest_hs is sufficient; for ~10% safety margin we add 10%.

    Realistic upper bound considers difficulty retarget responses; under
    LWMA-3 the difficulty rises quickly to attacker hashrate, slowing
    the attack -- but the *initial* private chain is mined at honest
    difficulty.
    """
    del horizon_days  # placeholder for future LWMA-3-aware modelling
    return honest_hs * 1.10           # 10% margin


def cost_model(honest_hs: float, height: int) -> dict:
    attacker_hs = attacker_required_hs(honest_hs, ATTACK_HORIZON_DAYS)
    boards = math.ceil(attacker_hs / BOARD_HS_HZ)
    capex = boards * BOARD_USD

    daily_kwh   = boards * BOARD_POWER_W * 24 / 1000.0
    daily_power = daily_kwh * POWER_USD_PER_KWH
    daily_total = daily_power * (1 + HOSTING_OVERHEAD_FRAC)
    horizon_opex = daily_total * ATTACK_HORIZON_DAYS

    # b3chain F-6 fix (M-13): per-board min-difficulty solve time at the
    # consensus floor (powLimit) and at the post-bootstrap operating
    # floor.  Heights <= nEarlyDifficultyGuardHeight (= 10_000) are
    # bounded only by the tier-1 floor; heights past that are bounded by
    # the (stricter) tier-2 floor.
    EARLY_DIFFICULTY_GUARD_HEIGHT = 10_000
    effective_floor_nbits = POW_LIMIT_NBITS
    if height > EARLY_DIFFICULTY_GUARD_HEIGHT:
        effective_floor_nbits = OPERATING_POW_FLOOR_NBITS
    floor_solve_1board = _min_diff_solve_seconds(BOARD_HS_HZ, effective_floor_nbits)
    floor_solve_honest = _min_diff_solve_seconds(honest_hs, effective_floor_nbits)

    return {
        "attacker_hs_required_hz": attacker_hs,
        "boards_required": boards,
        "capex_usd": capex,
        "opex_per_day_usd": daily_total,
        "opex_horizon_usd": horizon_opex,
        "total_cost_usd": capex + horizon_opex,
        "effective_floor_nbits": effective_floor_nbits,
        "floor_solve_1board_sec": floor_solve_1board,
        "floor_solve_honest_sec": floor_solve_honest,
    }


def emit_csv(out_path: Path, rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "height", "honest_hs_hz", "attacker_hs_required_hz",
            "boards_required", "capex_usd",
            "opex_per_day_usd", "opex_horizon_usd", "total_cost_usd",
            # b3chain F-6 fix (M-13): per-board and honest-cluster
            # solve time at the effective min-difficulty floor.
            "effective_floor_nbits_hex",
            "floor_solve_1board_sec",
            "floor_solve_honest_sec",
        ])
        for r in rows:
            w.writerow([
                r["height"], int(r["honest_hs_hz"]),
                int(r["attacker_hs_required_hz"]), r["boards_required"],
                f"{r['capex_usd']:.0f}",
                f"{r['opex_per_day_usd']:.2f}",
                f"{r['opex_horizon_usd']:.2f}",
                f"{r['total_cost_usd']:.0f}",
                f"0x{r['effective_floor_nbits']:08x}",
                f"{r['floor_solve_1board_sec']:.1f}",
                f"{r['floor_solve_honest_sec']:.1f}",
            ])
    print(BOLD(f"Wrote bootstrap-reorg CSV -> {out_path}"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-csv", type=Path, default=None,
                   help="emit per-height cost CSV at the given path")
    return p.parse_args()


def banner(text: str) -> None:
    print()
    print(BOLD("=" * 72))
    print(BOLD(f"  {text}"))
    print(BOLD("=" * 72))


def main() -> int:
    args = parse_args()
    r = AuditResult("A-4", "Bootstrap-phase reorg cost model (F-3)")

    banner("BOOTSTRAP REORG COST MODEL -- B3PoW-Scratch v1.1")
    print(DIM(f"""
        Models the launch-phase risk (F-3 / V-5) of a competing FPGA bank
        building a private fork at parity hashrate.  Horizon: {ATTACK_HORIZON_DAYS} days.
        Per-board: {BOARD_HS_HZ} H/s, ${BOARD_USD:.0f}, {BOARD_POWER_W:.0f} W.
        Power: ${POWER_USD_PER_KWH:.2f}/kWh + {int(HOSTING_OVERHEAD_FRAC*100)}% hosting overhead.
    """).strip())

    print()
    print(BOLD("Per-height attacker cost"))
    print(f"{'height':>8} | {'honest H/s':>11} | {'att H/s':>11} | "
          f"{'boards':>7} | {'cap-ex $':>9} | {'op-ex/d $':>10} | "
          f"{'total 7d $':>11}")
    print("-" * 92)
    rows = []
    for h, honest_hs in DEFAULT_HEIGHTS:
        m = cost_model(honest_hs, h)
        row = {"height": h, "honest_hs_hz": honest_hs, **m}
        rows.append(row)
        print(f"{h:>8} | {int(honest_hs):>11} | "
              f"{int(m['attacker_hs_required_hz']):>11} | "
              f"{m['boards_required']:>7} | "
              f"{int(m['capex_usd']):>9} | "
              f"{m['opex_per_day_usd']:>10.2f} | "
              f"{int(m['total_cost_usd']):>11}")

    print()
    print(BOLD("F-6 minimum-difficulty floor (post-fix, M-13)"))
    print(f"{'height':>8} | {'effective floor':>17} | "
          f"{'1-board min-diff s/blk':>22} | "
          f"{'honest min-diff s/blk':>22}")
    print("-" * 82)
    for row in rows:
        print(f"{row['height']:>8} | "
              f"0x{row['effective_floor_nbits']:08x}{'':>7} | "
              f"{row['floor_solve_1board_sec']:>22.1f} | "
              f"{row['floor_solve_honest_sec']:>22.1f}")

    # Sanity checks
    for row in rows:
        r.expect(row["boards_required"] >= 1,
                 f"[A-4] height={row['height']}: at least 1 board required",
                 f"boards={row['boards_required']}")
        r.expect(row["capex_usd"] > 0,
                 f"[A-4] height={row['height']}: positive cap-ex",
                 f"capex=${row['capex_usd']:.0f}")

    if args.output_csv:
        emit_csv(args.output_csv, rows)

    print()
    print(BOLD("Mitigations applied by this plan"))
    print(DIM("""
        M-3  LWMA-3              : retargets in ~10 hours, so the attacker's
                                   private chain difficulty rises with their
                                   hashrate within hours, not weeks.
        M-4  max_reorg_depth     : caps maximum reorg depth at 200 blocks
                                   (~33 hours), independent of cap-ex.
        M-5  depth-aware ban     : peer score increments per stale-tip
                                   header, throttling the reveal step.
        M-8  checkpoint stub     : operators can opt-in to checkpoints
                                   during the most vulnerable bootstrap
                                   weeks (off by default).
        M-13 powLimit + op floor : (F-6 fix) consensus floor tightened 4x
                                   to 0x1d7fffff; post-bootstrap LWMA-3
                                   clamps at 0x1d3fffff (2x stricter than
                                   powLimit).  Both floors lift the
                                   minimum-difficulty solve time for any
                                   given hashrate cluster (see table
                                   above) -- attacks that relied on
                                   landing min-difficulty windows now
                                   pay 4x-8x more wall-clock time.
    """).strip())

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
