#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Shared utilities for the BLAKE3-vs-SHA-256 comparative suite.

Provides:
  - host info (CPU model, core count, OS) for reproducibility
  - Timer: monotonic-clock context manager
  - write_result(): canonical JSON writer + latest.json updater
  - load_baseline(): reads baseline numbers used by the CI regression check
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Host detection
# ---------------------------------------------------------------------------

def _read_first(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def host_info() -> dict[str, Any]:
    """Return a small dict describing the machine for result reproducibility."""
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python":   platform.python_version(),
        "cores":    os.cpu_count() or 1,
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
    return info


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------

class Timer:
    """Tiny monotonic-clock context manager. Nanosecond resolution where supported."""

    def __init__(self, label: str = ""):
        self.label = label
        self.elapsed = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.elapsed = time.perf_counter() - self._t0


# ---------------------------------------------------------------------------
# Result schema and JSON writer
# ---------------------------------------------------------------------------

@dataclass
class CompareResult:
    comparison: str
    rows:       list[dict[str, Any]] = field(default_factory=list)
    summary:    dict[str, Any]       = field(default_factory=dict)
    host:       dict[str, Any]       = field(default_factory=host_info)
    timestamp:  str                  = field(default_factory=lambda:
                                              datetime.now(timezone.utc).isoformat(timespec="seconds"))
    notes:      list[str]            = field(default_factory=list)

    def add_row(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)


def results_dir() -> Path:
    """Return contrib/testing/compare/results/, creating it if needed."""
    here = Path(__file__).resolve()
    out = here.parent.parent / "results"
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_result(result: CompareResult) -> Path:
    """Persist result JSON and update latest.json. Returns the path written."""
    out_dir = results_dir()
    ts = result.timestamp.replace(":", "").replace("-", "").replace("+", "z")
    fn = f"{result.comparison}-{ts}.json"
    path = out_dir / fn
    payload = json.dumps(asdict(result), indent=2)
    path.write_text(payload, encoding="utf-8")

    latest = out_dir / "latest.json"
    # Update aggregate latest.json (a dict keyed by comparison name).
    if latest.is_file():
        try:
            current = json.loads(latest.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except json.JSONDecodeError:
            current = {}
    else:
        current = {}
    current[result.comparison] = asdict(result)
    latest.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Baseline loader (for CI)
# ---------------------------------------------------------------------------

def load_baseline() -> dict[str, Any]:
    """Return contents of baseline.json or {} if not present."""
    here = Path(__file__).resolve()
    p = here.parent.parent / "baseline.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Markdown table helper
# ---------------------------------------------------------------------------

def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Lazy hash-library detection
# ---------------------------------------------------------------------------

def have_blake3() -> bool:
    try:
        import blake3  # noqa: F401
        return True
    except ImportError:
        return False


def have_bitcoind() -> bool:
    return shutil.which("bitcoind") is not None


def have_b3chaind() -> bool:
    return shutil.which("b3chaind") is not None
