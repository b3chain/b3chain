## ============================================================================
## reports.tcl -- collect a summary of timing/util/power for human review
##
## Run AFTER implement.tcl + bitstream.tcl.  Produces:
##   build/reports/summary.txt          one-page status
##   build/reports/timing_*.rpt         detailed (regenerated)
##   build/reports/utilization_*.rpt    detailed (regenerated)
## ============================================================================

set ROOT      [file normalize [file dirname [info script]]/..]
set PROJ_NAME b3miner
set PROJ_DIR  $ROOT/build/$PROJ_NAME
set PROJ_FILE $PROJ_DIR/$PROJ_NAME.xpr
set REP_DIR   $ROOT/build/reports

file mkdir $REP_DIR

if {![file exists $PROJ_FILE]} {
    puts "reports.tcl: $PROJ_FILE not found"
    exit 1
}

open_project $PROJ_FILE
open_run impl_1

set wns  [get_property STATS.WNS [get_runs impl_1]]
set whs  [get_property STATS.WHS [get_runs impl_1]]
set tns  [get_property STATS.TNS [get_runs impl_1]]
set ths  [get_property STATS.THS [get_runs impl_1]]

set lut_used   [get_property SLACK [get_cells -hierarchical] -default "n/a"]
set u_report   [report_utilization -hierarchical -return_string]
set t_report   [report_timing_summary -return_string]
set p_report   [report_power -return_string]

set fp [open $REP_DIR/summary.txt w]
puts $fp "============================================================"
puts $fp "  b3miner-rtl post-route summary"
puts $fp "  Date: [clock format [clock seconds]]"
puts $fp "  Part: [get_property PART [current_project]]"
puts $fp "============================================================"
puts $fp ""
puts $fp "Timing (250 MHz mining clock target):"
puts $fp "  WNS = $wns ns    (must be >= 0)"
puts $fp "  WHS = $whs ns"
puts $fp "  TNS = $tns ns"
puts $fp "  THS = $ths ns"
puts $fp ""
puts $fp "Utilisation:"
puts $fp $u_report
puts $fp ""
puts $fp "Power:"
puts $fp $p_report
puts $fp ""
puts $fp "Timing summary:"
puts $fp $t_report
close $fp

puts "reports.tcl: build/reports/summary.txt written"

## Also regenerate the standalone reports so they're never stale.
report_utilization -hierarchical -file $REP_DIR/utilization_post_route.rpt
report_timing_summary             -file $REP_DIR/timing_post_route.rpt
report_power                      -file $REP_DIR/power_post_route.rpt
