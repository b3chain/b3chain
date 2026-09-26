# B3Miner-1 — PCB House Connection Guide

**Derived from:** `SCHEMATIC.md` rev R0 / R0.1 (2026-05-18)  
**Ethernet option:** **A — W5500 SPI** (binding for this guide)  
**Audience:** Contract PCB house — schematic capture, layout, assembly, ICT  
**Companion docs:** `SCHEMATIC.md` (full spec), `pcb/kicad-bringup.md` (KiCad sheets + floorplan)

---

## How to use this document

1. **Net names** in this guide are **binding** — use them on the schematic exactly (see Appendix A). They map to KiCad net classes in `pcb/b3miner1.kicad_pro`.
2. Tables use: **From (pin)** → **To (pin)** | **Net** | **Passives / notes**.
3. **DNI** = do not install (footprint only on R0).
4. **KU5P ball numbers** are *not* listed here — the house must complete Vivado pin-planning (SCHEMATIC §16 item 1) and map balls to the nets below.
5. Capture schematic in **8 hierarchical sheets** per `pcb/kicad-bringup.md` §2.

---

## 1. System-level interconnect map

Every major block and what it connects to:

```
                    ┌─────────────────────────────────────────┐
  12V Barrel ───────┤                                         │
  PCIe 6-pin ───────┤  POWER TREE (§3)                        │
                    │    V12_BUS → VCCINT, 5V, fan 12V        │
                    │    V5V0 → V3V3_SYS                       │
                    │    V3V3_SYS → ESP, W5500, KU5P HR, JTAG │
                    │    V1V8_AUX → KU5P HP + VCCO_HP          │
                    │    PG_ALL → KU5P PROGRAM_B + ESP sense  │
                    └─────────────────────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
  ESP32-S3-WROOM-1              W5500 + Magjack                  XCKU5P-2FFVB676E
  (host, USB, LEDs,             (RJ45 to LAN)                   (mining, JTAG,
   fan, I2C sec)                                                    200 MHz XO)
        │                             │                             │
        │ SPI2 (HSPI)                 │ SPI2                        │ SPI + config
        ├─────────────────────────────┤                             │
        │                             │                             │
        └──────── FPGA_SPI_* / FPGA_PROG_B / FPGA_DONE / etc. ─────┘

  ATECC608B ←I2C→ ESP (GPIO1/2 only)
  USB-C ←D+/D-→ ESP (GPIO19/20)
  2×7 header ←JTAG→ KU5P config bank (not ESP)
```

---

## 2. Power subsystem — connect every rail

### 2.1 Input path (12 V)

| Step | From | To | Net | Passives / notes |
|------|------|-----|-----|------------------|
| 1 | Barrel jack **+** (center 2.5 mm) | LM74700 #1 input | `V12_IN_BARREL` | Locking 5.5/2.5 mm, 12 V @ 8 A rated |
| 2 | Barrel jack **−** | Board `GND` | `GND` | Star to plane at jack |
| 3 | PCIe 6-pin **+12 V** (pins 1,2,3) | LM74700 #2 input | `V12_IN_PCIE` | Standard PCIe aux pinout |
| 4 | PCIe 6-pin **GND** (pins 2,4,6) | `GND` | `GND` | |
| 5 | LM74700 #1 out OR LM74700 #2 out | TPS25940A input | `V12_PRE_EFUSE` | Both inputs OR’d — higher voltage wins |
| 6 | TPS25940A output | 12 V bulk + all 12 V loads | `V12_BUS` | 2×470 µF e-cap + 4×22 µF X7R at input of tree; SMAJ16CA TVS barrel→GND |
| 7 | TPS25940A `PG` | TPS386596 input / EN chain | `PG_12V` | 50 ms inrush: dV/dt cap on TPS25940 `EN` per §3.4 |

**Do not:** Back-feed 12 V from ESP or FPGA. **Do not:** Tie barrel and PCIe grounds through a single thin trace — use plane.

### 2.2 12 V consumers (direct from `V12_BUS`)

| From `V12_BUS` | To | Net | Notes |
|----------------|-----|-----|-------|
| `V12_BUS` | 2× TPS546B24A input (VCCINT buck) | `V12_BUS` | 2-phase, 40 A peak capability |
| `V12_BUS` | TPS54360 input (5 V buck) | `V12_BUS` | |
| `V12_BUS` | Fan connector pin 2 | `V12_FAN` | **12 V**, not 5 V — Sunon 12 V fan |
| `V12_BUS` | (optional) PCIe-style loads | `V12_BUS` | Keep traces ≥1 mm or plane |

