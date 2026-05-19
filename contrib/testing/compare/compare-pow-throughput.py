#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Hash *primitive* throughput comparison: SHA-256 / SHA-256d vs BLAKE3 / BLAKE3d.

This measures the inner round-function throughput. It is NOT a
measurement of the chain's actual PoW (B3PoW-Scratch v1.1), which is
memory-hard - see
[`compare-b3pow-vs-sha256d.md`](compare-b3pow-vs-sha256d.md) for the
PoW-level comparison and
[`SPEC.md`](../../miner/b3miner-rtl/SPEC.md) for the algorithm.

For each algorithm, hash an 80-byte input (Bitcoin block-header size)
in a tight loop for a fixed wall-time window, single-threaded then
n-threaded. Records hashes/sec, ns/hash, and the speedup vs SHA-256d.

Outputs:
  - markdown table on stdout
  - results/pow-throughput-<host>-<ts>.json
  - updates results/latest.json
  - exit 0 always (this is a measurement, not a pass/fail audit)

Usage:
    python3 compare-pow-throughput.py
    python3 compare-pow-throughput.py --duration 5 --threads 1,4,8
    python3 compare-pow-throughput.py --no-portable     # skip BLAKE3 portable mode
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from compare_common import (  # noqa: E402
    CompareResult, write_result, md_table, have_blake3,
)


def hash_loop(hash_fn, data: bytes, duration: float) -> int:
    """Call hash_fn(data) repeatedly for `duration` seconds. Returns count."""
    t_end = time.perf_counter() + duration
    count = 0
    # Inline-hot loop. Local variables to avoid global lookups.
    fn = hash_fn
    d = data
    while time.perf_counter() < t_end:
        for _ in range(1024):
            fn(d)
        count += 1024
    return count


def make_sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def make_sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def make_blake3(data: bytes) -> bytes:
    import blake3
    return blake3.blake3(data).digest()


def make_blake3d(data: bytes) -> bytes:
    import blake3
    return blake3.blake3(blake3.blake3(data).digest()).digest()


