# B3Miner-1 PCB project files

Drop zone for EDA project files and fabrication outputs produced by the
contract PCB design house. The hardware specification they implement
against lives one level up in [`../SCHEMATIC.md`](../SCHEMATIC.md);
nothing in this folder may diverge from that spec without a paired
update there.

## Expected contents

| File / folder              | Tool         | Purpose                                                      |
|----------------------------|--------------|--------------------------------------------------------------|
| `b3miner1.kicad_pro`       | KiCad 8+     | Project file (preferred — open-source toolchain)             |
| `b3miner1.kicad_sch`       | KiCad 8+     | Top-level schematic + sub-sheets                             |
| `b3miner1.kicad_pcb`       | KiCad 8+     | Board layout                                                 |
| `b3miner1.PrjPcb`          | Altium 24+   | Alternative project file if the house uses Altium            |
| `b3miner1.SchDoc`          | Altium 24+   | Schematic capture                                            |
| `b3miner1.PcbDoc`          | Altium 24+   | Board layout                                                 |
| `lib/`                     | KiCad/Altium | Symbol + footprint libraries (committed alongside, not pulled live) |
| `pinplan/b3miner_r0.csv`   | Vivado       | KU5P FFVB676 pin assignment (per [`SCHEMATIC.md`](../SCHEMATIC.md) §16 item 1) |
| `fab/gerbers_r0/`          | output       | Gerber X2 + drill files (rev R0 release)                     |
| `fab/bom_r0.csv`           | output       | Production BOM with second sources marked (per §14)          |
| `fab/pnp_r0.csv`           | output       | Pick-and-place / centroid file                               |
| `fab/ipc2581_r0.xml`       | output       | IPC-2581 board export (per §12.4)                            |
| `fab/step_r0.step`         | output       | 3D STEP AP214 assembly model (per §16 item 9)                |
| `fab/dxf_r0.dxf`           | output       | Board outline DXF (per §12.4)                                |
| `fab/idf_r0.idf`           | output       | IDF 3.0 file for chassis design (per §12.4)                  |
| `fab/assembly_r0.pdf`      | output       | Top + bottom assembly drawings, fab notes                    |

## Workflow

1. House receives [`../SCHEMATIC.md`](../SCHEMATIC.md) as the spec.
2. House captures schematic in either KiCad 8+ (preferred) or Altium 24+.
   Use the EDA-tool-of-choice consistently — do not mix project files
   in this folder. Keep the unused branch deleted at commit time.
3. House routes layout per the §13 stack-up + impedance targets.
4. House produces the `fab/<rev>/` directory containing every output
   needed for a turn-key assembly quote.
5. PR opens against `b3chain-main` with this folder populated. Reviewers
   check the `fab/<rev>/` outputs render and the BOM second-source
   coverage matches `SCHEMATIC.md` §14.

## Version control rules for EDA files

- **KiCad files** are text — commit them directly. Diffable.
- **Altium files** are binary — commit them, but every revision bump
  must also produce a paired `*.SchDoc.pdf` and `*.PcbDoc.pdf` in
  `fab/<rev>/` so reviewers can see what changed without an Altium
  license.
- **Library files** (`lib/`) are vendored, not pulled live from a
  cloud library. The board must build offline from this repo alone.
- **Generated outputs** (`fab/<rev>/`) are committed — they are the
  authoritative artifact handed to the assembly house and need to
  be reviewable in the PR. Re-generation must be reproducible from
  the project files plus a documented tool version.

## Revision tagging

Each fab spin gets its own directory: `fab/gerbers_r0/`,
`fab/gerbers_r1/`, etc. Never overwrite an old spin's outputs — they
are the historical record of what was actually manufactured. The
matching schematic / layout source files are tagged in git with
`b3miner1-rN` annotated tags.

## Currently in this folder

| File | What it is |
|---|---|
| [`README.md`](README.md) | This file |
| [`b3miner1.kicad_pro`](b3miner1.kicad_pro) | KiCad 8 project skeleton — pre-encodes the 9 net classes from [`../SCHEMATIC.md`](../SCHEMATIC.md) §13 (USB 90 Ω diff, Ethernet 100 Ω diff, LVDS clock 100 Ω diff, GTH future, SPI bus, three power-rail classes), DRC rules at 8L / 4 mil fab class, BOM export format, and project text variables. Opens in KiCad 8.0+ without further setup. |
| [`kicad-bringup.md`](kicad-bringup.md) | Paste-ready GUI checklist to take the project from skeleton to a working capture + layout starter — layer stack-up dialog values, board outline coordinates, mounting-hole positions, hierarchical sheet structure for the schematic, inter-sheet net list, symbol-library prerequisites, and the explicit "what still needs the engineer" boundary. |

**Not yet in this folder (contract-house deliverables):**

- `b3miner1.kicad_sch` + per-subsystem sheet files (`01_power.kicad_sch` etc.) — schematic capture per `kicad-bringup.md` Step 2
- `b3miner1.kicad_pcb` — board layout per `kicad-bringup.md` Step 1
- `lib/b3chain.kicad_sym` + `lib/b3chain.pretty/` — custom symbols/footprints (KU5P BGA-676, ESP32-S3 module, W5500, etc.)
- `pinplan/b3miner_r0.csv` — KU5P FFVB676 pin assignment from Vivado pin-planner
- `fab/gerbers_r0/` and the rest of the `fab/` outputs

**Altium variant:** the Altium files listed in the "Expected contents" table above are an alternative project format the contract house may use instead of KiCad. They are binary and cannot be created as text in this repo — if the house chooses Altium, they will commit those files directly alongside the matching `*.SchDoc.pdf` and `*.PcbDoc.pdf` reviewer renders (see "Version control rules" below).