### 2.3 5 V rail

| From | To | Net | Passives |
|------|-----|-----|----------|
| TPS54360 output | TPS62933 input | `V5V0` | L=6.8 µH, Cout 47+22 µF, Fsw 500 kHz |
| TPS54360 `PG` | TPS386596 | `PG_5V` | |
| `V5V0` | (future option board only) | `V5V0` | R0: no fan/USB power from 5 V |

### 2.4 3.3 V system rail (`V3V3_SYS`)

| From | To | Net | Passives at load |
|------|-----|-----|------------------|
| TPS62933 output | ESP32-S3 `VDD3P3` / `3V3` pins | `V3V3_SYS` | 22 µF + 1 µF + 4×0.1 µF <5 mm from module |
| `V3V3_SYS` | W5500 `VDD`, `AVDD`, `1V2O` pin (if exposed) | `V3V3_SYS` | Per W5500 datasheet + 0.1 µF at each power pin |
| `V3V3_SYS` | KU5P **HR bank 84** `VCCO` | `V3V3_SYS` | 2×22 µF + 6×0.1 µF per bank §5.4 |
| `V3V3_SYS` | KU5P config bank `VCCO_0` | `V3V3_SYS` | Config straps 3.3 V |
| `V3V3_SYS` | JTAG header pins 1, 2 | `JTAG_VREF`, `JTAG_VCC` | Pin 2 via ferrite bead from `V3V3_SYS` |
| `V3V3_SYS` | ATECC608B pin 8 | `V3V3_SYS` | 0.1 µF + 1 µF at pin 8 |
| `V3V3_SYS` | LED anode networks, pull-ups | `V3V3_SYS` | See §10 |
| `V3V3_SYS` | 4.7 kΩ pull-ups: I2C, FPGA config, fan tach | `V3V3_SYS` | One net class for all 3.3 V pull-ups |

**W5500 internal 1.0 V:** W5500 generates core from `VDD` — **only decouple** per datasheet; **do not** feed external 1.0 V.

### 2.5 1.8 V FPGA auxiliary (`V1V8_AUX` / `VCCAUX`)

| From | To | Net | Notes |
|------|-----|-----|-------|
| TLV62568 output | KU5P `VCCAUX` pins | `V1V8_AUX` | L=2.2 µH, Cout 22+22 µF |
| `V1V8_AUX` | KU5P HP banks 65, 66, 67 `VCCO` | `VCCO_HP_1V8` | Same rail as VCCAUX in R0 |
| `V1V8_AUX` | KU5P `VCCBRAM` | `VCCBRAM` | **Tied to VCCINT 0.85 V plane** per UG583 — not 1.8 V |
| `V1V8_AUX` | XADC `VREFP` via 47 Ω ferrite | `VREFP` | REF3012 footprint **DNI** |

### 2.6 VCCINT 0.85 V (KU5P core)

| From | To | Net | Notes |
|------|-----|-----|-------|
| 2× TPS546B24A output | KU5P `VCCINT` balls | `VCCINT` | **Layer 5** 2 oz plane; 12×22 µF + 4×470 µF polymer under BGA |
| `VCCINT` | `VCCBRAM` balls | `VCCINT` | Same plane — 2×22 µF + 4×0.1 µF dedicated near BRAM cluster |

### 2.7 MGT power (R0: regulators DNI, still decouple)

| Rail | To KU5P | R0 |
|------|---------|-----|
| `MGTAVCC` 0.9 V | GTH bank 224 | LDO LP38798 **DNI** — place 22 µF + 0.1 µF to GND at pads |
| `MGTAVTT` 1.2 V | GTH bank 224 | LDO LP38798 **DNI** — same |
| `MGTVCCAUX` 1.8 V | From `V1V8_AUX` | Decouple per UG576 |

GTH TX/RX: **0 Ω DNI** to GND (parking). REFCLK: **float**. 156.25 MHz XO: **DNI**.

### 2.8 Sequencing / supervisor (TPS386596)

Connect monitor inputs to each rail feedback (resistor dividers per TI datasheet). EN chain:

```
EN_VCCINT  ← PG_system (12V/5V/3.3V chain OK)
EN_VCCAUX  ← PG(VCCINT)
EN_VCCO_HP ← PG(VCCAUX)
EN_VCCO_HR ← PG(3.3V)   // on with system 3.3 V
```

