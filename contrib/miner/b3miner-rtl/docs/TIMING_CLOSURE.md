# Timing closure runbook -- 250 MHz mining clock on KU5P-2I

This runbook documents the methodology for closing timing on `clk_mine`
(250 MHz, 4 ns period) and `clk_sys` (100 MHz, 10 ns period). The
out-of-the-box flow (`make synth impl`) is the starting point; this
document is the troubleshooting tree when WNS comes back negative.

The closure work is performed by the FPGA engineer on a Vivado-licensed
host. This file lives in the repo so the procedure is reproducible.

---

## Step 0 -- baseline measurements

```bash
make synth
make impl
make report
```

Look at `build/reports/summary.txt`:

```
Timing (250 MHz mining clock target):
  WNS = +0.342 ns    (must be >= 0)
  WHS = +0.041 ns
  TNS = 0.0 ns
  THS = 0.0 ns
```

If WNS ≥ +0.100 ns and TNS = 0: you're done. Generate the bitstream
(`make bin`) and proceed to hardware bring-up.

If WNS is negative or marginal (-1.0 < WNS < +0.100 ns), iterate
through the steps below.

## Step 1 -- identify the critical path

```bash
vivado -mode tcl
> open_run impl_1
> report_timing -nworst 5 -delay_type max -from [get_pins -hierarchical -filter {NAME =~ *u_mixing/*}]
```

For the B3Miner-1 design, the critical path is almost certainly one
of these (in expected order):

| Rank | Path | Why |
|---|---|---|
| 1 | `scratchpad_mem.ra_data` → `mixing_core.do_round.g_step` | 8 lanes × 16 G-functions = 128 add/rot/xor chains in 2 cycles |
| 2 | `mixing_core.short_compress` → `wb_data` | Combinational mix happens fully in `S_MIX_WRITE` |
| 3 | `regfile` rdata mux → `spi_slave.rdata_lat` | Wide one-hot mux at 100 MHz (lots of slack) |
| 4 | `blake3_compress.do_round` register chain | 7-round iterative, 1 round/cycle |

## Step 2 -- choose an iteration knob

In rough order of cost vs. WNS-improvement:

### A. Strategy upgrade (no RTL change)

```tcl
# In build/synth.tcl:
set_property strategy {Flow_PerfOptimized_high} [get_runs synth_1]

# In build/implement.tcl:
set_property strategy {Performance_ExplorePostRoutePhysOpt} [get_runs impl_1]
```

Expected gain: +0.2 to +0.5 ns WNS. Compile time roughly doubles.

### B. Pipeline `mixing_core.S_MIX_WRITE` (1 cycle penalty per iter)

Today `S_MIX_WRITE` runs the entire 8-lane × 2-round mix in a single
cycle. Split into two cycles by adding an intermediate register:

```systemverilog
// In mixing_core.sv -- replace the in-loop short_compress with:
typedef enum logic [3:0] { ..., S_MIX_R0, S_MIX_R1_WRITE, ... } state_e;

S_MIX_R0:  begin
    for (int L = 0; L < LANES; L++) begin
        // First round only
        do_round_once(lanes_mid[L], read_blk[L]);   // new function
    end
    state <= S_MIX_R1_WRITE;
end
S_MIX_R1_WRITE: begin
    // Second round + writeback as today
end
```

Cost: +1 cycle per iteration → 33 µs → 41 µs/hash → 24 kH/s (vs 30 kH/s).
Expected gain: +1.0 to +1.5 ns WNS. **Recommended first** if Step A doesn't close.

### C. Pipeline `blake3_compress.do_round` (no perf penalty)

Today `do_round` is a combinational chain of 8 G-functions running once
per clock. Insert a pipeline register between the column-G and diagonal-G
halves:

