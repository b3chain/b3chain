# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
Save Report: writes report-YYYYMMDD-HHMMSS.{json,md} next to the UI.

JSON is the source of truth (machine-parseable); the markdown is rendered
from the same data for easy email/paste.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import platform
import sys
from typing import Iterable, List, Tuple

from .capability_check import CapabilityProbe
from .test_definitions import TestCase, TestResult


def _host_info() -> dict:
    blake3_version = "missing"
    try:
        spec = importlib.util.find_spec("blake3")
        if spec is not None:
            import blake3 as _b3
            blake3_version = getattr(_b3, "__version__", "unknown")
    except Exception:
        pass

    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "blake3_version": blake3_version,
        "executable": sys.executable,
    }


def build_report(
    probe: CapabilityProbe,
    rows: Iterable[Tuple[TestCase, TestResult]],
) -> dict:
    """Compose the in-memory report dict that gets serialised to JSON."""
    capabilities = {}
    for cap in probe.all():
        capabilities[cap.key] = {
            "label": cap.label,
            "present": cap.present,
            "detail": cap.detail,
        }

    test_rows = []
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0,
              "RUNNING": 0, "PENDING": 0}
    total_s = 0.0
    for case, result in rows:
        counts[result.status] = counts.get(result.status, 0) + 1
        total_s += result.duration_s or 0.0
        test_rows.append({
            "id": case.id,
            "name": case.name,
            "description": case.description,
            "status": result.status,
            "metric": result.metric,
            "detail": result.detail,
            "duration_s": round(result.duration_s, 3) if result.duration_s else 0.0,
            "stdout_tail": result.stdout_tail,
        })

    return {
        "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": _host_info(),
        "capabilities": capabilities,
        "tests": test_rows,
        "summary": {
            "passed": counts.get("PASS", 0),
            "failed": counts.get("FAIL", 0),
            "skipped": counts.get("SKIP", 0),
            "errored": counts.get("ERROR", 0),
            "total_s": round(total_s, 2),
        },
    }


def render_markdown(report: dict) -> str:
    out: List[str] = []
    out.append("# b3chain CPU miner test report")
    out.append("")
    out.append(f"- **Timestamp:** {report['ts']}")
    out.append(f"- **OS:** {report['host']['os']}  ({report['host']['machine']})")
    out.append(f"- **Python:** {report['host']['python']}")
    out.append(f"- **blake3:** {report['host']['blake3_version']}")
    out.append("")

    s = report["summary"]
    out.append("## Summary")
    out.append("")
    out.append(f"- PASS: **{s['passed']}**")
    out.append(f"- FAIL: **{s['failed']}**")
    out.append(f"- SKIP: **{s['skipped']}**")
    out.append(f"- ERROR: **{s['errored']}**")
    out.append(f"- Total runtime: **{s['total_s']}s**")
    out.append("")

    out.append("## Capabilities")
    out.append("")
    out.append("| Capability | Present | Detail |")
    out.append("|---|---|---|")
    for key, val in report["capabilities"].items():
        mark = "OK" if val["present"] else "missing"
        detail = (val["detail"] or "").replace("|", "/")
        out.append(f"| {val['label']} | {mark} | {detail} |")
    out.append("")

    out.append("## Tests")
    out.append("")
    out.append("| # | Name | Status | Metric | Duration | Detail |")
    out.append("|---|---|---|---|---|---|")
    for t in report["tests"]:
        detail = (t.get("detail") or "").replace("|", "/").replace("\n", " ")
        if len(detail) > 80:
            detail = detail[:77] + "..."
        out.append(
            f"| {t['id']} | {t['name']} | {t['status']} | {t['metric']} | "
            f"{t['duration_s']}s | {detail} |"
        )
    out.append("")

    # Stdout tails for failed tests
    failed = [t for t in report["tests"]
              if t["status"] in ("FAIL", "ERROR") and t.get("stdout_tail")]
    if failed:
        out.append("## Failed test output (tails)")
        out.append("")
        for t in failed:
            out.append(f"### {t['id']}. {t['name']} ({t['status']})")
            out.append("")
            out.append("```")
            out.append(t["stdout_tail"].rstrip())
            out.append("```")
            out.append("")

    return "\n".join(out) + "\n"


def write_report(
    out_dir: str,
    probe: CapabilityProbe,
    rows: Iterable[Tuple[TestCase, TestResult]],
) -> Tuple[str, str]:
    """Write report-YYYYMMDD-HHMMSS.{json,md} into out_dir. Returns (json, md) paths."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rows_list = list(rows)
    report = build_report(probe, rows_list)

    json_path = os.path.join(out_dir, f"report-{stamp}.json")
    md_path = os.path.join(out_dir, f"report-{stamp}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))

    return json_path, md_path