| Signal | From | To | Net | Notes |
|--------|------|-----|-----|-------|
| `PG_ALL` | TPS386596 open-drain out | KU5P `PROGRAM_B` | `PG_ALL` | 10 kΩ pull-up to 3.3 V |
| `PG_ALL` | (optional sense) | ESP GPIO (if allocated) | `PG_ALL` | Firmware may read via strap — confirm schematic |

**Wire-OR on `PROGRAM_B`:** `PG_ALL` and ESP GPIO5 both pull `FPGA_PROG_B` low (open-drain). Use 4.7 kΩ pull-up to 3.3 V on `FPGA_PROG_B` net.

### 2.9 Ground

| All `GND` pins | Board `GND` plane layers 2 + 7 |
| Mounting holes | GND-stitched vias (4× M3) |
| Magjack shield / Bob-Smith | **Chassis island** — separate from digital GND except 1 nF tie |
| USB-C shell | `EARTH` → 1 MΩ ∥ 4.7 nF → chassis island |

---

## 3. ESP32-S3-WROOM-1-N16R8 — connections

### 3.1 Power and reset

| ESP pin / function | Connect to | Net | Passives |
|--------------------|------------|-----|----------|
| `3V3` / `VDD3P3` | `V3V3_SYS` | `V3V3_SYS` | §3.4 decoupling |
| `GND` | `GND` | `GND` | Multiple vias |
| `EN` | `V3V3_SYS` via 10 kΩ | `ESP_EN` | 10 kΩ pull-up; 1 µF to GND; RESET switch to GND via 470 Ω |
| `GPIO0` | `V3V3_SYS` via 10 kΩ + BOOT switch to GND | `ESP_BOOT` | Strap: pulled high normally |
| `GPIO3` | `GND` | `ESP_STRAP3` | Strap low @ reset |
| `GPIO45` | `GND` | — | Strap low |
| `GPIO46` | `GND` | — | Strap low |

### 3.2 **Do not route** (module internal use)

| ESP GPIO | Action |
|----------|--------|
| GPIO35, GPIO36, GPIO37 | **No PCB connection** — octal PSRAM internal |
| GPIO38 | **No PCB route** — RGB LED inside module |

### 3.3 Antenna keep-out

- Module at **(15, 60) mm**, antenna toward **front edge (Y=80)**.
- **≥15 mm** copper clearance on antenna axis per Espressif — chassis cutout required.

---

## 4. ESP ↔ KU5P (SPI + configuration) — **critical path**

All signals are **1.8 V** at KU5P HP bank 65 side; ESP GPIOs are **3.3 V**. Use **TXS0108E** or equivalent auto-direction level shifter **unless** house confirms KU5P HP pins are 3.3 V tolerant at slow SPI (spec assumes HP bank VCCO = 1.8 V — **level translation required** for 3.3 V ESP).

> **SCHEMATIC.md assumes direct connect at HP 1.8 V.** If ESP I/O is 3.3 V fixed, insert level shifter on: `FPGA_SPI_CLK`, `FPGA_SPI_MOSI`, `FPGA_SPI_CS`, `FPGA_PROG_B` (OD), and MISO/IRQ/DONE/INIT directionally. **Flag to b3chain if omitted.**

### 4.1 Configuration / SPI net table (binding firmware)

| Net | ESP GPIO | KU5P function | Dir @ ESP | Passives |
|-----|----------|---------------|-----------|----------|
| `FPGA_PROG_B` | GPIO5 | `PROGRAM_B` | OD out | 4.7 kΩ PU 3.3 V; wire-OR with `PG_ALL` |
| `FPGA_INIT_B` | GPIO6 | `INIT_B` | In | 4.7 kΩ PU 3.3 V |
| `FPGA_DONE` | GPIO7 | `DONE` | In | 4.7 kΩ PU 3.3 V; also to white LED circuit §10 |
| `FPGA_SPI_CS` | GPIO10 | HP CS (user ball) | Out | 0 Ω series optional |
| `FPGA_SPI_MOSI` | GPIO11 | `D00` / MOSI | Out | Shared with config `DIN` |
| `FPGA_SPI_CLK` | GPIO12 | `CCLK` + SPI CLK | Out | 22 Ω **DNI** at ESP; 25 MHz max |
| `FPGA_SPI_MISO` | GPIO13 | MISO | In | |
| `FPGA_SHARE_IRQ` | GPIO4 | HP IRQ out | In | ESP internal pull-up enabled in FW |

### 4.2 KU5P configuration straps (slave-serial)

