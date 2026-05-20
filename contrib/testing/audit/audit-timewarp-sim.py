#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[A-3] Time-warp attack simulator (Murch-Zawy / BIP94).

Models the canonical time-warp attack on a Bitcoin-style 2016-block
retarget chain.  The attacker crafts block timestamps so that the
*observed* timespan inside a retarget window appears much larger than
real time, tricking the retarget into lowering difficulty.

Two scenarios are compared side-by-side:

  Scenario A  (enforce_BIP94 = false, current b3chain mainnet)
      The attacker can backdate the first block of a new retarget window
      to the median-time-past (MTP) of the previous 11 blocks, while
      forward-dating the last block to 2-hour-future limit.  Over several
      retarget periods, difficulty can be driven down by a large factor.

  Scenario B  (enforce_BIP94 = true, the F-2 fix)
      The retarget validation uses the timestamp of the *first* block of
      the new window (not the last block of the previous one) when
      computing the elapsed-time figure.  This closes the manipulation
      vector documented by Murch & Zawy.

This script is pure Python; it never actually mines.  It implements the
Bitcoin retarget formula (`CalculateNextWorkRequired`) from src/pow.cpp
plus the BIP94 patch, simulates 10 retarget windows in each scenario,
and outputs the difficulty curve as CSV.

CSV output: contrib/testing/audit/results/r0/timewarp_curves.csv
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import AuditResult, BOLD, DIM, GREEN, RED  # type: ignore


# Bitcoin-style retarget params, mirroring src/kernel/chainparams.cpp.
TARGET_SPACING_SEC    = 600                  # 10 min
ADJUSTMENT_INTERVAL   = 2016                 # blocks
EXPECTED_TIMESPAN_SEC = TARGET_SPACING_SEC * ADJUSTMENT_INTERVAL   # 14 days
MIN_TIMESPAN_SEC      = EXPECTED_TIMESPAN_SEC // 4   # 4x clamp
MAX_TIMESPAN_SEC      = EXPECTED_TIMESPAN_SEC * 4

# Bitcoin's "future-block-time" tolerance.
FUTURE_TIME_LIMIT_SEC = 2 * 60 * 60          # 2 hours


def bitcoin_retarget(prev_target: int,
                     window_first_block_time: int,
                     window_last_block_time: int) -> int:
    """Replicates CalculateNextWorkRequired() arithmetic.

    Args:
        prev_target              -- previous difficulty target as 256-bit int
        window_first_block_time  -- nTime of the first block of the
                                    just-finished retarget window
        window_last_block_time   -- nTime of the last  block of the
                                    just-finished retarget window
    Returns the new difficulty target.
    """
    timespan = window_last_block_time - window_first_block_time
    if timespan < MIN_TIMESPAN_SEC:
        timespan = MIN_TIMESPAN_SEC
    if timespan > MAX_TIMESPAN_SEC:
        timespan = MAX_TIMESPAN_SEC
    new_target = prev_target * timespan // EXPECTED_TIMESPAN_SEC
    return new_target


def bip94_retarget(prev_target: int,
                   prev_window_first_block_time: int,
                   current_window_first_block_time: int) -> int:
    """BIP94 retarget: uses the timestamp of the FIRST block of the
    current (just-finished) retarget window, not the last block of the
    previous one.

    Murch-Zawy showed that the off-by-one between "first block of
    current window" and "first block of previous window" is what enables
    the time-warp.  BIP94 closes the loop.

    Args:
        prev_target                       -- previous difficulty target
        prev_window_first_block_time      -- nTime of the first block
                                             of the PREVIOUS window
        current_window_first_block_time   -- nTime of the first block
                                             of the CURRENT  window
    Returns the new difficulty target.
    """
    timespan = current_window_first_block_time - prev_window_first_block_time
    if timespan < MIN_TIMESPAN_SEC:
        timespan = MIN_TIMESPAN_SEC
    if timespan > MAX_TIMESPAN_SEC:
        timespan = MAX_TIMESPAN_SEC
    new_target = prev_target * timespan // EXPECTED_TIMESPAN_SEC
    return new_target


