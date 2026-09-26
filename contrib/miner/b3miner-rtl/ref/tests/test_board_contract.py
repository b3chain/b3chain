import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "boards" / "xcku5p-2ffvb676"


def test_xcku5p_board_contract_and_xdc_match():
    contract = json.loads((PROFILE / "board_contract.json").read_text(encoding="utf-8"))
    xdc = (PROFILE / "xdc" / "xcku5p_b3miner_pins.xdc").read_text(encoding="utf-8")

    assert contract["vivado_part"] == "xcku5p-ffvb676-2-e"
    assert contract["clock"]["period_ns"] == 10.0
    assert contract["clock"]["diff_term"] is False
    assert contract["spi"]["max_frequency_hz"] == 5_000_000

    ports = {row["port"]: row for row in contract["ports"]}
    assert set(ports) == {
        "sys_clk_p",
        "sys_clk_n",
        "spi_sck",
        "spi_mosi",
        "spi_miso",
        "spi_csn",
        "share_irq",
        "user_key_n",
        "led_busy_n",
        "led_share_n",
    }
    for port, row in ports.items():
        assert f"PACKAGE_PIN {row['ball']} [get_ports {port}]" in xdc
        assert row["iostandard"] in xdc

    assert contract["configuration"]["esp32_selectmap"] == "not_wired"
    assert contract["configuration"]["onboard_qspi"] == "present_not_authorized"
    assert "PROGRAM_B" not in xdc
    assert "INIT_B" not in xdc
    assert "DONE" not in xdc

    build_tcl = (PROFILE / "build" / "build_board.tcl").read_text(
        encoding="utf-8"
    )
    assert "program_hw_devices" not in build_tcl
    assert "write_cfgmem" not in build_tcl
    program_tcl = (PROFILE / "build" / "program_volatile.tcl").read_text(
        encoding="utf-8"
    )
    assert "program_hw_devices" in program_tcl
    assert "cfgmem" not in program_tcl.lower()
