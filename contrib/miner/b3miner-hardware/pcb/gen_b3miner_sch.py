#!/usr/bin/env python3
"""Generate B3Miner-1 KiCad 8 hierarchical schematic skeleton from SCHEMATIC.md structure."""

from __future__ import annotations

import uuid
from pathlib import Path
from textwrap import dedent

VERSION = "20231120"
GENERATOR = "b3chain-gen"
PROJECT = "b3miner1"
ROOT_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# Stable sheet UUIDs (parent hierarchical sheet object == child sheet_instances path tail)
SHEET_UUIDS = {
    "01_power": "b1000001-0001-4000-8000-000000000001",
    "02_fpga": "b1000002-0002-4000-8000-000000000002",
    "03_host": "b1000003-0003-4000-8000-000000000003",
    "04_ethernet": "b1000004-0004-4000-8000-000000000004",
    "05_usb": "b1000005-0005-4000-8000-000000000005",
    "06_jtag": "b1000006-0006-4000-8000-000000000006",
    "07_io_led": "b1000007-0007-4000-8000-000000000007",
    "08_thermal": "b1000008-0008-4000-8000-000000000008",
}

# (sheet_file, sheet_name, page, spec_section, description, inputs, outputs)
SHEETS = [
    (
        "01_power.kicad_sch",
        "01_power",
        "2",
        "§3",
        "Power tree: 12V OR/eFuse, 5V/3.3V/1.8V/VCCINT bucks, TPS386596 supervisor",
        [],
        ["V12_BUS", "V5V0", "V3V3_SYS", "V1V8_AUX", "VCCINT", "PG_ALL"],
    ),
    (
        "02_fpga.kicad_sch",
        "02_fpga",
        "3",
        "§5",
        "XCKU5P-2FFVB676E, decoupling, slave-serial config straps, 200MHz LVDS XO",
        [
            "V12_BUS",
            "V3V3_SYS",
            "V1V8_AUX",
            "VCCINT",
            "PG_ALL",
            "FPGA_PROG_B",
            "FPGA_SPI_CLK",
            "FPGA_SPI_MOSI",
            "FPGA_SPI_CS",
            "JTAG_TCK",
            "JTAG_TDI",
            "JTAG_TDO",
            "JTAG_TMS",
            "JTAG_VREF",
        ],
        [
            "FPGA_SPI_MISO",
            "FPGA_SHARE_IRQ",
            "FPGA_INIT_B",
            "FPGA_DONE",
        ],
    ),
    (
        "03_host.kicad_sch",
        "03_host",
        "4",
        "§6",
        "ESP32-S3-WROOM-1-N16R8, reset/boot, ATECC608B I2C (GPIO1/2)",
        ["V3V3_SYS", "PG_ALL", "FPGA_SPI_MISO", "FPGA_SHARE_IRQ", "FPGA_INIT_B", "FPGA_DONE", "FAN_TACH"],
        [
            "FPGA_PROG_B",
            "FPGA_SPI_CLK",
            "FPGA_SPI_MOSI",
            "FPGA_SPI_CS",
            "W5500_SCK",
            "W5500_MOSI",
            "W5500_MISO",
            "W5500_CS",
            "W5500_INT",
            "W5500_RST",
            "USB_DP",
            "USB_DM",
            "LED_POWER",
            "LED_LINK",
            "LED_MINING",
            "FAN_PWM",
        ],
    ),
    (
        "04_ethernet.kicad_sch",
        "04_ethernet",
        "5",
        "§7",
        "W5500 LQFP-48, 25MHz xtal, Pulse J0011D01BNL magjack, Bob-Smith term",
        ["V12_BUS", "V3V3_SYS", "W5500_SCK", "W5500_MOSI", "W5500_MISO", "W5500_CS", "W5500_INT", "W5500_RST"],
        [],
    ),
    (
        "05_usb.kicad_sch",
        "05_usb",
        "6",
        "§8",
        "USB4105-GF-A USB-C 2.0, CC Rd, USBLC6-2P6, VBUS sense (DNI divider)",
        ["USB_DP", "USB_DM"],
        [],
    ),
    (
        "06_jtag.kicad_sch",
        "06_jtag",
        "7",
        "§9",
        "2x7 Xilinx JTAG header (FPGA only), 3.3V VREF",
        ["V3V3_SYS"],
        ["JTAG_TCK", "JTAG_TDI", "JTAG_TDO", "JTAG_TMS", "JTAG_VREF"],
    ),
    (
        "07_io_led.kicad_sch",
        "07_io_led",
        "8",
        "§10",
        "Front-panel PWR/LINK/MINE LEDs, reset/boot switches, FPGA-DONE indicator",
        ["V3V3_SYS", "LED_POWER", "LED_LINK", "LED_MINING", "FPGA_DONE"],
        [],
    ),
    (
        "08_thermal.kicad_sch",
        "08_thermal",
        "9",
        "§11",
        "Sunon 40mm 4-pin fan header, 12V feed, tach to ESP GPIO23",
        ["V12_BUS", "FAN_PWM"],
        ["FAN_TACH"],
    ),
]