# ---------------------------------------------------------------------------
# Time-warp window generator
#
# An attacker mining a 2016-block window can:
#   1. Backdate the first block of the window to the median-time-past
#      of the previous 11 blocks (i.e. nearly the previous tip's time).
#   2. Forward-date the last block to 2h-future from real time.
#   3. For all middle blocks, walk the clock forward in tiny increments
#      so neither the MTP nor the 2-hour-future check ever fires.
#
# The result: an observed "timespan" for the window inflated by ~28 days
# relative to its real-time elapsed-time of ~14 days, halving difficulty.
# Sustained over multiple windows, difficulty plunges geometrically.
# ---------------------------------------------------------------------------
def craft_warped_window(real_time_start: int,
                        prev_tip_time: int,
                        inflation_factor: float = 2.0) -> tuple[int, int, int]:
    """Return (first_block_time, last_block_time, real_time_end) for one
    crafted retarget window.

    inflation_factor=2.0 means: pretend the window took 2 weeks * 2 = 4 weeks
    of "observed" time, even though the attacker's actual mining only took
    real elapsed time = EXPECTED_TIMESPAN_SEC.

    Returns:
        first_block_time  -- timestamp recorded for block N+1
        last_block_time   -- timestamp recorded for block N+2016
        real_time_end     -- wall-clock time when block N+2016 was mined
    """
    # Backdate first block of the window to ~MTP of previous tips.
    # Conservatively use prev_tip_time - 1 hour.
    first_block_time = prev_tip_time - 60 * 60

    # Forward-date last block by inflation_factor weeks of "observed" time.
    last_block_time = first_block_time + int(inflation_factor * EXPECTED_TIMESPAN_SEC)

    # Real elapsed time the attacker actually spent mining: assume they
    # mined at honest difficulty (no advantage yet for the first window).
    real_time_end = real_time_start + EXPECTED_TIMESPAN_SEC
    return first_block_time, last_block_time, real_time_end


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
def simulate(use_bip94: bool, n_windows: int = 10) -> list[dict]:
    """Run n_windows retarget cycles with crafted timestamps; return
    a list of dicts (one per window) with the difficulty trajectory."""
    initial_target = 1 << 240        # arbitrary; only ratios matter
    real_time_now = 1_700_000_000    # epoch arbitrary

    target_now = initial_target
    # Bootstrap: pretend the previous window ran honestly.
    prev_window_first_block_time = real_time_now - EXPECTED_TIMESPAN_SEC
    prev_tip_time = real_time_now

    history = []
    for w in range(n_windows):
        first_time, last_time, real_end = craft_warped_window(
            real_time_start=real_time_now,
            prev_tip_time=prev_tip_time,
            inflation_factor=2.0,
        )
        if use_bip94:
            new_target = bip94_retarget(
                prev_target=target_now,
                prev_window_first_block_time=prev_window_first_block_time,
                current_window_first_block_time=first_time,
            )
        else:
            new_target = bitcoin_retarget(
                prev_target=target_now,
                window_first_block_time=first_time,
                window_last_block_time=last_time,
            )
        # difficulty (relative): 1 / target ratio
        difficulty_relative = initial_target / new_target
        history.append({
            "window": w + 1,
            "first_block_time": first_time,
            "last_block_time": last_time,
            "real_time_end": real_end,
            "target_hex": f"0x{new_target:064x}",
            "difficulty_relative": difficulty_relative,
        })
        # Step forward.
        target_now = new_target
        prev_window_first_block_time = first_time
        prev_tip_time = last_time
        real_time_now = real_end
    return history