| KU5P pin | Tie to | Net |
|----------|--------|-----|
| `M0`, `M1`, `M2` | `V3V3_SYS` via 4.7 kΩ each | `FPGA_M0` etc. |
| `CFGBVS` | `VCCO_0` (3.3 V) | direct |
| `POR_OVERRIDE` | `GND` via 10 kΩ | |

### 4.3 200 MHz clock (SiT9501 → KU5P MRCC)

| From | To | Net | Layout |
|------|-----|-----|--------|
| SiT9501 `OUT+` | MRCC `CLK_P` bank 65 | `CLK_200M_P` | 100 Ω diff, ≤5 mm, ±2 mil match |
| SiT9501 `OUT−` | MRCC `CLK_N` bank 65 | `CLK_200M_N` | |
| XO `VDD` | `V3V3_SYS` or `V1V8` per datasheet | — | 0.1 µF + 10 µF |

156.25 MHz XO to bank 224: footprint **DNI**.

---

## 5. ESP ↔ W5500 (SPI2 / HSPI)

| Net | ESP GPIO | W5500 pin | Dir @ ESP | Notes |
|-----|----------|-----------|-----------|-------|
| `W5500_SCK` | GPIO14 | `SCLK` | Out | SPI mode 0/3, target 30 MHz |
| `W5500_MOSI` | GPIO17 | `MOSI` / `SI` | Out | |
| `W5500_MISO` | GPIO15 | `MISO` / `SO` | In | |
| `W5500_CS` | GPIO9 | `SCSn` | Out | Active low |
| `W5500_INT` | GPIO8 | `INTn` | In | Active low interrupt |
| `W5500_RST` | GPIO16 | `RSTn` | Out | Hold low ≥500 µs at boot |
| `V3V3_SYS` | `VDD`, `AVDD` | power | — | Decouple per §7 |
| `GND` | `GND` | — | — | |

**Do not** route RMII signals — Option A has **no** `ETH_MDC`, `ETH_MDIO`, `ETH_CLK`.

### 5.1 W5500 ↔ Magjack (PHY side)

| W5500 pin pair | Magjack pins | Net | Notes |
|----------------|--------------|-----|-------|
| `TX+`, `TX−` | Transformer TX side | `ETH_TX_P`, `ETH_TX_N` | 100 Ω diff ≤50 mm |
| `RX+`, `RX−` | Transformer RX side | `ETH_RX_P`, `ETH_RX_N` | Pair-match ≤5 mil |
| LED drivers | Magjack LED pins | `ETH_LED_LINK`, `ETH_LED_ACT` | **Not** front-panel LEDs |
| — | Bob-Smith 75 Ω ×4 | `ETH_BS` | Common → chassis via 1 nF 2 kV |
| RJ45 pairs | SP0503BAHTG | — | ESD before magjack |

### 5.2 W5500 crystal

| From | To | Net | Passives |
|------|-----|-----|----------|
| NX2520SA-25M pad 1 | W5500 `XI` | `W5500_XI` | 22 pF load cap ×2 to GND |
| NX2520SA pad 2 | W5500 `XO` | `W5500_XO` | Crystal <10 mm from IC |

---

## 6. ESP ↔ ATECC608B (I2C)

| Net | ESP | ATECC pin | Passives |
|-----|-----|-----------|----------|
| `SEC_I2C_SDA` | GPIO1 | Pin 5 (SDA) | 4.7 kΩ PU to `V3V3_SYS` **near ESP** |
| `SEC_I2C_SCL` | GPIO2 | Pin 6 (SCL) | 4.7 kΩ PU to `V3V3_SYS` **near ESP** |
| `V3V3_SYS` | — | Pin 8 (VCC) | 0.1 µF + 1 µF |
| `GND` | — | Pin 4 (GND) | |
| NC | — | Pins 1,2,3,7 | **Float** — do not tie |

- Bus speed: **400 kHz** max layout length **<20 mm** from ESP.
- **No** test header on I2C lines.

---

## 7. ESP ↔ USB-C (USB4105-GF-A)

| USB-C pins | Connect to | Net | Passives |
|------------|------------|-----|----------|
| A6 ∥ B6 | ESP GPIO20 via USBLC6 | `USB_DP` | 22 Ω **DNI** series; 90 Ω diff pair <60 mm |
| A7 ∥ B7 | ESP GPIO19 via USBLC6 | `USB_DM` | |
| A5, B5 | `GND` via 5.1 kΩ each | `CC1`, `CC2` | Rd sink — device port |
| A1,A12,B1,B12 | `GND` | `GND` | |
| A4,A9,B4,B9 | Polyfuse → TVS → (divider **DNI**) | `VBUS_PROT` | **Not** system power |
| Shell | `EARTH` | 1 MΩ ∥ 4.7 nF → chassis |
| SBU1, SBU2 | NC | — | |