BOM_NOTES = {
    "01_power": "TPS25940A, LM74700×2, TPS54360, TPS62933, TLV62568, 2×TPS546B24A, TPS386596",
    "02_fpga": "XCKU5P-2FFVB676E, SiT9501 200MHz LVDS, config straps M0-M2=1",
    "03_host": "ESP32-S3-WROOM-1-N16R8, ATECC608B-MAHDA-T",
    "04_ethernet": "W5500, NX2520SA-25M, J0011D01BNL magjack",
    "05_usb": "USB4105-GF-A, USBLC6-2P6",
    "06_jtag": "Wurth 61201421621 2×7 shrouded header",
    "07_io_led": "APT3216 LEDs, Omron B3U-1100P switches",
    "08_thermal": "MF40101V2-1000U-A99, JST PHR-4",
}


def uid() -> str:
    return str(uuid.uuid4())


def text_effects(justify: str = "left", indent: int = 6) -> str:
    pad = " " * indent
    return f"""{pad}(effects
{pad}  (font
{pad}    (size 1.27 1.27)
{pad}  )
{pad}  (justify {justify})
{pad})"""


def title_block(sheet_comment: str) -> str:
    return f"""  (title_block
    (title "B3Miner-1")
    (date "2026-05-21")
    (rev "r0")
    (company "b3chain")
    (comment 1 "XCKU5P-2FFVB676E + ESP32-S3 — Option A W5500")
    (comment 2 "Spec: ../SCHEMATIC.md")
    (comment 3 "{sheet_comment}")
    (comment 4 "Capture skeleton — contract house completes parts/wiring")
  )"""


def hierarchical_label(name: str, shape: str, x: float, y: float, angle: float = 0) -> str:
    return f"""
  (hierarchical_label "{name}"
    (shape {shape})
    (at {x} {y} {angle})
    {text_effects()}
    (uuid "{uid()}")
  )"""


def power_symbol(net: str, x: float, y: float, instance_path: str) -> str:
    """GND flag using KiCad stock power library."""
    lib_id = "power:GND"
    return f"""
  (symbol
    (lib_id "{lib_id}")
    (at {x} {y} 0)
    (unit 1)
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (dnp no)
    (fields_autoplaced)
    (uuid "{uid()}")
    (property "Reference" "#PWR"
      (at {x} {y - 3.81} 0)
      (effects
        (font
          (size 1.27 1.27)
        )
        (hide yes)
      )
    )
    (property "Value" "{net}"
      (at {x} {y + 3.556} 0)
      (effects
        (font
          (size 1.27 1.27)
        )
      )
    )
    (property "Footprint" ""
      (at {x} {y} 0)
      (effects
        (font
          (size 1.27 1.27)
        )
        (hide yes)
      )
    )
    (property "Datasheet" ""
      (at {x} {y} 0)
      (effects
        (font
          (size 1.27 1.27)
        )
        (hide yes)
      )
    )
    (instances
      (project "{PROJECT}"
        (path "{instance_path}"
          (reference "#PWR")
          (unit 1)
        )
      )
    )
  )"""


def note_text(x: float, y: float, lines: list[str]) -> str:
    body = "\\n".join(lines)
    return f"""
  (text "{body}"
    (exclude_from_sim no)
    (at {x} {y} 0)
    (effects
      (font
        (size 1.27 1.27)
      )
      (justify left top)
    )
    (uuid "{uid()}")
  )"""


