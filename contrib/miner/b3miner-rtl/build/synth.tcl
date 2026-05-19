## ============================================================================
## synth.tcl -- run synthesis (Vivado XPR project must already exist)
## ============================================================================

set ROOT      [file normalize [file dirname [info script]]/..]
set PROJ_NAME b3miner
set PROJ_DIR  $ROOT/build/$PROJ_NAME
set PROJ_FILE $PROJ_DIR/$PROJ_NAME.xpr

if {![file exists $PROJ_FILE]} {
    puts "synth.tcl: $PROJ_FILE not found -- run create_project.tcl first"
    exit 1
}

open_project $PROJ_FILE

## Performance-leaning synth strategy (default is balanced).  For first
## bring-up we use Default; switch to Flow_PerfOptimized_high after
## timing closure is a real concern.
set_property strategy {Vivado Synthesis Defaults} [get_runs synth_1]

## Re-run synth from scratch if it's done; reset on failure too.
reset_run synth_1
launch_runs synth_1 -jobs 8
wait_on_run synth_1

if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    puts "synth.tcl: synthesis did not complete cleanly"
    exit 1
}

open_run synth_1

## Sanity-check reports
report_utilization -hierarchical -file $ROOT/build/reports/utilization_post_synth.rpt
report_timing_summary -file $ROOT/build/reports/timing_post_synth.rpt
report_clock_interaction -file $ROOT/build/reports/clock_interaction_post_synth.rpt

puts "synth.tcl: synthesis complete; reports in build/reports/"
