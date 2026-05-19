## ============================================================================
## timing_explore.tcl -- auto-iterate Vivado strategies for timing closure.
##
## Usage (on a Vivado-licensed host):
##   cd b3miner-rtl
##   vivado -mode batch -source build/timing_explore.tcl
##
## Tries each (synth_strategy × impl_strategy) pair in order, recording
## WNS for each, and stops as soon as a combo closes timing (WNS >= 0.1 ns).
##
## See ../docs/TIMING_CLOSURE.md for the manual runbook.
## ============================================================================

set ROOT      [file normalize [file dirname [info script]]/..]
set PROJ_NAME b3miner
set PROJ_DIR  $ROOT/build/$PROJ_NAME
set PROJ_FILE $PROJ_DIR/$PROJ_NAME.xpr
set REP_DIR   $ROOT/build/reports

set CLOSURE_THRESH 0.100   ;# require WNS >= +0.100 ns to call it closed

if {![file exists $PROJ_FILE]} {
    puts "timing_explore.tcl: $PROJ_FILE not found -- run create_project.tcl first"
    exit 1
}

set strategy_pairs [list \
    [list {Vivado Synthesis Defaults}      {Vivado Implementation Defaults}] \
    [list {Flow_PerfOptimized_high}        {Performance_Explore}] \
    [list {Flow_PerfOptimized_high}        {Performance_ExploreWithRemap}] \
    [list {Flow_PerfOptimized_high}        {Performance_ExplorePostRoutePhysOpt}] \
    [list {Flow_AlternateRoutability}      {Performance_RefinePlacement}] \
    [list {Flow_RuntimeOptimized}          {Congestion_SpreadLogic_high}] \
]

set fp [open $REP_DIR/timing_explore_summary.txt w]
puts $fp "[clock format [clock seconds]] -- timing_explore on $PROJ_NAME"
puts $fp "Closure threshold: WNS >= $CLOSURE_THRESH ns"
puts $fp ""

set best_wns -999.0
set best_pair {}

foreach pair $strategy_pairs {
    set s [lindex $pair 0]
    set i [lindex $pair 1]
    puts $fp "----- synth='$s'  impl='$i' -----"
    flush $fp

    open_project $PROJ_FILE

    set_property strategy $s [get_runs synth_1]
    reset_run synth_1
    launch_runs synth_1 -jobs 8
    wait_on_run synth_1
    if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
        puts $fp "   SYNTH FAILED"
        close_project
        continue
    }

    set_property strategy $i [get_runs impl_1]
    reset_run impl_1
    launch_runs impl_1 -to_step route_design -jobs 8
    wait_on_run impl_1
    if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
        puts $fp "   IMPL  FAILED"
        close_project
        continue
    }

    set wns [get_property STATS.WNS [get_runs impl_1]]
    set tns [get_property STATS.TNS [get_runs impl_1]]
    puts $fp "   WNS = $wns ns, TNS = $tns ns"

    if {$wns > $best_wns} {
        set best_wns $wns
        set best_pair $pair
    }

    close_project

    if {$wns >= $CLOSURE_THRESH} {
        puts $fp ""
        puts $fp ">>> CLOSED with synth='$s' impl='$i' (WNS=$wns)"
        puts $fp ">>> Update build/synth.tcl + build/implement.tcl to lock in."
        break
    }
}

puts $fp ""
puts $fp "Best: synth='[lindex $best_pair 0]' impl='[lindex $best_pair 1]' WNS=$best_wns"
close $fp
puts "timing_explore.tcl: results in $REP_DIR/timing_explore_summary.txt"
