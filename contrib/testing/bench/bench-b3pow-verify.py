#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
B3PoW-Scratch *verifier* latency bench.

Measures **single-block verification cost** -- how long a full node
spends checking the PoW of one inbound block -- across a deterministic
corpus of `--corpus-size` random headers (default 10 000).

This is the most operationally-important bench in the suite. The plan
target (SPEC §8.E): p95 < 50 ms per block on a modern x86_64 core, so
that PoW verification stays well under 1 % of the 10-minute block
interval and the chain is not DoS-able by malformed-header floods.

Two backends are measured (when available):

  - python-ref:  contrib/miner/b3miner-rtl/ref/b3pow_ref.py
  - cpp-cli:     out-of-process verify-b3pow.py harness, which can be
                 swapped for a future direct C++ verifier (b3chaind RPC
                 once one is added, or a standalone bench binary)

Use --backend=python-ref alone for a pre-build environment.

Outputs:
    - markdown table on stdout
    - results/<run-id>/bench-b3pow-verify.csv
    - results/<run-id>/bench-b3pow-verify-<ts>.json
    - results/<run-id>/bench-b3pow-verify.latest.json
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from math import isnan, nan
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from bench_common import (  # noqa: E402
    BenchResult, BenchRow,
    Timer, add_ref_import_path, deterministic_headers, deterministic_prev_hash,
    md_table, measure_power_watts, percentile, write_csv, write_json,
)

add_ref_import_path()
import b3pow_ref  # noqa: E402


def verify_python_ref(headers: list[bytes], prev_hash: bytes,
                      pristine_pad: bytes) -> list[float]:
    """For each header, measure b3pow_ref.b3pow_scratch latency in ms.

    Each call gets a fresh mutable copy of the pristine pad (mirrors
    pool/cpuminer pad-caching pattern).
    """
    latencies_ms: list[float] = []
    for h in headers:
        fresh = bytearray(pristine_pad)
        t0 = time.perf_counter()
        b3pow_ref.b3pow_scratch(h, prev_hash, pad=fresh)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    return latencies_ms


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-size", type=int, default=10_000,
                    help="number of distinct headers to verify (default: 10 000)")
    ap.add_argument("--seed", type=int, default=0xB3110002,
                    help="PRNG seed for the deterministic corpus")
    ap.add_argument("--quick", action="store_true",
                    help="shortcut: corpus-size=200 (sanity check, < 1 min)")
    ap.add_argument("--backend", choices=("python-ref", "all"),
                    default="python-ref",
                    help="which backend(s) to bench (default: python-ref)")
    ap.add_argument("--run-id", default=None,
                    help="results bucket name (default: r0 or $B3POW_BENCH_RUN_ID)")
    ap.add_argument("--note", default="",
                    help="free-form note attached to every row")
    args = ap.parse_args()

    n = 200 if args.quick else max(1, args.corpus_size)
    headers = list(deterministic_headers(n, seed=args.seed))
    prev_hash = deterministic_prev_hash()

    result = BenchResult(bench="bench-b3pow-verify")
    result.notes.append(f"corpus_size={n}, seed=0x{args.seed:08X}")
    if args.note:
        result.notes.append(args.note)

    print(f"\nB3PoW-Scratch verifier latency bench  (corpus={n}, "
          f"backend={args.backend})\n")

    # ---- python-ref --------------------------------------------------------
    print("  [python-ref] priming pristine pad ...")
    pristine = bytes(b3pow_ref.init_scratchpad(prev_hash))
    print(f"  [python-ref] verifying {n} headers ...")
    with Timer() as t:
        lat_ms = verify_python_ref(headers, prev_hash, pristine)
    hps = n / t.elapsed if t.elapsed else 0
    watts = measure_power_watts(t.elapsed)
    j_per_hash = (watts * t.elapsed) / n if (watts and n) else nan
    p50 = percentile(lat_ms, 50)
    p95 = percentile(lat_ms, 95)
    p99 = percentile(lat_ms, 99)
    mean_ms = statistics.fmean(lat_ms) if lat_ms else 0
    print(f"             {hps:>8.2f} H/s  "
          f"(mean={mean_ms:.1f}ms, p50={p50:.1f}ms, p95={p95:.1f}ms, p99={p99:.1f}ms)")

    result.add(BenchRow(
        bench="bench-b3pow-verify", label=f"python-ref-{n}",
        backend="python-ref", threads=1, iterations=n,
        wall_s=t.elapsed, hashes_per_s=hps,
        ns_per_hash=1e9 / hps if hps else 0,
        p50_ms=p50, p95_ms=p95, p99_ms=p99,
        j_per_hash=j_per_hash,
        note=args.note or "verifier-latency",
    ))

    # ---- target check ------------------------------------------------------
    TARGET_P95_MS = 50.0
    met_target = (p95 <= TARGET_P95_MS)
    result.summary["target_p95_ms"] = TARGET_P95_MS
    result.summary["observed_p95_ms"] = p95
    result.summary["meets_target"] = met_target
    print(f"\n  SPEC §8.E target: p95 < {TARGET_P95_MS:.0f} ms")
    print(f"  observed (this backend): {'PASS' if met_target else 'BELOW TARGET'} "
          f"(p95={p95:.1f} ms)")
    print("  Note: the SPEC target is for the C++ consensus impl, not the\n"
          "        Python reference. The reference impl is intentionally\n"
          "        slow; treat python-ref p95 as a CORRECTNESS row.\n")

    # ---- emit --------------------------------------------------------------
    csv_path = write_csv(result, args.run_id)
    json_path = write_json(result, args.run_id)
    print(f"  wrote {csv_path}")
    print(f"  wrote {json_path}\n")
    print(md_table(
        ["label", "backend", "iters", "H/s", "p50 ms", "p95 ms", "p99 ms", "J/hash"],
        [[r.label, r.backend, r.iterations,
          f"{r.hashes_per_s:.2f}",
          f"{r.p50_ms:.1f}", f"{r.p95_ms:.1f}", f"{r.p99_ms:.1f}",
          "n/a" if isnan(r.j_per_hash) else f"{r.j_per_hash:.3f}"]
         for r in result.rows],
    ))
    return 0 if met_target or args.backend == "python-ref" else 1


if __name__ == "__main__":
    sys.exit(main())
