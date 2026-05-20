#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
B3PoW-Scratch v1.1 *CPU reference* throughput bench.

Measures hashes/sec of the authoritative Python reference impl
(`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`) under a few realistic
configurations:

    1. cold:      no scratchpad cache, full init per hash
    2. warm:      shared scratchpad cache (pad init amortised across nonces)
    3. multi-thread warm: same as warm, fan-out over `--threads`

The Python reference is deliberately slow (single-digit H/s/core); its
purpose is byte-for-byte correctness, not competitive mining. This bench
publishes the slow numbers honestly. See `methodology.md` § 1 for why.

Outputs:
    - markdown table on stdout
    - results/<run-id>/bench-b3pow-cpu.csv  (one row per measurement)
    - results/<run-id>/bench-b3pow-cpu-<ts>.json
    - results/<run-id>/bench-b3pow-cpu.latest.json

Usage:
    python3 bench-b3pow-cpu.py
    python3 bench-b3pow-cpu.py --duration 30 --threads 1,4,8
    python3 bench-b3pow-cpu.py --iterations 10 --no-multi
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from math import isnan, nan
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from bench_common import (  # noqa: E402
    BenchResult, BenchRow,
    Timer, add_ref_import_path, deterministic_prev_hash,
    make_header, md_table, measure_power_watts, percentile,
    write_csv, write_json,
)

add_ref_import_path()
import b3pow_ref  # noqa: E402


def measure_cold(iterations: int) -> tuple[float, list[float]]:
    """Iterate `iterations` hashes WITHOUT a pad cache (init each call)."""
    prev = deterministic_prev_hash()
    latencies_ms: list[float] = []
    with Timer() as t:
        for n in range(iterations):
            hdr = make_header(prev_hash=prev, nonce=n)
            t0 = time.perf_counter()
            b3pow_ref.b3pow_scratch(hdr, prev)  # discards result
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    return t.elapsed, latencies_ms


def measure_warm(iterations: int) -> tuple[float, list[float]]:
    """Iterate `iterations` hashes against a SHARED pristine pad.

    Mirrors the production pattern in
    `contrib/miner/b3chain-cpuminer.py::PadCache`: the pad is
    initialised once for prev_hash, then a fresh mutable copy is handed
    out per nonce (`b3pow_ref.b3pow_scratch` mutates `pad` in place).
    """
    prev = deterministic_prev_hash()
    pristine = bytes(b3pow_ref.init_scratchpad(prev))
    latencies_ms: list[float] = []
    with Timer() as t:
        for n in range(iterations):
            hdr = make_header(prev_hash=prev, nonce=n)
            fresh = bytearray(pristine)
            t0 = time.perf_counter()
            b3pow_ref.b3pow_scratch(hdr, prev, pad=fresh)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    return t.elapsed, latencies_ms


def measure_warm_thread(iterations: int) -> tuple[float, list[float]]:
    """Per-thread warm measurement helper (used by the fan-out path)."""
    return measure_warm(iterations)


