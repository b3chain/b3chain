set script_dir [file normalize [file dirname [info script]]]
set root [file normalize [file join $script_dir ../../..]]
set profile [file normalize [file join $script_dir ..]]
set build_dir [file join $root build xcku5p_b3miner]
set report_dir [file join $build_dir reports]
set part xcku5p-ffvb676-2-e
set top xcku5p_b3miner_top

file mkdir $build_dir
file mkdir $report_dir
create_project xcku5p_b3miner $build_dir -part $part -force
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]

add_files [glob [file join $root rtl *.sv]]
add_files [file join $profile rtl xcku5p_b3miner_top.sv]
add_files -fileset constrs_1 [file join $profile xdc xcku5p_b3miner_pins.xdc]
add_files -fileset constrs_1 [file join $profile xdc xcku5p_b3miner_timing.xdc]
set cdc_xdc [file join $profile xdc xcku5p_b3miner_cdc_impl.xdc]
add_files -fileset constrs_1 $cdc_xdc
set_property USED_IN_SYNTHESIS false [get_files $cdc_xdc]
set_property USED_IN_IMPLEMENTATION true [get_files $cdc_xdc]
set_property top $top [current_fileset]
update_compile_order -fileset sources_1

puts "PROJECT_PART: [get_property PART [current_project]]"
puts "PROJECT_TOP: [get_property TOP [current_fileset]]"
puts "SOURCE_FILES_BEGIN"
foreach source [get_files -of_objects [get_filesets sources_1]] { puts $source }
puts "SOURCE_FILES_END"
puts "CONSTRAINT_FILES_BEGIN"
foreach xdc [get_files -of_objects [get_filesets constrs_1]] { puts $xdc }
puts "CONSTRAINT_FILES_END"

# RTL elaboration is a hard gate before synthesis.
synth_design -rtl -name rtl_gate
set expected_ports {sys_clk_p sys_clk_n spi_sck spi_mosi spi_miso spi_csn share_irq user_key_n led_busy_n led_share_n}
set actual_ports [lsort [get_property NAME [get_ports]]]
if {$actual_ports ne [lsort $expected_ports]} {
    puts "ELAB_PORT_MISMATCH expected=[lsort $expected_ports] actual=$actual_ports"
    exit 2
}
foreach port $expected_ports {
    puts "ELAB_PORT $port PIN=[get_property PACKAGE_PIN [get_ports $port]] IOSTANDARD=[get_property IOSTANDARD [get_ports $port]]"
}
set clock_std [get_property IOSTANDARD [get_ports sys_clk_p]]
if {$clock_std ne "DIFF_SSTL12"} {
    puts "ELAB_CLOCK_STANDARD_FAIL $clock_std"
    exit 2
}
set diff_term [get_property DIFF_TERM [get_cells u_clock_input]]
puts "ELAB_IBUFDS_DIFF_TERM: $diff_term"
if {$diff_term ni {"FALSE" "0"}} {
    puts "ELAB_DIFF_TERM_FAIL"
    exit 2
}
puts "ELABORATION: PASS"
close_design

reset_run synth_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set synth_progress [get_property PROGRESS [get_runs synth_1]]
puts "SYNTH_PROGRESS: $synth_progress"
puts "SYNTH_STATUS: [get_property STATUS [get_runs synth_1]]"
if {$synth_progress ne "100%"} { exit 2 }
open_run synth_1
report_utilization -file [file join $report_dir utilization_synth.rpt]
report_clocks -file [file join $report_dir clocks_synth.rpt]
report_cdc -details -file [file join $report_dir cdc_synth.rpt]
close_design

launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
set impl_progress [get_property PROGRESS [get_runs impl_1]]
puts "IMPL_PROGRESS: $impl_progress"
puts "IMPL_STATUS: [get_property STATUS [get_runs impl_1]]"
if {$impl_progress ne "100%"} { exit 2 }
open_run impl_1
report_utilization -file [file join $report_dir utilization_impl.rpt]
report_timing_summary -file [file join $report_dir timing.rpt]
report_drc -file [file join $report_dir drc.rpt]
report_methodology -file [file join $report_dir methodology.rpt]
report_cdc -details -file [file join $report_dir cdc_impl.rpt]
report_io -file [file join $report_dir io.rpt]
report_power -file [file join $report_dir power.rpt]
report_route_status -file [file join $report_dir route_status.rpt]

set setup_path [get_timing_paths -setup -max_paths 1]
set hold_path [get_timing_paths -hold -max_paths 1]
puts "TIMING_WNS: [get_property SLACK $setup_path]"
puts "TIMING_WHS: [get_property SLACK $hold_path]"
set wns [get_property SLACK $setup_path]
set whs [get_property SLACK $hold_path]
if {$wns < 0.0 || $whs < 0.0} {
    puts "TIMING_GATE: FAIL"
    exit 2
}
puts "TIMING_GATE: PASS"

set checkpoint [file join $build_dir xcku5p_b3miner_routed.dcp]
set bitstream [file join $build_dir xcku5p_b3miner.bit]
write_checkpoint -force $checkpoint
write_bitstream -force $bitstream
puts "CHECKPOINT: $checkpoint"
puts "BITSTREAM: $bitstream"
puts "BOARD_BUILD_DONE"
exit 0
