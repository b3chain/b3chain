## ============================================================================
## create_project.tcl -- bootstrap Vivado project for b3miner-rtl
##
## Usage:
##   cd b3chain/contrib/miner/b3miner-rtl
##   vivado -mode batch -source build/create_project.tcl
##
## Idempotent: drops the existing project if present and rebuilds it from
## scratch.  All sources are added by reference so an in-tree git edit shows
## up on the next `synth`.
## ============================================================================

set ROOT          [file normalize [file dirname [info script]]/..]
set PROJ_NAME     b3miner
set PROJ_DIR      $ROOT/build/$PROJ_NAME
set PART          xcku5p-ffvb676-2-i
set TOP           b3miner_top

puts "create_project.tcl: ROOT      = $ROOT"
puts "create_project.tcl: PROJ_DIR  = $PROJ_DIR"
puts "create_project.tcl: PART      = $PART"

if {[file isdirectory $PROJ_DIR]} {
    puts "removing existing project at $PROJ_DIR"
    file delete -force $PROJ_DIR
}

create_project $PROJ_NAME $PROJ_DIR -part $PART -force
set_property target_language Verilog [current_project]
set_property default_lib     work    [current_project]

## ---- RTL ----
set rtl_files [lsort [glob -nocomplain $ROOT/rtl/*.sv]]
add_files -norecurse $rtl_files
set_property file_type {SystemVerilog} [get_files $rtl_files]

## params_pkg.sv must compile first
set_property used_in_synthesis true [get_files $ROOT/rtl/params_pkg.sv]
set_property is_global_include true [get_files $ROOT/rtl/params_pkg.sv]

## ---- XDC ----
set xdc_files [list \
    $ROOT/build/xdc/b3miner_pins.xdc \
    $ROOT/build/xdc/b3miner_timing.xdc \
    $ROOT/build/xdc/b3miner_falsepaths.xdc \
]
add_files -fileset constrs_1 -norecurse $xdc_files

## ---- Set top ----
set_property top $TOP [current_fileset]
update_compile_order -fileset sources_1

## ---- IP catalogue ----
## The XADC primitive lives in the device library, no extra IP needed.
## MMCM is also a primitive (MMCME4_ADV).  If we later add Xilinx IP cores,
## generate them here.

puts "create_project.tcl: done"