def parse_threads(spec: str) -> list[int]:
    out: list[int] = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok == "n":
            out.append(os.cpu_count() or 1)
        else:
            out.append(int(tok))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iterations", type=int, default=5,
                    help="full PoW evaluations per configuration "
                         "(default: 5; Python ref ≈ 5-10 H/s/core, "
                         "so 5 keeps the total under ~10 s on most CPUs)")
    ap.add_argument("--threads", default="1,n",
                    help="comma list; 'n' expands to os.cpu_count() (default: 1,n)")
    ap.add_argument("--no-multi", action="store_true",
                    help="skip the multi-thread fan-out measurement")
    ap.add_argument("--no-cold", action="store_true",
                    help="skip the cold-cache measurement (slow, repeats pad init)")
    ap.add_argument("--run-id", default=None,
                    help="results bucket name (default: r0 or $B3POW_BENCH_RUN_ID)")
    ap.add_argument("--note", default="",
                    help="free-form note attached to every row")
    args = ap.parse_args()

    iterations: int = max(1, args.iterations)
    threads_list = parse_threads(args.threads) if not args.no_multi else [1]
    threads_list = sorted(set(threads_list))

    result = BenchResult(bench="bench-b3pow-cpu")
    result.notes.append(
        f"iterations={iterations}, threads={threads_list}, "
        f"cold={'off' if args.no_cold else 'on'}, "
        f"multi={'off' if args.no_multi else 'on'}"
    )
    if args.note:
        result.notes.append(args.note)

    print(f"\nB3PoW-Scratch CPU reference bench  "
          f"(iterations={iterations}, threads={threads_list})\n")

    # ----- cold ------------------------------------------------------------
    if not args.no_cold:
        print("  [cold]    no pad cache, full init per hash ...")
        wall, lat_ms = measure_cold(iterations)
        hps = iterations / wall if wall else 0
        watts = measure_power_watts(wall)
        j_per_hash = (watts * wall) / iterations if (watts and iterations) else nan
        row = BenchRow(
            bench="bench-b3pow-cpu", label="cold-no-cache",
            backend="python-ref", threads=1, iterations=iterations,
            wall_s=wall, hashes_per_s=hps,
            ns_per_hash=1e9 / hps if hps else 0,
            p50_ms=percentile(lat_ms, 50),
            p95_ms=percentile(lat_ms, 95),
            p99_ms=percentile(lat_ms, 99),
            j_per_hash=j_per_hash,
            note=args.note or "cold-cache",
        )
        result.add(row)
        print(f"             {hps:>8.2f} H/s  "
              f"(p50={row.p50_ms:.0f}ms, p95={row.p95_ms:.0f}ms, p99={row.p99_ms:.0f}ms)")

    # ----- warm single thread ---------------------------------------------
    print("  [warm 1]  shared pristine pad, single thread ...")
    wall, lat_ms = measure_warm(iterations)
    hps = iterations / wall if wall else 0
    watts = measure_power_watts(wall)
    j_per_hash = (watts * wall) / iterations if (watts and iterations) else nan
    row = BenchRow(
        bench="bench-b3pow-cpu", label="warm-1t",
        backend="python-ref", threads=1, iterations=iterations,
        wall_s=wall, hashes_per_s=hps,
        ns_per_hash=1e9 / hps if hps else 0,
        p50_ms=percentile(lat_ms, 50),
        p95_ms=percentile(lat_ms, 95),
        p99_ms=percentile(lat_ms, 99),
        j_per_hash=j_per_hash,
        note=args.note or "warm-cache",
    )
    result.add(row)
    print(f"             {hps:>8.2f} H/s  "
          f"(p50={row.p50_ms:.0f}ms, p95={row.p95_ms:.0f}ms, p99={row.p99_ms:.0f}ms)")

    # ----- warm multi-thread ----------------------------------------------
    for t in threads_list:
        if t <= 1:
            continue
        print(f"  [warm {t}]  shared pristine pad, {t}-way fan-out ...")
        per_thread = max(1, iterations)
        with ThreadPoolExecutor(max_workers=t) as pool, Timer() as tm:
            futures = [pool.submit(measure_warm_thread, per_thread)
                       for _ in range(t)]
            # Drain wall results so the threads finish before tm.elapsed
            # is read; we don't keep the per-thread walls because the
            # outer Timer captures the aggregate wall time.
            for f in futures:
                f.result()
            sub_lats: list[float] = []
            for f in futures:
                sub_lats.extend(f.result()[1])  # type: ignore[index]
        total_iters = per_thread * t
        hps = total_iters / tm.elapsed if tm.elapsed else 0
        watts = measure_power_watts(tm.elapsed)
        j_per_hash = (watts * tm.elapsed) / total_iters if (watts and total_iters) else nan
        row = BenchRow(
            bench="bench-b3pow-cpu", label=f"warm-{t}t",
            backend="python-ref", threads=t, iterations=total_iters,
            wall_s=tm.elapsed, hashes_per_s=hps,
            ns_per_hash=1e9 / hps if hps else 0,
            p50_ms=percentile(sub_lats, 50),
            p95_ms=percentile(sub_lats, 95),
            p99_ms=percentile(sub_lats, 99),
            j_per_hash=j_per_hash,
            note=args.note or f"warm-cache-fanout-{t}",
        )
        result.add(row)
        print(f"             {hps:>8.2f} H/s  "
              f"(p50={row.p50_ms:.0f}ms, p95={row.p95_ms:.0f}ms, p99={row.p99_ms:.0f}ms)")

    # ----- emit ------------------------------------------------------------
    csv_path = write_csv(result, args.run_id)
    json_path = write_json(result, args.run_id)
    print(f"\n  wrote {csv_path}")
    print(f"  wrote {json_path}\n")
    print(md_table(
        ["label", "backend", "threads", "H/s", "p50 ms", "p95 ms", "p99 ms", "J/hash"],
        [[r.label, r.backend, r.threads,
          f"{r.hashes_per_s:.2f}",
          f"{r.p50_ms:.0f}", f"{r.p95_ms:.0f}", f"{r.p99_ms:.0f}",
          "n/a" if isnan(r.j_per_hash) else f"{r.j_per_hash:.3f}"]
         for r in result.rows],
    ))

    print("Note: Python reference impl is intentionally slow (single-digit\n"
          "      H/s/core). For competitive mining rates see\n"
          "      bench-b3pow-cpp (C++ consensus impl) or\n"
          "      bench-b3pow-fpga (B3Miner-1 FPGA card).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