def child_sheet(
    filename: str,
    sheet_name: str,
    page: str,
    spec: str,
    description: str,
    inputs: list[str],
    outputs: list[str],
    parent_path: str,
    file_uuid: str,
) -> str:
    labels: list[str] = []
    y = 30.48
    for net in inputs:
        labels.append(hierarchical_label(net, "input", 20.32, y, 180))
        y += 7.62
    y = 30.48
    for net in outputs:
        labels.append(hierarchical_label(net, "output", 200.66, y, 0))
        y += 7.62

    notes = [
        f"B3Miner-1 — {sheet_name}",
        f"SCHEMATIC.md {spec}: {description}",
        f"Key parts: {BOM_NOTES.get(sheet_name, 'see spec')}",
        "Hierarchical labels match kicad-bringup.md §2.1 — do not rename without updating b3miner1.kicad_pro netclass_patterns.",
        "Place symbols from lib/b3chain.kicad_sym (contract house).",
    ]

    parts = [
        f"(kicad_sch",
        f'  (version {VERSION})',
        f'  (generator "{GENERATOR}")',
        f'  (generator_version "8.0")',
        f'  (uuid "{file_uuid}")',
        f'  (paper "A3")',
        title_block(f"{sheet_name} — {spec}"),
        f"  (lib_symbols)",
        *labels,
        power_symbol("GND", 25.4, 177.8, parent_path),
        note_text(25.4, 25.4, notes),
        f"""  (sheet_instances
    (path "{parent_path}"
      (page "{page}")
    )
  )
)""",
    ]
    return "\n".join(parts)


def sheet_pin(name: str, shape: str, at_x: float, at_y: float, angle: float) -> str:
    return f"""
    (pin "{name}" {shape}
      (at {at_x} {at_y} {angle})
{text_effects(indent=6)}
      (uuid "{uid()}")
    )"""


def root_sheet() -> str:
    sheet_blocks: list[str] = []
    x0, y0 = 25.4, 25.4
    col_w, row_h = 95.0, 55.0
    positions = [
        (0, 0),
        (1, 0),
        (2, 0),
        (3, 0),
        (0, 1),
        (1, 1),
        (2, 1),
        (3, 1),
    ]

    for idx, (fname, sname, page, spec, desc, inputs, outputs) in enumerate(SHEETS):
        su = SHEET_UUIDS[sname]
        col, row = positions[idx]
        at_x = x0 + col * col_w
        at_y = y0 + row * row_h
        w, h = 50.0, max(25.4, 7.62 * (len(inputs) + len(outputs) + 1))

        pins: list[str] = []
        py = at_y + 7.62
        for net in inputs:
            pins.append(sheet_pin(net, "input", at_x, py, 180))
            py += 5.08
        py = at_y + 7.62
        for net in outputs:
            pins.append(sheet_pin(net, "output", at_x + w, py, 0))
            py += 5.08

        pins_str = "".join(pins)
        sheet_blocks.append(
            f"""
  (sheet
    (at {at_x} {at_y})
    (size {w} {h})
    (fields_autoplaced)
    (stroke
      (width 0.1524)
      (type solid)
    )
    (fill
      (color 0 0 0 0.0000)
    )
    (uuid "{su}")
    (property "Sheetname" "{sname}"
      (at {at_x} {at_y - 2.54} 0)
      (effects
        (font
          (size 1.524 1.524)
        )
        (justify left bottom)
      )
    )
    (property "Sheetfile" "{fname}"
      (at {at_x} {at_y + h + 2.54} 0)
      (effects
        (font
          (size 1.524 1.524)
        )
        (justify left top)
      )
    )
    {pins_str}
    (instances
      (project "{PROJECT}"
        (path "/{ROOT_UUID}"
          (page "{page}")
        )
      )
    )
  )"""
        )

    cover = note_text(
        25.4,
        180.0,
        [
            "B3Miner-1 rev A — hierarchical root",
            "Spec: ../SCHEMATIC.md (R0, Option A W5500)",
            "Net names per Appendix A — tied to b3miner1.kicad_pro net classes",
            "Inter-sheet nets: see kicad-bringup.md §2.1",
            "Contract house: capture parts inside each subsheet, then ERC/DRC",
        ],
    )

    parts = [
        "(kicad_sch",
        f"  (version {VERSION})",
        f'  (generator "{GENERATOR}")',
        f'  (generator_version "8.0")',
        f'  (uuid "{ROOT_UUID}")',
        '  (paper "A3")',
        title_block("root / cover"),
        "  (lib_symbols)",
        *sheet_blocks,
        cover,
        """  (sheet_instances
    (path "/"
      (page "1")
    )
  )
)""",
    ]
    return "\n".join(parts)


def main() -> None:
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    out.mkdir(parents=True, exist_ok=True)

    root_path = f"/{ROOT_UUID}"
    (out / "b3miner1.kicad_sch").write_text(root_sheet(), encoding="utf-8")
    print(f"Wrote {out / 'b3miner1.kicad_sch'}")

    for fname, sname, page, spec, desc, inputs, outputs in SHEETS:
        sheet_path = f"/{ROOT_UUID}/{SHEET_UUIDS[sname]}"
        file_uuid = uid()
        content = child_sheet(
            fname, sname, page, spec, desc, inputs, outputs, sheet_path, file_uuid
        )
        path = out / fname
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
