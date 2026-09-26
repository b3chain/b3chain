#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROFILE = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "xcku5p_b3miner"


def record(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


sources = sorted((ROOT / "rtl").glob("*.sv"))
sources += [
    PROFILE / "rtl" / "xcku5p_b3miner_top.sv",
    PROFILE / "xdc" / "xcku5p_b3miner_pins.xdc",
    PROFILE / "xdc" / "xcku5p_b3miner_timing.xdc",
    PROFILE / "board_contract.json",
]
sources += sorted((PROFILE / "build").glob("*.tcl"))
sources += [PROFILE / "build" / "create_manifest.py"]
sources += sorted((PROFILE / "host").glob("*"))
outputs = [
    BUILD / "xcku5p_b3miner.bit",
    BUILD / "xcku5p_b3miner_routed.dcp",
]
outputs += sorted((BUILD / "reports").glob("*.rpt"))

missing = [str(path) for path in sources + outputs if not path.is_file()]
if missing:
    raise SystemExit("missing manifest input:\n" + "\n".join(missing))

manifest = {
    "schema_version": 1,
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "board": "XCKU5P-2FFVB676",
    "part": "xcku5p-ffvb676-2-e",
    "top": "xcku5p_b3miner_top",
    "spec_version": "0x00010101",
    "register_magic": "0xB3110003",
    "sources": [record(path) for path in sources],
    "outputs": [record(path) for path in outputs],
}
(BUILD / "manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
print(BUILD / "manifest.json")
