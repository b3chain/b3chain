#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Shared utilities for the B3PoW-Scratch benchmark suite.

The B3PoW-Scratch bench suite measures the **full PoW** (memory-hard,
1 MB scratchpad, 16 384 RMW rounds per hash); it is distinct from
contrib/testing/compare/, which measures only the inner hash primitive
(BLAKE3 vs SHA-256 round-function throughput).

Use one of the two depending on what question you are answering:

  - "How fast does X compute B3PoW-Scratch?"            -> bench/
  - "How fast is the BLAKE3 primitive on this machine?" -> compare/

Provides:
  - host detection (CPU, OS, Python, BLAKE3 backend) for reproducibility
  - BenchRow / BenchResult dataclasses
  - CSV + JSON writers
  - percentile helpers (p50/p95/p99)
  - markdown-table helper
  - random-header generator (deterministic from a seed)

The file mirrors the patterns in `../compare/lib/compare_common.py` so
operators familiar with the compare suite can read the bench suite
without re-learning conventions.
"""
from __future__ import annotations

import csv
import json
import os
import platform
import random
import socket
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


# --------------------------------------------------------------------------- #
# Host detection                                                              #
# --------------------------------------------------------------------------- #

def _read_first(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def host_info() -> dict[str, Any]:
    """Return a small dict describing the machine for result
    reproducibility. Schema-compatible with `compare/lib/compare_common.host_info`.
    """
    info: dict[str, Any] = {
        "hostname":  socket.gethostname(),
        "platform":  platform.platform(),
        "python":    platform.python_version(),
        "cores":     os.cpu_count() or 1,
    }

    cpu_model = ""
    if Path("/proc/cpuinfo").is_file():
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    if not cpu_model:
        try:
            cpu_model = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                stderr=subprocess.DEVNULL,
            ).decode().strip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            cpu_model = platform.processor() or "unknown"
    info["cpu_model"] = cpu_model

    try:
        import blake3  # noqa: F401
        info["blake3_available"] = True
        try:
            info["blake3_version"] = getattr(blake3, "__version__", "unknown")
        except Exception:  # noqa: BLE001
            info["blake3_version"] = "unknown"
    except ImportError:
        info["blake3_available"] = False

    return info


# --------------------------------------------------------------------------- #
# Result dataclasses                                                          #
# --------------------------------------------------------------------------- #

@dataclass
class BenchRow:
    """One measurement row.

    Fields are intentionally flat so the CSV writer can serialise directly
    without re-flattening per call site.
    """
    bench:        str
    label:        str            # human-readable variant of the measurement
    backend:      str            # python-ref / cpp-consensus / fpga / verify
    threads:      int            # 1 for serial, n for n-way concurrency
    iterations:   int            # how many full PoW evaluations this row covers
    wall_s:       float          # total wall-clock seconds spent
    hashes_per_s: float          # full-PoW hashes per second
    ns_per_hash:  float          # 1 / hashes_per_s in nanoseconds
    p50_ms:       float          # per-hash latency p50, milliseconds (verify-style)
    p95_ms:       float
    p99_ms:       float
    j_per_hash:   float          # joules / hash, NaN unless --power passed
    note:         str            # free-form annotation (cache, --no-pad-cache, ...)


@dataclass
class BenchResult:
    bench:     str
    rows:      list[BenchRow]            = field(default_factory=list)
    summary:   dict[str, Any]            = field(default_factory=dict)
    host:      dict[str, Any]            = field(default_factory=host_info)
    timestamp: str                       = field(default_factory=lambda:
                                             datetime.now(timezone.utc).isoformat(timespec="seconds"))
    notes:     list[str]                 = field(default_factory=list)

    def add(self, row: BenchRow) -> None:
        self.rows.append(row)


# --------------------------------------------------------------------------- #
# Output paths                                                                #
# --------------------------------------------------------------------------- #

def bench_dir() -> Path:
    """Return contrib/testing/bench/."""
    return Path(__file__).resolve().parent.parent


def results_dir() -> Path:
    """Return contrib/testing/bench/results/, creating it if needed."""
    out = bench_dir() / "results"
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_results_dir(run_id: str | None = None) -> Path:
    """Return contrib/testing/bench/results/<run_id>/.

    run_id defaults to env $B3POW_BENCH_RUN_ID, then to 'r0' (the
    canonical 'first authoritative run' bucket the plan reserves).
    """
    rid = (run_id
           or os.environ.get("B3POW_BENCH_RUN_ID")
           or "r0")
    out = results_dir() / rid
    out.mkdir(parents=True, exist_ok=True)
    return out


# --------------------------------------------------------------------------- #
# Writers                                                                     #
# --------------------------------------------------------------------------- #

CSV_HEADERS = [
    "timestamp", "bench", "label", "backend", "threads",
    "iterations", "wall_s",
    "hashes_per_s", "ns_per_hash",
    "p50_ms", "p95_ms", "p99_ms",
    "j_per_hash", "note",
]


def write_csv(result: BenchResult, run_id: str | None = None) -> Path:
    """Append-or-create the canonical CSV for this bench.

    CSV name: <bench>.csv inside results/<run_id>/. Header is written
    when the file is new; subsequent runs append rows.
    """
    out_dir = run_results_dir(run_id)
    path = out_dir / f"{result.bench}.csv"
    new_file = not path.is_file()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(CSV_HEADERS)
        for row in result.rows:
            w.writerow([
                result.timestamp,
                row.bench, row.label, row.backend, row.threads,
                row.iterations, f"{row.wall_s:.6f}",
                f"{row.hashes_per_s:.4f}", f"{row.ns_per_hash:.2f}",
                f"{row.p50_ms:.4f}", f"{row.p95_ms:.4f}", f"{row.p99_ms:.4f}",
                f"{row.j_per_hash:.6f}", row.note,
            ])
    return path


def write_json(result: BenchResult, run_id: str | None = None) -> Path:
    """Persist the full result blob as JSON (host + summary + rows).

    File: <bench>-<timestamp>.json inside results/<run_id>/.  A pointer
    file `<bench>.latest.json` is also updated.
    """
    out_dir = run_results_dir(run_id)
    ts = result.timestamp.replace(":", "").replace("-", "").replace("+", "z")
    path = out_dir / f"{result.bench}-{ts}.json"
    payload = json.dumps({
        **{k: v for k, v in asdict(result).items() if k != "rows"},
        "rows": [asdict(r) for r in result.rows],
    }, indent=2)
    path.write_text(payload, encoding="utf-8")

    latest = out_dir / f"{result.bench}.latest.json"
    latest.write_text(payload, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Statistics                                                                  #
# --------------------------------------------------------------------------- #

def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (0 < pct < 100). Returns 0.0 on
    empty input rather than raising, so callers don't have to special-case
    no-measurement rows."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    d = k - f
    return s[f] + (s[c] - s[f]) * d


# --------------------------------------------------------------------------- #
# Random-header generation (deterministic)                                    #
# --------------------------------------------------------------------------- #

def deterministic_headers(n: int, seed: int = 0xB3110002) -> Iterable[bytes]:
    """Yield `n` 80-byte block headers with a fixed PRNG seed.

    Used by verify-latency benches so two runs on the same machine
    measure the *same* header corpus and differences are measurement
    noise, not corpus differences.
    """
    rng = random.Random(seed)
    for _ in range(n):
        yield bytes(rng.getrandbits(8) for _ in range(80))


def deterministic_prev_hash(seed: int = 0xB3C4A1F0) -> bytes:
    """Stable 32-byte prev_hash for benches that don't need to vary it."""
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(32))


