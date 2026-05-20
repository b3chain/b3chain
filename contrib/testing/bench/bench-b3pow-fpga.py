#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
B3PoW-Scratch *FPGA* throughput bench.

Drives a B3Miner-1 card (or any host running `b3miner-firmware`) over
the network and samples the hash counter (`B3_FPGA_REG_HASH_COUNT`)
exposed by the firmware's telemetry HTTP endpoint or by a Stratum-style
"work" submission cycle.

This bench is a thin host-side wrapper; the heavy lifting lives in
firmware (`contrib/miner/b3miner-firmware/`) and RTL
(`contrib/miner/b3miner-rtl/`). The wrapper enforces the same CSV /
JSON output schema as the other benches so charts can plot CPU vs
FPGA on the same axes (see `charts/render-charts.py`).

Two data sources are supported:

  1. **telemetry endpoint** (default): firmware exposes a
     `/telemetry/v1/snapshot` JSON over HTTP(S) with at least:
            { "hash_count": <int>, "uptime_s": <float>,
              "temp_c": <float>, "job_epoch": <int> }
     We poll at `--poll-interval`s and difference the counter.

  2. **dry-run** (`--dry-run`): emits a synthetic row with the algebraic
     expected hashrate from FPGA-FEASIBILITY.md so the bench runs
     end-to-end in CI even without hardware on the wire.

Usage:
    python3 bench-b3pow-fpga.py --endpoint http://b3miner-01.lan:80
    python3 bench-b3pow-fpga.py --dry-run --expected-hps 8e6
    python3 bench-b3pow-fpga.py --endpoint http://... --window 120

Outputs:
    - markdown table on stdout
    - results/<run-id>/bench-b3pow-fpga.csv
    - results/<run-id>/bench-b3pow-fpga-<ts>.json
    - results/<run-id>/bench-b3pow-fpga.latest.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from math import isnan, nan
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from bench_common import (  # noqa: E402
    BenchResult, BenchRow,
    Timer, md_table, measure_power_watts, percentile,
    write_csv, write_json,
)


def fetch_snapshot(endpoint: str, timeout: float = 5.0) -> dict:
    url = endpoint.rstrip("/") + "/telemetry/v1/snapshot"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body.decode("utf-8"))