def measure(label: str, fn, data: bytes, threads: int, duration: float) -> dict:
    """Run hash_loop in `threads` parallel workers; return aggregated stats."""
    if threads == 1:
        n = hash_loop(fn, data, duration)
    else:
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futs = [pool.submit(hash_loop, fn, data, duration) for _ in range(threads)]
            n = sum(f.result() for f in futs)
    hps = n / duration
    return {
        "algo":            label,
        "threads":         threads,
        "input_bytes":     len(data),
        "duration_s":      duration,
        "total_hashes":    n,
        "hashes_per_sec":  hps,
        "ns_per_hash":     1e9 / hps if hps else 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=3.0,
                    help="seconds per measurement (default: 3)")
    ap.add_argument("--threads", default="1,n",
                    help="comma list; 'n' expands to os.cpu_count() (default: 1,n)")
    ap.add_argument("--no-portable", action="store_true",
                    help="skip the BLAKE3_NO_SIMD measurement")
    ap.add_argument("--input-bytes", type=int, default=80,
                    help="bytes to hash per call (default: 80, Bitcoin header size)")
    args = ap.parse_args()

    if not have_blake3():
        print("error: pip3 install blake3 required for this comparison",
              file=sys.stderr)
        return 2

    # Resolve thread plan
    threads: list[int] = []
    for tok in args.threads.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok == "n":
            threads.append(os.cpu_count() or 1)
        else:
            threads.append(int(tok))

    data = b"\xa5" * args.input_bytes

    algos = [
        ("sha256",   make_sha256),
        ("sha256d",  make_sha256d),
        ("blake3",   make_blake3),
        ("blake3d",  make_blake3d),
    ]

    result = CompareResult(comparison="pow-throughput")
    result.notes.append(f"input size: {args.input_bytes} bytes")
    result.notes.append(f"duration per measurement: {args.duration:.1f}s")

    print(f"\nMeasuring hash throughput "
          f"(input={args.input_bytes}B, duration={args.duration:.1f}s)\n")

    for label, fn in algos:
        for t in threads:
            row = measure(label, fn, data, t, args.duration)
            result.add_row(**row)
            print(f"  {label:<10} threads={t:<3} -> {row['hashes_per_sec']:>14,.0f} h/s "
                  f"({row['ns_per_hash']:>8.1f} ns/hash)")

    if not args.no_portable:
        # BLAKE3 with SIMD disabled: set the env var BEFORE importing blake3 in
        # a subprocess. We can't toggle it in this process because blake3 is
        # already loaded. Spawn a child to measure.
        import subprocess
        portable_cmd = [sys.executable, __file__,
                        "--threads", ",".join(str(t) for t in threads),
                        "--duration", str(args.duration),
                        "--input-bytes", str(args.input_bytes),
                        "--no-portable",
                        "--__portable-internal"]
        env = dict(os.environ)
        env["BLAKE3_NO_SIMD"] = "1"
        try:
            child = subprocess.run(
                portable_cmd, env=env, check=False, capture_output=True, text=True,
                timeout=args.duration * len(algos) * len(threads) * 1.5 + 60,
            )
            for line in child.stdout.splitlines():
                # Reuse the parent's table format for rows beginning with a known algo.
                if line.strip().startswith("blake3"):
                    print(f"  [no-simd] {line.strip()}")
            # Best-effort parse of the JSON the child wrote (latest.json was updated).
            from compare_common import results_dir
            import json
            try:
                latest = json.loads((results_dir() / "latest.json").read_text(encoding="utf-8"))
                child_rows = latest.get("pow-throughput-portable", {}).get("rows", [])
                for r in child_rows:
                    rr = dict(r); rr["algo"] = rr["algo"] + "-portable"
                    result.add_row(**rr)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        except subprocess.TimeoutExpired:
            print("  [no-simd] (timeout — skipped)")

    # Internal-portable mode: write under a different comparison name.
    if "--__portable-internal" in sys.argv:
        result.comparison = "pow-throughput-portable"

    # Compute summary speedups.
    by_key = {}
    for r in result.rows:
        by_key[(r["algo"], r["threads"])] = r["hashes_per_sec"]
    sha256d_1 = by_key.get(("sha256d", 1))
    blake3d_1 = by_key.get(("blake3d", 1))
    if sha256d_1 and blake3d_1:
        result.summary["speedup_blake3d_vs_sha256d_single_thread"] = blake3d_1 / sha256d_1
    sha256d_n = by_key.get(("sha256d", os.cpu_count() or 1))
    blake3d_n = by_key.get(("blake3d", os.cpu_count() or 1))
    if sha256d_n and blake3d_n:
        result.summary["speedup_blake3d_vs_sha256d_multi_thread"] = blake3d_n / sha256d_n

    path = write_result(result)
    print(f"\n  wrote {path}")

    print()
    print(md_table(
        ["algorithm", "threads", "MH/s", "ns/hash", "vs sha256d (1T)"],
        [
            [r["algo"], r["threads"],
             f"{r['hashes_per_sec']/1e6:.2f}",
             f"{r['ns_per_hash']:.1f}",
             f"{(r['hashes_per_sec'] / sha256d_1):.2f}x" if sha256d_1 else "-"]
            for r in result.rows
        ],
    ))

    if "speedup_blake3d_vs_sha256d_single_thread" in result.summary:
        s1 = result.summary["speedup_blake3d_vs_sha256d_single_thread"]
        print(f"BLAKE3d vs SHA-256d (1 thread):  {s1:.2f}x")
    if "speedup_blake3d_vs_sha256d_multi_thread" in result.summary:
        sn = result.summary["speedup_blake3d_vs_sha256d_multi_thread"]
        print(f"BLAKE3d vs SHA-256d ({os.cpu_count()} threads): {sn:.2f}x")

    return 0


if __name__ == "__main__":
    sys.exit(main())
