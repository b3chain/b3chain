# Volatile FPGA configuration only. No configuration-memory operations.
set root [file normalize [file join [file dirname [info script]] ../../..]]
set bit [file join $root build xcku5p_b3miner xcku5p_b3miner.bit]
set expected_idcode 00000100101001100010000010010011

open_hw_manager
connect_hw_server -url localhost:3121
refresh_hw_server
set targets [get_hw_targets]
if {[llength $targets] != 1} {
    puts "TARGET_COUNT_FAIL: [llength $targets]"
    exit 2
}
open_hw_target [lindex $targets 0]
set devices [get_hw_devices]
if {[llength $devices] != 1} {
    puts "DEVICE_COUNT_FAIL: [llength $devices]"
    exit 2
}
set device [lindex $devices 0]
set part [get_property PART $device]
set idcode [get_property IDCODE $device]
puts "DEVICE_PART: $part"
puts "DEVICE_IDCODE: $idcode"
if {$part ne "xcku5p" || $idcode ne $expected_idcode} {
    puts "DEVICE_IDENTITY_FAIL"
    exit 2
}
set_property PROGRAM.FILE $bit $device
program_hw_devices $device
refresh_hw_device $device
puts "VOLATILE_PROGRAM_DONE"
close_hw_target
disconnect_hw_server
close_hw_manager
exit 0
