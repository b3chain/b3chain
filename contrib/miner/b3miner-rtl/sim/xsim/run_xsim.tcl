## ============================================================================
## run_xsim.tcl -- XSIM fallback for Xilinx-IP-heavy TBs
##
## Usage:
##   cd b3miner-rtl/sim/xsim
##   vivado -mode batch -source run_xsim.tcl -tclargs <tb_name>
##
## Most TBs run faster under Verilator; use XSIM when the TB needs
## simulation models for MMCME4_ADV, XADC, or other primitives that
## Verilator doesn't model accurately.
## ============================================================================

if {[llength $argv] < 1} {
    puts "usage: vivado -mode batch -source run_xsim.tcl -tclargs <tb_name>"
    exit 1
}

set TB        [lindex $argv 0]
set ROOT      [file normalize [file dirname [info script]]/../..]
set RTL_DIR   $ROOT/rtl
set TB_DIR    $ROOT/sim/tb
set VECT_DIR  $ROOT/sim/vectors

puts "run_xsim.tcl: TB        = $TB"
puts "run_xsim.tcl: ROOT      = $ROOT"
puts "run_xsim.tcl: VECT_DIR  = $VECT_DIR"

if {![file exists $TB_DIR/$TB.sv]} {
    puts "run_xsim.tcl: ERROR -- $TB_DIR/$TB.sv not found"
    exit 1
}

set work_dir [file normalize ./xsim_work_$TB]
file mkdir $work_dir

cd $work_dir

set rtl_files [glob $RTL_DIR/*.sv]

## Compile
exec xvlog -sv \
    -L unisims_ver -L unimacro_ver -L secureip \
    -d "SIM=1" -d "VECT_DIR=\"$VECT_DIR\"" \
    -i $RTL_DIR -i $TB_DIR \
    {*}$rtl_files $TB_DIR/$TB.sv 2>@1

## Elaborate
exec xelab -debug typical -L unisims_ver -L unimacro_ver -L secureip \
    -relax $TB sim.glbl 2>@1

## Run -- TB owns $finish
exec xsim ${TB}_behav -R 2>@1

puts "run_xsim.tcl: $TB completed"