**Do not** power board from VBUS.

---

## 8. KU5P ↔ JTAG header (2×7, Xilinx 14-pin)

| Header pin | Net | KU5P | Passives |
|------------|-----|------|----------|
| 1 | `JTAG_VREF` | `VCCO_0` | 3.3 V |
| 2 | `JTAG_VCC` | `VCCO_0` | Ferrite from `V3V3_SYS` |
| 4 | `JTAG_TMS` | `TMS` | 4.7 kΩ PU |
| 6 | `JTAG_TCK` | `TCK` | 1 kΩ PD |
| 8 | `JTAG_TDO` | `TDO` | 4.7 kΩ PU |
| 10 | `JTAG_TDI` | `TDI` | 4.7 kΩ PU |
| 3,5,7,9,11–14 | `GND` | `GND` | Pin 7 = key |

**Do not** connect header to ESP JTAG — ESP debug is **USB-C only**.

---

## 9. LEDs, buttons, fan

### 9.1 Front-panel LEDs (ESP source mode → LED → resistor → GND)

| LED | ESP GPIO | Net | Resistor | Notes |
|-----|----------|-----|----------|-------|
| Green PWR | GPIO48 | `LED_POWER` | 680 Ω | Solid when 3.3 V good |
| Yellow LINK | GPIO47 | `LED_LINK` | 680 Ω | Ethernet link |
| Blue MINE | GPIO21 | `LED_MINING` | 150 Ω | Mining activity |
| — | `V3V3_SYS` | Anode side | — | PESD3V3L1BA TVS on user-touchable leads |

### 9.2 Top-side indicators

| Function | Drive | Net | Circuit |
|----------|-------|-----|---------|
| FPGA configured | KU5P `DONE` | `FPGA_DONE` | 150 Ω + white 0805 LED to GND |
| Share found | KU5P `FPGA_SHARE_IRQ` | `FPGA_SHARE_IRQ` | 100 ms RC one-shot → MOSFET → red LED + 220 Ω |

### 9.3 Reset / boot switches

| Switch | Between | Net |
|--------|---------|-----|
| RESET | `ESP_EN` and `GND` | via 470 Ω |
| BOOT | `GPIO0` and `GND` | direct |

### 9.4 Fan (JST PHR-4)

| Conn pin | Connect to | Net |
|----------|------------|-----|
| 1 | `GND` | `GND` |
| 2 | `V12_BUS` | `V12_FAN` |
| 3 | ESP GPIO23 via 4.7 kΩ PU to 3.3 V | `FAN_TACH` |
| 4 | ESP GPIO22 | `FAN_PWM` | 25 kHz |

**Optional:** Route `FAN_TACH` to KU5P HR bank if firmware later reads tach from FPGA — R0 firmware reads ESP GPIO23 only.

---

## 10. Clock summary (what connects to what)

| Source | Destination | Net(s) |
|--------|-------------|--------|
| (in module) 40 MHz | ESP PLL | internal — **no PCB** |
| NX2520SA 25 MHz | W5500 XI/XO | `W5500_XI`, `W5500_XO` |
| SiT9501 200 MHz LVDS | KU5P MRCC 65 | `CLK_200M_P/N` |
| ESP GPIO12 | KU5P CCLK + SPI CLK | `FPGA_SPI_CLK` |
| SiT9501 156.25 MHz | KU5P GTH | **DNI** |

---

## 11. Complete signal checklist (sign-off)

Use this table to verify every net exists on the schematic:

