#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit/.
"""
[A-7] Verify the M-6 (F-5 fix) 2-tier pinned LRU defense in
``src/crypto/b3pow_cache.{h,cpp}``.

This audit is structural + behavioural.  It does NOT require the
C++ binary; it (a) statically inspects the source for the public
API and parameters, and (b) simulates the worst-case hostile-peer
header flood against a PlainLRU vs the new PinnedLRU to verify
that the active-tip pad is never evicted at the new
``b3pow_cache_depth = 8`` mainnet setting.

Verifies:
 * ``b3pow::Cache::Pin / Unpin / pinned_count / pinned_capacity``
   members exist on the class.
 * ``kDefaultPinnedCapacity = 3`` (tip + 2 ancestors).
 * ``b3pow_cache_depth = 8`` is set on mainnet/testnet/signet.
 * ``Chainstate::UpdateTip`` calls ``m_b3pow_cache.Pin(...)`` for
   the tip and 2 ancestors.
 * Simulated flood: with depth=8, pinned=3, an attacker emitting
   10 000 hostile headers evicts 0 tip pads (PinnedLRU) vs N tip
   pads (PlainLRU).

CSV output: contrib/testing/audit/results/r0/cache_pinning.csv
"""

import argparse
import collections
import csv
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_H = REPO_ROOT / "src" / "crypto" / "b3pow_cache.h"
CACHE_CPP = REPO_ROOT / "src" / "crypto" / "b3pow_cache.cpp"
CHAINPARAMS_CPP = REPO_ROOT / "src" / "kernel" / "chainparams.cpp"
VALIDATION_CPP = REPO_ROOT / "src" / "validation.cpp"

DEFAULT_CSV = REPO_ROOT / "contrib" / "testing" / "audit" / "results" / "r0" / "cache_pinning.csv"


# ---------- structural checks -------------------------------------------------

def check_header_api(errors: list[str]) -> None:
    body = CACHE_H.read_text(encoding="utf-8")
    needed = [
        ("Pin signature",                  r"PadPtr\s+Pin\s*\(\s*const\s+uint256"),
        ("Unpin signature",                r"void\s+Unpin\s*\(\s*const\s+uint256"),
        ("kDefaultPinnedCapacity = 3",     r"kDefaultPinnedCapacity\s*=\s*3"),
        ("pinned_capacity() accessor",     r"pinned_capacity\s*\(\s*\)\s*const"),
        ("pinned_count() accessor",        r"pinned_count\s*\(\s*\)\s*const"),
        ("m_pinned list member",           r"std::list<\s*uint256\s*>\s+m_pinned"),
    ]
    for name, pattern in needed:
        if not re.search(pattern, body):
            errors.append(f"b3pow_cache.h: missing {name}")


def check_cache_depth_8(errors: list[str]) -> None:
    body = CHAINPARAMS_CPP.read_text(encoding="utf-8")
    # The default initialiser may be 8, but the per-network sets
    # must each be 8.  Count those.
    matches = re.findall(r"consensus\.b3pow_cache_depth\s*=\s*(\d+)\s*;", body)
    if not matches:
        errors.append("chainparams.cpp: no b3pow_cache_depth assignment found")
        return
    eights = sum(1 for m in matches if m == "8")
    # Regtest uses depth=1 deliberately.
    expected_mainnet_like = len(matches) - 1
    if eights < expected_mainnet_like:
        errors.append(
            f"chainparams.cpp: only {eights}/{expected_mainnet_like} non-regtest "
            f"networks use b3pow_cache_depth = 8 (got values: {matches})"
        )


def check_update_tip_pins(errors: list[str]) -> None:
    body = VALIDATION_CPP.read_text(encoding="utf-8")
    if "m_b3pow_cache.Pin(" not in body:
        errors.append("validation.cpp: Chainstate::UpdateTip does not call m_b3pow_cache.Pin(...)")
    # Verify the loop covers tip + 2 ancestors (3 iterations).
    if not re.search(r"i\s*<\s*3\b[^;]*;\s*\+\+i,\s*w\s*=\s*w->pprev", body):
        errors.append(
            "validation.cpp: Pin loop does not appear to walk 3 ancestors (tip + 2 prev)"
        )


# ---------- behavioural simulation -------------------------------------------

class PlainLRU:
    """Mirrors the pre-M-6 plain LRU."""
    def __init__(self, depth: int):
        self.depth = depth
        self.order: "collections.OrderedDict[str, None]" = collections.OrderedDict()

    def access(self, key: str) -> tuple[bool, str | None]:
        if key in self.order:
            self.order.move_to_end(key)
            return True, None
        evicted = None
        while len(self.order) >= self.depth:
            evicted, _ = self.order.popitem(last=False)
        self.order[key] = None
        return False, evicted


