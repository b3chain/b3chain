#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[A-5] Cache-eviction DoS model for b3pow::Cache (F-5 / V-9).

A peer flooding headers with novel `prev_block_hash` values forces
evictions of the active-tip pad from the LRU cache.  On the next
legitimate tip extension, the verifier pays the 5 ms cold-init penalty.
At cache_depth = 4 (current mainnet), the attacker needs 4 distinct
hostile headers to fully cycle the cache.

This script models the eviction dynamics analytically (no live regtest
binary is required because the LRU semantics are deterministic) and
contrasts:

  (A) Plain LRU (current behaviour)
        - cache_depth = 4
        - every novel prev_block_hash evicts the LRU entry
        - active tip pad is evictable if not touched recently

  (B) 2-tier pinned LRU (M-6, the fix)
        - cache_depth = 8
        - 3 pinned slots = best-header + 2 ancestors, never evicted
        - 5 LRU slots remain for ad-hoc requests
        - hostile peer can churn only the LRU tier

Output: average evictions of the active-tip pad per N hostile headers
and the resulting cold-init cost.

CSV output: contrib/testing/audit/results/r0/cache_eviction.csv
"""

import argparse
import csv
import collections
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import AuditResult, BOLD, DIM  # type: ignore


# Reference cost parameters (mirror SPEC §6.1 + b3pow_scratch.cpp comment).
COLD_INIT_MS = 5.0     # one pad init via 16384 BLAKE3-XOF calls
HOT_HIT_MS   = 0.05    # cache hit (memcpy of 1 MB pad to thread-local)


class PlainLRU:
    """Plain LRU mirroring b3pow_cache.h current behaviour."""
    def __init__(self, depth: int):
        self.depth = depth
        self.order = collections.OrderedDict()

    def lookup_or_insert(self, key: str) -> tuple[bool, str | None]:
        """Returns (hit, evicted_key_or_None)."""
        if key in self.order:
            self.order.move_to_end(key)
            return True, None
        evicted = None
        if len(self.order) >= self.depth:
            evicted, _ = self.order.popitem(last=False)
        self.order[key] = True
        return False, evicted


class PinnedLRU:
    """2-tier LRU: pinned slots are immune to eviction (M-6).

    Pinned keys (managed via pin()/unpin()) live in a separate set
    that the eviction logic skips entirely.
    """
    def __init__(self, depth: int, pinned_capacity: int = 3):
        self.depth = depth
        self.pinned_capacity = pinned_capacity
        self.pinned: collections.OrderedDict[str, bool] = collections.OrderedDict()
        self.lru: collections.OrderedDict[str, bool] = collections.OrderedDict()

    def pin(self, key: str) -> None:
        """Promote/insert key into the pinned tier; evict oldest pinned
        slot if needed."""
        # Remove from LRU tier if present.
        self.lru.pop(key, None)
        if key in self.pinned:
            self.pinned.move_to_end(key)
            return
        if len(self.pinned) >= self.pinned_capacity:
            self.pinned.popitem(last=False)
        self.pinned[key] = True

    def lookup_or_insert(self, key: str) -> tuple[bool, str | None]:
        """Returns (hit, evicted_key_or_None).  Pinned keys are never
        the eviction victim."""
        if key in self.pinned:
            return True, None
        if key in self.lru:
            self.lru.move_to_end(key)
            return True, None
        evicted = None
        # Compute LRU capacity at runtime; the pinned tier doesn't shrink
        # the total cache budget because the cache_depth in M-6 is raised
        # to 8 (3 pinned + 5 LRU).
        lru_capacity = self.depth - len(self.pinned)
        if lru_capacity <= 0:
            lru_capacity = 1
        if len(self.lru) >= lru_capacity:
            evicted, _ = self.lru.popitem(last=False)
        self.lru[key] = True
        return False, evicted


def _hex_key(n: int) -> str:
    return f"k{n:016x}"


def simulate(cache, *, n_attacker_headers: int, attacker_novel: bool,
             tip_key: str, ancestor_keys: list[str] | None = None,
             interleave_honest_tip: bool = True,
             seed: int = 42) -> dict:
    """Simulate `n_attacker_headers` hostile requests interleaved with
    legitimate tip-extension requests.

    Returns:
        {'tip_evictions': int, 'honest_misses': int, 'attacker_misses': int,
         'honest_cost_ms': float, 'total_cost_ms': float}
    """
    rng = random.Random(seed)
    # Pre-warm the cache with the tip + ancestors.
    if isinstance(cache, PinnedLRU):
        cache.pin(tip_key)
        for k in (ancestor_keys or []):
            cache.pin(k)
    else:
        cache.lookup_or_insert(tip_key)
        for k in (ancestor_keys or []):
            cache.lookup_or_insert(k)

    tip_evictions  = 0
    honest_misses  = 0
    attacker_misses = 0
    total_cost_ms  = 0.0

    for i in range(n_attacker_headers):
        # Hostile request with novel prev_block_hash.
        if attacker_novel:
            hostile_key = _hex_key(rng.getrandbits(60) | (1 << 60))
        else:
            # Hostile uses one of a small set (e.g. round-robin existing keys).
            hostile_key = _hex_key(i % 4)
        hit, evicted = cache.lookup_or_insert(hostile_key)
        if not hit:
            attacker_misses += 1
            total_cost_ms += COLD_INIT_MS
        if evicted == tip_key:
            tip_evictions += 1

        if interleave_honest_tip and (i % 4 == 0):
            # Honest validation -- best-case the tip is still cached.
            hit2, _ = cache.lookup_or_insert(tip_key)
            if not hit2:
                honest_misses += 1
                total_cost_ms += COLD_INIT_MS
            else:
                total_cost_ms += HOT_HIT_MS

    return {
        "tip_evictions": tip_evictions,
        "honest_misses": honest_misses,
        "attacker_misses": attacker_misses,
        "total_cost_ms": total_cost_ms,
    }


def emit_csv(out_path: Path, results: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["cache_kind", "n_attacker_headers",
                    "tip_evictions", "honest_misses",
                    "attacker_misses", "total_cost_ms"])
        for r in results:
            w.writerow([r["kind"], r["n"], r["tip_evictions"],
                        r["honest_misses"], r["attacker_misses"],
                        f"{r['total_cost_ms']:.2f}"])
    print(BOLD(f"Wrote cache-eviction CSV -> {out_path}"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-attacker", type=int, default=10_000,
                   help="number of hostile headers to simulate")
    p.add_argument("--output-csv", type=Path, default=None,
                   help="emit detailed CSV at the given path")
    return p.parse_args()


def banner(text: str) -> None:
    print()
    print(BOLD("=" * 72))
    print(BOLD(f"  {text}"))
    print(BOLD("=" * 72))


def main() -> int:
    args = parse_args()
    r = AuditResult("A-5", "Cache-eviction DoS on b3pow::Cache (F-5)")

    banner("CACHE-EVICTION DoS -- b3pow::Cache LRU (V-9)")
    print(DIM("""
        A hostile peer can submit many headers with novel prev_block_hash
        values, each one forcing an eviction in the LRU cache.  At
        b3pow_cache_depth = 4 (current mainnet default), four distinct
        novel headers cycle the cache, kicking out the active-tip pad
        and forcing a 5 ms cold-init on the next legitimate validation.

        The M-6 fix is a 2-tier cache: pinned slots for the active tip
        and 2 ancestors (never evicted), and a normal LRU for everything
        else.  cache_depth raised from 4 -> 8.
    """).strip())

    tip = _hex_key(0xDEADBEEF)
    ancestors = [_hex_key(0xDEADBEE0 + i) for i in range(2)]

    # Scenario A -- current mainnet (plain LRU, depth=4)
    plain = PlainLRU(depth=4)
    a = simulate(plain, n_attacker_headers=args.n_attacker,
                 attacker_novel=True, tip_key=tip,
                 ancestor_keys=[ancestors[0]])  # only 1 ancestor fits

    # Scenario B -- M-6 fix (2-tier pinned LRU, depth=8, 3 pinned)
    pinned = PinnedLRU(depth=8, pinned_capacity=3)
    b = simulate(pinned, n_attacker_headers=args.n_attacker,
                 attacker_novel=True, tip_key=tip,
                 ancestor_keys=ancestors)

    print()
    print(BOLD(f"Results after {args.n_attacker} hostile headers"))
    print(f"{'metric':>25} | {'plain LRU (d=4)':>18} | {'pinned LRU (d=8)':>18}")
    print("-" * 70)
    print(f"{'tip evictions':>25} | "
          f"{a['tip_evictions']:>18} | {b['tip_evictions']:>18}")
    print(f"{'honest tip misses':>25} | "
          f"{a['honest_misses']:>18} | {b['honest_misses']:>18}")
    print(f"{'attacker cold inits':>25} | "
          f"{a['attacker_misses']:>18} | {b['attacker_misses']:>18}")
    print(f"{'total verifier cost ms':>25} | "
          f"{a['total_cost_ms']:>18.2f} | {b['total_cost_ms']:>18.2f}")

    # The defining test: M-6 must keep tip_evictions at 0.
    r.expect(b["tip_evictions"] == 0,
             "[A-5] M-6 pinned cache keeps the active-tip pad pinned",
             f"tip_evictions(pinned)={b['tip_evictions']} (expected 0)")
    r.expect(b["honest_misses"] < a["honest_misses"] or a["honest_misses"] == 0,
             "[A-5] M-6 reduces honest-validation cold-init count",
             f"plain={a['honest_misses']} pinned={b['honest_misses']}")
    r.expect(a["tip_evictions"] > 0 or a["honest_misses"] > 0,
             "[A-5] plain LRU shows non-zero attacker impact "
             "(confirms vector exists in current code)",
             f"tip_evictions(plain)={a['tip_evictions']} "
             f"honest_misses(plain)={a['honest_misses']}")

    if args.output_csv:
        emit_csv(args.output_csv, [
            {"kind": "plain_lru_d4", "n": args.n_attacker, **a},
            {"kind": "pinned_lru_d8", "n": args.n_attacker, **b},
        ])

    print()
    print(BOLD("Recommendation (M-6 in B3POW-51-ATTACK-ANALYSIS.md)"))
    print(DIM("""
        - Modify src/crypto/b3pow_cache.{h,cpp} to add pin()/unpin()
          API and a separate pinned ordered map.
        - Raise consensus.b3pow_cache_depth on mainnet from 4 to 8.
        - ChainstateManager pins the best-header pad + 2 ancestors on
          every tip change.
        - New ctest case in src/test/b3pow_cache_tests.cpp asserts the
          pin invariant under stress (this script's logic, but in C++).
    """).strip())

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