```systemverilog
// Split do_round into two combinational halves with a reg between.
task automatic do_round_cols(ref logic [31:0] st [0:15], input logic [31:0] mm [0:15]);
    g_step(st[0], st[4], st[ 8], st[12], mm[0], mm[1]);
    ...
endtask
task automatic do_round_diags(ref logic [31:0] st [0:15], input logic [31:0] mm [0:15]);
    g_step(st[0], st[5], st[10], st[15], mm[8], mm[9]);
    ...
endtask
```

Cost: blake3 compress doubles from 7 to 14 cycles, but BLAKE3 is only
used for scratch_init and final hash -- negligible global impact.
Expected gain: +0.3 to +0.5 ns WNS *if* blake3 is on the critical path.

### D. Floorplan: pin the scratchpad BRAMs near the mixing_core slices

```tcl
# In build/xdc/b3miner_floorplan.xdc  (create this file, add to TCL flow):
create_pblock pblock_lane_0
add_cells_to_pblock pblock_lane_0 [get_cells {u_dut/u_scratchpad/g_lane[0].*}]
resize_pblock pblock_lane_0 -add {SLICE_X0Y0:SLICE_X20Y50}
add_cells_to_pblock pblock_lane_0 [get_cells {u_dut/u_mixing/lane_logic[0].*}]
```

Cost: re-running impl with the pblocks adds ~10 min compile time.
Expected gain: +0.5 to +2.0 ns WNS *if* placement was the problem.

### E. Retiming pragma on critical combinational paths

```systemverilog
// In mixing_core.sv, on the lanes register:
(* retiming_forward = 1, retiming_backward = 1 *)
logic [255:0] lanes [0:LANES-1];
```

Cost: synthesis may use more flops.
Expected gain: +0.2 ns WNS.

### F. Drop the clock to 200 MHz (last resort)

If after A, B, C, D the design still doesn't close at 250 MHz:

```tcl
# In build/xdc/b3miner_timing.xdc:
create_generated_clock -name clk_mine ... -multiply_by 1 ...
```

Update the README hashrate claim accordingly:
- 200 MHz × 8192 cyc/hash = 40.96 µs/hash = 24.4 kH/s.

## Step 3 -- iterate

After each knob change, re-run:

```bash
make synth impl report
grep WNS build/reports/summary.txt
```

Stop when WNS ≥ +0.100 ns. Two successive runs with WNS swings smaller
than ±0.05 ns means you've found the bedrock; further iteration won't
help. If WNS is still negative at that point, move to the next knob.

## Step 4 -- record the closure recipe

Add to [`CHANGELOG.md`](../CHANGELOG.md):

```
### Timing closure (YYYY-MM-DD)

* Strategy: Flow_PerfOptimized_high + Performance_ExplorePostRoutePhysOpt
* RTL: split mixing_core into S_MIX_R0 / S_MIX_R1_WRITE (1-cycle penalty)
* Floorplan: 8 × pblock_lane_N pinning scratchpad+mix-logic together
* Result: WNS = +0.187 ns, +0.034 ns WHS @ 250 MHz mining

Throughput: 24.4 kH/s per pipeline, 6.5 W average.
```

Then commit the new `b3miner_floorplan.xdc` and any RTL pragma changes
so the next builder gets a closure-tested starting point.

## Reference: known WNS ranges from similar KU5P designs

* Simple BLAKE3 (single compressor, no scratchpad): WNS +1.5 to +2.0 ns
* This design (out-of-box, no floorplan): WNS -0.5 to +0.5 ns expected
* This design (after A + B floorplan): WNS +0.3 to +0.8 ns expected
* DDR4-MIG-equipped designs: WNS rarely > +0.5 ns (MIG eats the budget)

If your WNS is below -1.5 ns after every knob above, the design needs
architectural rework -- the most likely culprit is the BRAM read-output
to G-function-input chain being too long. Insert a register between
`scratchpad_mem.ra_data` and `mixing_core.short_compress`, accepting
1 more cycle/iter.