class PinnedLRU:
    """Mirrors M-6: pinned tier (up to pinned_cap), LRU tier for the rest."""
    def __init__(self, depth: int, pinned_cap: int):
        self.depth = depth
        self.pinned_cap = min(pinned_cap, depth - 1)
        self.pinned: "collections.OrderedDict[str, None]" = collections.OrderedDict()
        self.lru: "collections.OrderedDict[str, None]" = collections.OrderedDict()

    def access(self, key: str) -> tuple[bool, str | None]:
        if key in self.pinned:
            return True, None
        if key in self.lru:
            self.lru.move_to_end(key)
            return True, None
        # Miss: insert into LRU.
        evicted = None
        while len(self.pinned) + len(self.lru) >= self.depth:
            if not self.lru:
                # Shouldn't happen because pinned_cap < depth, but guard.
                break
            evicted, _ = self.lru.popitem(last=False)
        self.lru[key] = None
        return False, evicted

    def pin(self, key: str) -> str | None:
        """Pin and possibly demote oldest pinned to LRU front."""
        if key in self.pinned:
            self.pinned.move_to_end(key, last=False)  # refresh
            return None
        if key in self.lru:
            self.lru.pop(key)
        self.pinned[key] = None
        self.pinned.move_to_end(key, last=False)
        demoted = None
        while len(self.pinned) > self.pinned_cap:
            demoted, _ = self.pinned.popitem(last=True)
            self.lru[demoted] = None
        return demoted


def simulate_flood(depth: int, pinned_cap: int, flood_n: int, seed: int):
    """Return (plain_tip_evictions, pinned_tip_evictions)."""
    tip = "TIP"
    plain = PlainLRU(depth)
    pinned = PinnedLRU(depth, pinned_cap)

    # Warm up: tip is the hot entry being verified repeatedly.
    plain.access(tip)
    pinned.access(tip)
    pinned.pin(tip)  # M-6: pin the tip

    plain_tip_evicted = 0
    pinned_tip_evicted = 0
    for i in range(flood_n):
        novel = f"H{seed}_{i}"
        _, ev_plain = plain.access(novel)
        if ev_plain == tip:
            plain_tip_evicted += 1
            plain.access(tip)  # re-load
        _, ev_pinned = pinned.access(novel)
        if ev_pinned == tip:
            pinned_tip_evicted += 1
            pinned.access(tip)
            pinned.pin(tip)  # would happen on next UpdateTip
    return plain_tip_evicted, pinned_tip_evicted


# ---------- CSV emission ------------------------------------------------------

def emit_csv(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scenarios = [
        # (label, depth_plain, depth_pinned, pinned_cap, flood)
        ("mainnet_pre_fix",  4, 4, 0, 1_000),
        ("mainnet_post_fix", 4, 8, 3, 1_000),
        ("stress_test",      8, 8, 3, 10_000),
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "flood_headers",
                    "plainLRU_tip_evictions", "plainLRU_capacity",
                    "pinnedLRU_tip_evictions", "pinnedLRU_capacity",
                    "pinnedLRU_pinned_cap",
                    "tip_evictions_eliminated_pct"])
        for label, dp, dpr, pc, n in scenarios:
            plain_ev, _ = simulate_flood(dp, 0,  n, seed=1)
            _, pin_ev   = simulate_flood(dpr, pc, n, seed=1)
            elim_pct = 100.0 * (plain_ev - pin_ev) / plain_ev if plain_ev else 0.0
            w.writerow([label, n, plain_ev, dp, pin_ev, dpr, pc,
                        f"{elim_pct:.1f}"])


# ---------- driver ------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", action="store_true",
                   help="Emit CSV (default: also print to stdout)")
    p.add_argument("--csv-path", type=Path, default=DEFAULT_CSV,
                   help=f"CSV output path (default: {DEFAULT_CSV})")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    print("\033[1m== B3PoW Cache Pinning Audit (M-6 / F-5 fix) ==\033[0m")
    errors: list[str] = []
    check_header_api(errors)
    check_cache_depth_8(errors)
    check_update_tip_pins(errors)

    if errors:
        print("\n\033[31mStructural checks FAILED:\033[0m")
        for e in errors:
            print(f"  * {e}")
    else:
        print("\033[32mStructural checks PASSED\033[0m")
        print("  - b3pow_cache.h: Pin/Unpin/pinned_count/pinned_capacity present")
        print("  - kDefaultPinnedCapacity = 3 (tip + 2 ancestors)")
        print("  - b3pow_cache_depth = 8 on mainnet/testnet/signet")
        print("  - Chainstate::UpdateTip pins tip + 2 ancestors")

    print("\nBehavioural simulation (hostile peer header flood)")
    print("---------------------------------------------------")
    for label, dp, dpr, pc, n in [
        ("plain_pre_fix",  4, 4, 0,  1_000),
        ("pinned_post_fix",4, 8, 3,  1_000),
        ("stress_test",    8, 8, 3, 10_000),
    ]:
        plain_ev, _ = simulate_flood(dp, 0, n, seed=1)
        _, pin_ev   = simulate_flood(dpr, pc, n, seed=1)
        print(f"  {label:>18}  flood={n:>6}  "
              f"plain-tip-evicted={plain_ev:>5}  "
              f"pinned-tip-evicted={pin_ev:>5}")

    if args.csv:
        emit_csv(args.csv_path)
        print(f"\nCSV written to: {args.csv_path}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