| # | Net | Must connect |
|---|-----|----------------|
| 1 | `V12_BUS` | Inputs, VCCINT buck, 5V buck, fan pin2 |
| 2 | `V5V0` | 3.3 V buck input |
| 3 | `V3V3_SYS` | ESP, W5500, KU5P HR, config bank, JTAG VREF, pull-ups |
| 4 | `V1V8_AUX` | KU5P VCCAUX + HP VCCO |
| 5 | `VCCINT` | KU5P core + VCCBRAM |
| 6 | `PG_ALL` | Supervisor → `FPGA_PROG_B` |
| 7 | `FPGA_PROG_B` | ESP GPIO5 + supervisor + KU5P |
| 8 | `FPGA_INIT_B` | ESP GPIO6 + KU5P |
| 9 | `FPGA_DONE` | ESP GPIO7 + KU5P + white LED |
| 10 | `FPGA_SPI_*` | ESP GPIO10–13 + KU5P |
| 11 | `FPGA_SHARE_IRQ` | ESP GPIO4 + KU5P + share LED circuit |
| 12 | `W5500_*` | ESP GPIO8,9,14–17 + W5500 IC |
| 13 | `ETH_TX/RX_*` | W5500 ↔ magjack |
| 14 | `SEC_I2C_*` | ESP GPIO1–2 ↔ ATECC608B |
| 15 | `USB_DP/DM` | USB-C ↔ ESP GPIO19–20 |
| 16 | `JTAG_*` | Header ↔ KU5P only |
| 17 | `LED_*` | ESP GPIOs ↔ LEDs |
| 18 | `FAN_PWM/TACH` | ESP ↔ fan header |
| 19 | `CLK_200M_P/N` | XO ↔ KU5P |
| 20 | `GND` / `EARTH` | Planes + chassis island |

---

## 12. KiCad sheet assignment (where to draw each connection)

| Sheet file | Draw these connections in |
|------------|---------------------------|
| `01_power.kicad_sch` | §2 entire power tree |
| `02_fpga.kicad_sch` | KU5P power, decap, straps, XO, JTAG to FPGA balls, `FPGA_SHARE_IRQ` out |
| `03_host.kicad_sch` | ESP module, ATECC, all ESP GPIO nets |
| `04_ethernet.kicad_sch` | W5500, xtal, magjack, ETH diff pairs |
| `05_usb.kicad_sch` | USB-C, CC, VBUS protection, USBLC6 |
| `06_jtag.kicad_sch` | 2×7 header only |
| `07_io_led.kicad_sch` | Front LEDs, switches, DONE/SHARE LEDs |
| `08_thermal.kicad_sch` | Fan connector |
| `b3miner1.kicad_sch` | Hierarchical blocks only — wire `V3V3_SYS`, `FPGA_SPI_*`, etc. between sheets |

Inter-sheet nets: see `pcb/kicad-bringup.md` §2.1.

---

## 13. Bring-up order (verify connections)

| Step | Populate | Prove these connections |
|------|----------|-------------------------|
| 1 | Power parts only | TP1–TP6 rails §15.1 |
| 2 | + ESP | USB-C `USB_DP/DM`; 3.3 V at module |
| 3 | + ATECC | `SEC_I2C_*` TP15–16 |
| 4 | + W5500 + magjack | `ETH_*`, `W5500_*`; link LED on magjack |
| 5 | + KU5P | `FPGA_SPI_*`, `FPGA_DONE` TP7; `CLK_200M` TP12 |
| 6 | Full | TP10 share IRQ; mining LED |

---

## 14. Open items for PCB house (from SCHEMATIC §16)

1. Export `pinplan/b3miner_r0.csv` after Vivado — maps KU5P balls to nets in §4–5.  
2. Confirm **3.3 V ESP ↔ 1.8 V KU5P HP** level shifter strategy.  
3. Regulator FET/inductor BOM detail.  
4. Return STEP + IPC-2581 + fab outputs to `pcb/fab/`.

---

## Appendix — Net naming (copy to schematic)

| Prefix | Example nets |
|--------|----------------|
| `V*` | `V12_BUS`, `V3V3_SYS`, `VCCINT`, `V1V8_AUX`, `V5V0` |
| `PG_*` | `PG_ALL`, `PG_5V` |
| `FPGA_*` | `FPGA_SPI_CLK`, `FPGA_PROG_B`, `FPGA_DONE` |
| `W5500_*` | `W5500_CS`, `W5500_RST` |
| `SEC_*` | `SEC_I2C_SDA`, `SEC_I2C_SCL` |
| `USB_*` | `USB_DP`, `USB_DM` |
| `JTAG_*` | `JTAG_TCK`, `JTAG_TDI`, … |
| `LED_*` | `LED_POWER`, `LED_LINK`, `LED_MINING` |
| `FAN_*` | `FAN_PWM`, `FAN_TACH` |
| `CLK_*` | `CLK_200M_P`, `CLK_200M_N` |
| `ETH_*` | `ETH_TX_P`, `ETH_RX_P`, … |

---

*Document: CONNECTION-GUIDE.md rev 1.0 — generated for PCB house from SCHEMATIC.md R0/R0.1.*
