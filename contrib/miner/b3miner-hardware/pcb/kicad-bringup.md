# KiCad project bringup — B3Miner-1

Step-by-step instructions to take [`b3miner1.kicad_pro`](b3miner1.kicad_pro)
from skeleton to a working capture + layout starter. Every value listed
here is pre-derived from [`../SCHEMATIC.md`](../SCHEMATIC.md) — paste
them into the KiCad GUI dialogs rather than re-reading the spec doc and
translating. Tested against **KiCad 8.0.4**.

> Why this file exists: a `.kicad_pro` JSON pre-encodes net classes and
> design rules, but the layer stack-up, board outline, mounting holes,
> and hierarchical sheet structure live inside `.kicad_pcb` and
> `.kicad_sch` files that need component-level work to build sensibly.
> The bringup below is the 30-minute GUI checklist that gets a layout
> engineer from zero to "ready to capture schematic".

## What `b3miner1.kicad_pro` already gives you

When you open the project, the following are pre-set:

- **9 net classes** with track widths, clearances, and diff-pair geometry
  matching [`../SCHEMATIC.md`](../SCHEMATIC.md) §13:
  - `USB_90R_DIFF` — USB 2.0 D±  (0.18 mm trace, 0.13 mm gap → 90 Ω diff on 4 mil prepreg)
  - `ETH_100R_DIFF` — W5500 ↔ magjack TX/RX pairs (0.2 / 0.18)
  - `LVDS_CLK_100R_DIFF` — 200 MHz SiT9501 to KU5P MRCC pair
  - `GTH_100R_DIFF_DNI` — future SFP+ uplink, parked
  - `SPI_FPGA` — 25 MHz SPI bus
  - `PWR_3V3` — 0.5 mm trace minimum
  - `PWR_VCCINT` — 1.5 mm trace minimum, fed via 2 oz copper plane
  - `PWR_12V_BUS` — 1.0 mm trace minimum
- **Auto-pattern assignments** that route a net to its class by name
  (e.g. any net matching `/USB_D*` → `USB_90R_DIFF`). Naming
  convention is locked in [`../SCHEMATIC.md`](../SCHEMATIC.md)
  Appendix A.
- **Project text variables** for `${BOARD_NAME}`, `${BOARD_REV}`,
  `${FPGA_PART}`, etc. — referenced in title blocks and BOM exports.
- **DRC rules** at standard 8-layer / 4 mil fab class. Min track 0.1016
  mm = 4 mil, min via 0.45 mm OD, min annular ring 0.1 mm.
- **BOM export format** pointing at `fab/bom_${BOARD_REV}.csv`.
- **Plot directory** pointing at `fab/`.

## Step 1 — Create the board (`b3miner1.kicad_pcb`)

In KiCad → File → New Board (saves alongside the `.kicad_pro`).

### 1.1 Page settings

| Field | Value |
|---|---|
| Paper size | A3 landscape |
| Title | B3Miner-1 |
| Rev | ${BOARD_REV} |
| Date | (current) |
| Company | b3chain |
| Comment 1 | XCKU5P-2FFVB676E + ESP32-S3 mining card |
| Comment 2 | Spec: ../SCHEMATIC.md |

### 1.2 Board stack-up (Board Setup → Physical Stackup)

8-layer, 1.6 mm total per [`../SCHEMATIC.md`](../SCHEMATIC.md) §13.1:

| # | Name      | Type        | Material | Thickness (mm) | Copper weight | εr  |
|---|-----------|-------------|----------|----------------|---------------|-----|
|   | F.SilkS   | Silkscreen  | —        | 0.012          | —             | —   |
|   | F.Mask    | Solder mask | —        | 0.025          | —             | 3.3 |
| 1 | F.Cu      | TOP signal  | Cu       | 0.035          | 1 oz          | —   |
|   | dielectric| Prepreg     | FR4 Tg170| 0.102          | —             | 4.5 |
| 2 | In1.Cu    | GND1        | Cu       | 0.035          | 1 oz          | —   |
|   | dielectric| Core        | FR4 Tg170| 0.203          | —             | 4.5 |
| 3 | In2.Cu    | SIG-IN1     | Cu       | 0.035          | 1 oz          | —   |
|   | dielectric| Prepreg     | FR4 Tg170| 0.102          | —             | 4.5 |
| 4 | In3.Cu    | PWR1        | Cu       | 0.035          | 1 oz          | —   |
|   | dielectric| Core        | FR4 Tg170| 0.305          | —             | 4.5 |
| 5 | In4.Cu    | PWR2        | Cu       | 0.070          | 2 oz          | —   |
|   | dielectric| Prepreg     | FR4 Tg170| 0.102          | —             | 4.5 |
| 6 | In5.Cu    | SIG-IN2     | Cu       | 0.035          | 1 oz          | —   |
|   | dielectric| Core        | FR4 Tg170| 0.203          | —             | 4.5 |
| 7 | In6.Cu    | GND2        | Cu       | 0.035          | 1 oz          | —   |
|   | dielectric| Prepreg     | FR4 Tg170| 0.102          | —             | 4.5 |
| 8 | B.Cu      | BOT signal  | Cu       | 0.035          | 1 oz          | —   |
|   | B.Mask    | Solder mask | —        | 0.025          | —             | 3.3 |
|   | B.SilkS   | Silkscreen  | —        | 0.012          | —             | —   |
| **Total** | | | | **1.6 mm** | | |