def sample_hashrate(endpoint: str, window_s: float,
                    poll_interval_s: float) -> tuple[float, list[float], dict]:
    """Sample (avg_hps, per-tick_hps, last_snapshot) over `window_s`."""
    samples: list[float] = []
    snap0 = fetch_snapshot(endpoint)
    t_prev = time.perf_counter()
    cnt_prev = int(snap0["hash_count"])
    t_end = t_prev + window_s
    last = snap0
    while time.perf_counter() < t_end:
        time.sleep(poll_interval_s)
        snap = fetch_snapshot(endpoint)
        t_now = time.perf_counter()
        cnt_now = int(snap["hash_count"])
        dt = t_now - t_prev
        dcnt = cnt_now - cnt_prev
        if dt > 0:
            samples.append(dcnt / dt)
        t_prev, cnt_prev, last = t_now, cnt_now, snap
    total_hashes = int(last["hash_count"]) - int(snap0["hash_count"])
    total_dt = time.perf_counter() - (t_end - window_s)
    avg_hps = total_hashes / total_dt if total_dt > 0 else 0
    return avg_hps, samples, last


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", default=None,
                    help="firmware telemetry endpoint, e.g. http://b3miner-01.lan:80")
    ap.add_argument("--window", type=float, default=60.0,
                    help="sample window in seconds (default: 60)")
    ap.add_argument("--poll-interval", type=float, default=1.0,
                    help="seconds between counter polls (default: 1.0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="no hardware; emit a row from --expected-hps")
    ap.add_argument("--expected-hps", type=float, default=8.0e6,
                    help="dry-run hashrate placeholder (default: 8e6, "
                         "preliminary FPGA-FEASIBILITY.md estimate at 200 MHz, 8 lanes)")
    ap.add_argument("--card-name", default="b3miner-1",
                    help="identifier for the card (default: b3miner-1)")
    ap.add_argument("--run-id", default=None,
                    help="results bucket name (default: r0 or $B3POW_BENCH_RUN_ID)")
    ap.add_argument("--note", default="",
                    help="free-form note attached to every row")
    args = ap.parse_args()

    result = BenchResult(bench="bench-b3pow-fpga")

    if args.dry_run or not args.endpoint:
        if not args.dry_run and not args.endpoint:
            print("warn: no --endpoint and not --dry-run; "
                  "running synthetic measurement.", file=sys.stderr)
        avg_hps = float(args.expected_hps)
        note = (args.note or
                "dry-run synthetic; see doc/analysis/FPGA-FEASIBILITY.md for the algebra")
        result.notes.append("dry-run mode (no hardware)")
        result.add(BenchRow(
            bench="bench-b3pow-fpga", label=f"{args.card_name}-dry",
            backend="fpga-dry", threads=1, iterations=0,
            wall_s=0.0,
            hashes_per_s=avg_hps,
            ns_per_hash=1e9 / avg_hps if avg_hps else 0,
            p50_ms=0.0, p95_ms=0.0, p99_ms=0.0,
            j_per_hash=nan,
            note=note,
        ))
        result.summary["mode"] = "dry-run"
        result.summary["avg_hps"] = avg_hps
    else:
        print(f"\nB3PoW-Scratch FPGA bench  (endpoint={args.endpoint}, "
              f"window={args.window:.0f}s, poll={args.poll_interval:.2f}s)\n")
        print("  sampling telemetry ...")
        with Timer() as t:
            avg_hps, samples, last = sample_hashrate(
                args.endpoint, args.window, args.poll_interval)
        watts = measure_power_watts(t.elapsed)
        j_per_hash = (watts / avg_hps) if (watts and avg_hps) else nan

        # Convert per-tick hashrate samples to a "ms per million hashes"
        # latency-style metric so the percentile columns are meaningful.
        ms_per_M = [1000.0 / (s / 1e6) if s > 0 else 0.0 for s in samples]

        print(f"  observed avg : {avg_hps:>12,.0f} H/s")
        if samples:
            print(f"  observed p50 : {percentile(samples, 50):>12,.0f} H/s")
            print(f"  observed p95 : {percentile(samples, 95):>12,.0f} H/s")
            if "temp_c" in last:
                print(f"  die temp     : {last.get('temp_c', 'n/a')} C")
        result.notes.append(
            f"endpoint={args.endpoint}, window={args.window:.0f}s, "
            f"poll={args.poll_interval:.2f}s")
        if args.note:
            result.notes.append(args.note)
        result.add(BenchRow(
            bench="bench-b3pow-fpga", label=f"{args.card_name}-live",
            backend="fpga-live", threads=1, iterations=int(avg_hps * args.window),
            wall_s=args.window,
            hashes_per_s=avg_hps,
            ns_per_hash=1e9 / avg_hps if avg_hps else 0,
            p50_ms=percentile(ms_per_M, 50),
            p95_ms=percentile(ms_per_M, 95),
            p99_ms=percentile(ms_per_M, 99),
            j_per_hash=j_per_hash,
            note=args.note or "live-telemetry",
        ))
        result.summary["mode"] = "live"
        result.summary["avg_hps"] = avg_hps
        result.summary["samples_count"] = len(samples)

    csv_path = write_csv(result, args.run_id)
    json_path = write_json(result, args.run_id)
    print(f"\n  wrote {csv_path}")
    print(f"  wrote {json_path}\n")
    print(md_table(
        ["label", "backend", "H/s", "J/hash", "note"],
        [[r.label, r.backend, f"{r.hashes_per_s:,.0f}",
          "n/a" if isnan(r.j_per_hash) else f"{r.j_per_hash:.6f}",
          r.note] for r in result.rows],
    ))

    if result.summary.get("mode") == "dry-run":
        print("Note: dry-run mode. Real FPGA numbers require a B3Miner-1 card.\n"
              "      Set --endpoint to the firmware's HTTP telemetry URL.\n"
              "      See doc/analysis/FPGA-FEASIBILITY.md for the algebra.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as e:
        print(f"FPGA telemetry endpoint unreachable: {e}\n"
              "  Re-run with --dry-run to emit a synthetic row.",
              file=sys.stderr)
        sys.exit(2)
