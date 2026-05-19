## ============================================================================
## implement.tcl -- place + route + post-route reports
## ============================================================================

set ROOT      [file normalize [file dirname [info script]]/..]
set PROJ_NAME b3miner
set PROJ_DIR  $ROOT/build/$PROJ_NAME
set PROJ_FILE $PROJ_DIR/$PROJ_NAME.xpr

if {![file exists $PROJ_FILE]} {
    puts "implement.tcl: $PROJ_FILE not found -- run create_project.tcl first"
    exit 1
}

open_project $PROJ_FILE

if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    puts "implement.tcl: synth not complete; run synth.tcl first"
    exit 1
}

## Place + route strategy.  Performance_Explore is a sane first pick;
## upgrade to Performance_ExplorePostRoutePhysOpt after timing-closure
## iterations.
set_property strategy Performance_Explore [get_runs impl_1]

reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1

if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    puts "implement.tcl: implementation did not complete cleanly"
    exit 1
}

open_run impl_1

report_utilization -hierarchical -file $ROOT/build/reports/utilization_post_route.rpt
report_timing_summary -file $ROOT/build/reports/timing_post_route.rpt
report_drc -file $ROOT/build/reports/drc_post_route.rpt
report_power -file $ROOT/build/reports/power_post_route.rpt
report_methodology -file $ROOT/build/reports/methodology_post_route.rpt

set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
puts "implement.tcl: WNS = $wns ns, WHS = $whs ns"
if {[expr {$wns < 0.0}]} {
    puts "implement.tcl: WARNING -- negative WNS; iterate timing constraints / pipeline"
}

puts "implement.tcl: place+route complete"