> Use **Edit Pre-defined Stackup** → "Custom (Microstrip + Stripline)"
> and adjust dielectric heights to hit 90 Ω SE / 100 Ω diff on layer 1
> microstrip. KiCad's impedance calculator confirms with the values above.

### 1.3 Board outline (Edge.Cuts layer)

Origin at bottom-left corner. Outline = 120 × 80 mm rectangle.

Paste these four lines into `Eeschema → File → Import → Graphics`, or
draw manually on `Edge.Cuts`:

```
Line: (0.0, 0.0)    →  (120.0, 0.0)
Line: (120.0, 0.0)  →  (120.0, 80.0)
Line: (120.0, 80.0) →  (0.0, 80.0)
Line: (0.0, 80.0)   →  (0.0, 0.0)
```

### 1.4 Mounting holes

4 × M3 thru-hole, 3.2 mm drill, 6 mm pad, plated, GND-stitched.
Coordinates (centre-of-hole, X mm, Y mm):

| Hole | X | Y |
|---|---|---|
| H1 | 5.0  | 5.0  |
| H2 | 115.0 | 5.0 |
| H3 | 5.0  | 75.0 |
| H4 | 115.0 | 75.0 |

Use `Add Footprint → MountingHole_3mm_M3_DIN965` (KiCad standard
library) or `MountingHole_3mm_Pad_Via` for the GND-stitched variant.

### 1.5 Component placement origin

Per [`../SCHEMATIC.md`](../SCHEMATIC.md) §12.2, set the **drill /
place file origin** at the bottom-left corner (0, 0). KiCad: 
`File → Place Origin → Set Drill/Place Origin` and click on (0, 0).

### 1.6 Reserved component areas

Drop empty `Footprint` ghosts on F.Fab at the floorplan positions so
later placement keeps to plan. Each ghost gets a courtyard the size
of the part. From [`../SCHEMATIC.md`](../SCHEMATIC.md) §12.2:

| Part | Footprint centroid (X, Y) | Courtyard (mm) |
|---|---|---|
| KU5P | (60.0, 40.0)  | 30 × 30 |
| ESP32-S3 module | (15.0, 60.0) | 20 × 14 |
| W5500 + magjack | (18.0, 75.0) | 22 × 18 |
| USB-C receptacle | (45.0, 78.0) | 10 × 8 |
| LED PWR | (70.0, 78.0)  | 3 × 5 |
| LED LINK | (78.0, 78.0)  | 3 × 5 |
| LED MINING | (86.0, 78.0)  | 3 × 5 |
| Barrel jack | (15.0, 4.0)  | 14 × 12 |
| PCIe 6-pin | (60.0, 5.0)  | 23 × 14 |
| Fan header | (105.0, 5.0)  | 12 × 6 |
| FPGA-JTAG header (2×7) | (118.0, 40.0) | 5 × 18 |

## Step 2 — Create the schematic (`b3miner1.kicad_sch`)

In KiCad → Schematic Editor → File → New Schematic (saves alongside
the `.kicad_pro`). Then build out the hierarchical sheet structure:

```
b3miner1.kicad_sch  (root)
├── 01_power.kicad_sch        — §3 power tree
├── 02_fpga.kicad_sch         — §5 KU5P + decoupling + config
├── 03_host.kicad_sch         — §6 ESP32-S3 + reset/boot
├── 04_ethernet.kicad_sch     — §7 W5500 + magjack
├── 05_usb.kicad_sch          — §8 USB-C console
├── 06_jtag.kicad_sch         — §9 FPGA-JTAG header
├── 07_io_led.kicad_sch       — §10 LEDs + buttons
└── 08_thermal.kicad_sch      — §11 fan header + tach
```

Create each child sheet via `Place → Hierarchical Sheet`, name it as
above, and add hierarchical labels at the sheet edges for the nets
that cross sheet boundaries. The net-naming convention from
[`../SCHEMATIC.md`](../SCHEMATIC.md) Appendix A is what the project's
auto-pattern net-class assignment relies on — **do not rename** these
crossing nets without updating both the spec doc and the
`netclass_patterns` block in [`b3miner1.kicad_pro`](b3miner1.kicad_pro).

### 2.1 Net crossings between sheets

The minimum set of inter-sheet hierarchical labels (left side =
producer sheet, right side = consumer sheets):

