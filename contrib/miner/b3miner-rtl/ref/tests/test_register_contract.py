import re
from pathlib import Path


RTL_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_ROOT = RTL_ROOT.parent / "b3miner-firmware"


def _c_define(text: str, name: str) -> int:
    match = re.search(rf"^#define\s+{name}\s+(0x[0-9A-Fa-f]+)", text, re.MULTILINE)
    assert match, name
    return int(match.group(1), 16)


def _sv_word(text: str, name: str) -> int:
    match = re.search(
        rf"{name}\s*=\s*7'h([0-9A-Fa-f]+)", text, re.MULTILINE
    )
    assert match, name
    return int(match.group(1), 16)


def test_firmware_and_rtl_register_maps_match():
    header = (
        FIRMWARE_ROOT
        / "components"
        / "b3_fpga"
        / "include"
        / "b3_fpga_regs.h"
    ).read_text(encoding="utf-8")
    params = (RTL_ROOT / "rtl" / "params_pkg.sv").read_text(encoding="utf-8")

    pairs = {
        "B3_FPGA_REG_NONCE_START": "REG_NONCE_START",
        "B3_FPGA_REG_NONCE_END": "REG_NONCE_END",
        "B3_FPGA_REG_NONCE_COUNT": "REG_NONCE_COUNT",
        "B3_FPGA_REG_SHARE_TARGET": "REG_TARGET_BASE",
        "B3_FPGA_REG_POW_HASH": "REG_POW_HASH_BASE",
        "B3_FPGA_REG_HEADER_PREFIX": "REG_HEADER_BASE",
    }
    for c_name, sv_name in pairs.items():
        assert _c_define(header, c_name) // 4 == _sv_word(params, sv_name)

    assert "B3_FPGA_CTRL_SHARE_ACK    (1u << 3)" in header
    assert "CTRL_SHARE_ACK    = 3" in params
    assert _c_define(header, "B3_FPGA_MAGIC") == 0xB3110003
    assert "REG_ID_MAGIC = 32'hB3110003" in params