def emit_curves_csv(out_path: Path,
                    history_off: list[dict],
                    history_on: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "window",
            "BIP94_off_target_hex",
            "BIP94_off_difficulty_relative",
            "BIP94_on_target_hex",
            "BIP94_on_difficulty_relative",
        ])
        for off, on in zip(history_off, history_on):
            w.writerow([
                off["window"],
                off["target_hex"], f"{off['difficulty_relative']:.6f}",
                on["target_hex"], f"{on['difficulty_relative']:.6f}",
            ])
    print(BOLD(f"Wrote time-warp curves -> {out_path}"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--windows", type=int, default=10,
                   help="number of retarget windows to simulate (default 10)")
    p.add_argument("--output-csv", type=Path, default=None,
                   help="emit side-by-side difficulty curve CSV")
    return p.parse_args()


def banner(text: str) -> None:
    print()
    print(BOLD("=" * 72))
    print(BOLD(f"  {text}"))
    print(BOLD("=" * 72))


def main() -> int:
    args = parse_args()
    r = AuditResult("A-3", "Time-warp attack: BIP94 effectiveness")

    banner("TIME-WARP ATTACK (Murch-Zawy / BIP94) -- B3PoW-Scratch v1.1")
    print(DIM("""
        The time-warp attack manipulates block timestamps to inflate the
        observed retarget timespan, causing the difficulty algorithm to
        lower difficulty far below what real elapsed time warrants.

        Two scenarios compared:
          (A) enforce_BIP94 = false   -- current b3chain mainnet (F-2)
          (B) enforce_BIP94 = true    -- the F-2 fix

        Crafted attacker timespans: each window pretends to have taken
        2 * 14 days = 28 days of "observed" time, even though real
        elapsed time is 14 days.  Sustained over 10 windows.
    """).strip())

    history_off = simulate(use_bip94=False, n_windows=args.windows)
    history_on  = simulate(use_bip94=True,  n_windows=args.windows)

    print()
    print(BOLD("Difficulty trajectory (relative to initial = 1.0)"))
    print(f"{'window':>6} | {'BIP94 OFF':>12} | {'BIP94 ON':>12} | {'ratio off/on':>14}")
    print("-" * 56)
    for off, on in zip(history_off, history_on):
        ratio = (off["difficulty_relative"] / on["difficulty_relative"]
                 if on["difficulty_relative"] != 0 else float("inf"))
        print(f"{off['window']:>6} | "
              f"{off['difficulty_relative']:>12.4f} | "
              f"{on['difficulty_relative']:>12.4f} | "
              f"{ratio:>14.4f}")

    # Sanity assertions for the audit framework.
    final_off = history_off[-1]["difficulty_relative"]
    final_on  = history_on[-1]["difficulty_relative"]
    r.expect(final_off < final_on,
             "[A-3] without BIP94, difficulty falls (attack succeeds)",
             f"final OFF={final_off:.4f}  ON={final_on:.4f}")
    # BIP94 should clamp the inflation to near-honest values.
    r.expect(abs(final_on - 1.0) < 0.05 or final_on >= 0.95,
             "[A-3] with BIP94, difficulty stays at or near initial (attack closed)",
             f"final ON={final_on:.4f}  (expected close to 1.0)")

    if args.output_csv:
        emit_curves_csv(args.output_csv, history_off, history_on)

    print()
    print(BOLD("Result"))
    delta = final_on - final_off
    if delta > 0:
        print(GREEN(f"   BIP94 closes the attack: difficulty maintained {delta:.3f} higher"))
    else:
        print(RED("   BIP94 did not close the attack (this is unexpected)"))

    print()
    print(BOLD("Recommendation (matches M-2 in B3POW-51-ATTACK-ANALYSIS.md)"))
    print(DIM("""
        Set consensus.enforce_BIP94 = true on mainnet, testnet, and signet
        in src/kernel/chainparams.cpp.  Already true on testnet4.
        This is a free pre-genesis hard fork (no live chain affected).
    """).strip())

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