| Net | Producer | Consumers |
|---|---|---|
| `V12_BUS` | 01_power | 02_fpga, 04_ethernet, 08_thermal |
| `V3V3_SYS` | 01_power | 02_fpga, 03_host, 04_ethernet, 06_jtag, 07_io_led |
| `V1V8_AUX` | 01_power | 02_fpga |
| `VCCINT` | 01_power | 02_fpga |
| `PG_ALL` | 01_power | 02_fpga (→ PROGRAM_B chain), 03_host |
| `FPGA_SPI_CLK` | 03_host | 02_fpga |
| `FPGA_SPI_MOSI` | 03_host | 02_fpga |
| `FPGA_SPI_MISO` | 02_fpga | 03_host |
| `FPGA_SPI_CS` | 03_host | 02_fpga |
| `FPGA_SHARE_IRQ` | 02_fpga | 03_host |
| `FPGA_PROG_B` | 03_host | 02_fpga |
| `FPGA_INIT_B` | 02_fpga | 03_host |
| `FPGA_DONE` | 02_fpga | 03_host, 07_io_led |
| `W5500_SCK / MOSI / MISO / CS / INT / RST` | 03_host | 04_ethernet |
| `USB_DP / USB_DM` | 03_host | 05_usb |
| `JTAG_TCK / TDI / TDO / TMS / VREF` | 06_jtag | 02_fpga |
| `LED_POWER / LED_LINK / LED_MINING` | 03_host | 07_io_led |
| `FAN_PWM` | 03_host | 08_thermal |
| `FAN_TACH` | 08_thermal | 03_host |
| `CLK_200M_P / CLK_200M_N` | (XO inside 02_fpga) | local |

### 2.2 Symbol library prerequisites

The contract house must commit to `lib/` (peer to this file):

- `lib/b3chain.kicad_sym` — custom symbols not in stock KiCad libs:
  - `XCKU5P-2FFVB676E` (multi-unit, one unit per bank)
  - `ESP32-S3-WROOM-1-N16R8`
  - `W5500-LQFP48`
  - `SiT9501` (LVDS XO)
  - `TPS546B24A`
  - `TPS386596`
  - `LM74700-Q1`
  - `Pulse-J0011D01BNL` magjack
- `lib/b3chain.pretty/` — matching footprints (BGA-676 1.0 mm pitch
  for KU5P, LGA-13 for the ESP module, magjack body cutout, etc.)

Library is vendored, not pulled live — see
[`README.md`](README.md) "Version control rules".

## Step 3 — Verify load

1. Open [`b3miner1.kicad_pro`](b3miner1.kicad_pro) in KiCad 8.
2. Project should open without error dialog.
3. Switch to PCB editor; Board Setup → Net Classes should show all 9
   classes from §1.
4. Board Setup → Design Rules → Constraints should show min track
   width 0.1016 mm, min via 0.45 mm.
5. Schematic editor will be empty until Step 2 completes.

If the project fails to open with a parse error, KiCad's release
notes for your 8.x point-release may have added required keys. Run
`File → Save` once from a working empty project at your KiCad version
to capture the latest schema, then diff against
[`b3miner1.kicad_pro`](b3miner1.kicad_pro) and merge.

## Step 4 — What still needs the engineer

The skeleton ends here. The contract house owns:

1. KU5P pin planning (Vivado pin-planner CSV → KiCad pin mapping for
   the multi-unit BGA symbol). Spec: [`../SCHEMATIC.md`](../SCHEMATIC.md)
   §5.2, §16 item 1.
2. Schematic capture of every subsystem (§3–§11).
3. Component placement within the §12.2 reserved courtyards.
4. BGA escape for the KU5P (the §13 stack-up assumes 4/4 mil and was
   sized to make this feasible without microvias).
5. Impedance verification with the actual board-house's prepreg
   constants (the §13 numbers assume Isola FR408HR; substitute as
   needed).
6. Fan-out, length-matching, and DRC clean.
7. Fab output generation into `fab/<rev>/`.

## Appendix — Quick reference

| Constraint | Value | Spec section |
|---|---|---|
| Board outline | 120 × 80 mm | §12.2 |
| Layer count | 8 | §13.1 |
| Min trace / space | 0.1016 mm (4 mil) / 0.1 mm | §13.2 |
| Min via | 0.45 mm OD / 0.25 mm drill | §13.2 |
| USB diff impedance | 90 Ω | §13.2 |
| Ethernet diff impedance | 100 Ω | §13.2 |
| LVDS clock impedance | 100 Ω diff | §4.3 |
| VCCINT current capacity | 40 A peak | §3.2 |
| Mounting holes | 4 × M3, 110 × 70 grid | §12.2 |
| Total z-stack | 35 mm above PCB | §12.3 |
| Surface finish | ENIG | §13.3 |