# --------------------------------------------------------------------------- #
# Markdown table                                                              #
# --------------------------------------------------------------------------- #

def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Timing                                                                      #
# --------------------------------------------------------------------------- #

class Timer:
    """Tiny monotonic-clock context manager."""

    def __init__(self, label: str = ""):
        self.label = label
        self.elapsed = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.elapsed = time.perf_counter() - self._t0


# --------------------------------------------------------------------------- #
# Reference-impl loader                                                       #
# --------------------------------------------------------------------------- #

def add_ref_import_path() -> None:
    """Make `import b3pow_ref` work for any bench script.

    The reference impl lives at
    `contrib/miner/b3miner-rtl/ref/b3pow_ref.py`. We compute the path
    relative to this file rather than relative to the caller, so the
    addition is correct regardless of how the bench script was invoked.
    """
    here = Path(__file__).resolve()
    ref_dir = here.parent.parent.parent.parent / "miner" / "b3miner-rtl" / "ref"
    if str(ref_dir) not in sys.path:
        sys.path.insert(0, str(ref_dir))


# --------------------------------------------------------------------------- #
# Header packing helper                                                       #
# --------------------------------------------------------------------------- #

def make_header(version: int = 0x20000000,
                prev_hash: bytes = b"\x00" * 32,
                merkle_root: bytes = b"\x00" * 32,
                ntime: int = 0x67000000,
                nbits: int = 0x1d00ffff,
                nonce: int = 0) -> bytes:
    """Pack a Bitcoin-style 80-byte block header (little-endian).

    Defaults are sensible for repeatable benches; override per row.
    """
    assert len(prev_hash) == 32
    assert len(merkle_root) == 32
    return (struct.pack("<I", version)
            + prev_hash
            + merkle_root
            + struct.pack("<I", ntime)
            + struct.pack("<I", nbits)
            + struct.pack("<I", nonce))


# --------------------------------------------------------------------------- #
# Power-measurement placeholder                                               #
# --------------------------------------------------------------------------- #

def measure_power_watts(window_s: float, **_kw: Any) -> float | None:
    """Stub for in-band wall power measurement.

    The bench framework supports an optional `--power-meter` flag that
    operators wire up to a real power meter (USB power analyser,
    Killawatt-with-IR-read, INA219 on the FPGA card, etc.). The default
    implementation returns None; bench scripts then write `NaN` for
    `j_per_hash`. Override locally by setting B3POW_BENCH_POWER_CMD to a
    shell command that prints watts on stdout, or by editing this
    function.
    """
    cmd = os.environ.get("B3POW_BENCH_POWER_CMD")
    if not cmd:
        return None
    try:
        out = subprocess.check_output(cmd, shell=True, timeout=window_s + 5,
                                      text=True, stderr=subprocess.DEVNULL)
        return float(out.strip().split()[0])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None


__all__ = [
    "BenchRow", "BenchResult",
    "host_info",
    "bench_dir", "results_dir", "run_results_dir",
    "CSV_HEADERS",
    "write_csv", "write_json",
    "percentile",
    "deterministic_headers", "deterministic_prev_hash",
    "md_table",
    "Timer",
    "add_ref_import_path",
    "make_header",
    "measure_power_watts",
]
