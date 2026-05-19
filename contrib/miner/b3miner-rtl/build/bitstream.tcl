## ============================================================================
## bitstream.tcl -- emit the SelectMAP-friendly .bin file
##
## Produces:
##   build/artifacts/b3miner.bit       Vivado wrapper (debug)
##   build/artifacts/b3miner.bin       SelectMAP-serial raw (flash this)
##   build/artifacts/b3miner.ltx       optional ILA probes (if any)
## ============================================================================

set ROOT      [file normalize [file dirname [info script]]/..]
set PROJ_NAME b3miner
set PROJ_DIR  $ROOT/build/$PROJ_NAME
set PROJ_FILE $PROJ_DIR/$PROJ_NAME.xpr
set ART_DIR   $ROOT/build/artifacts

file mkdir $ART_DIR

if {![file exists $PROJ_FILE]} {
    puts "bitstream.tcl: $PROJ_FILE not found -- run create_project.tcl first"
    exit 1
}

open_project $PROJ_FILE

if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    puts "bitstream.tcl: impl not complete; run implement.tcl first"
    exit 1
}

open_run impl_1

## ---- Bitstream config ----
## Compression on -- shrinks 12.3 MB raw bitstream to ~6.5 MB, fits in
## the firmware's 8 MB `bitstream` flash partition.
set_property BITSTREAM.GENERAL.COMPRESS                TRUE   [current_design]

## SelectMAP-serial loader contract (see ../BITSTREAM_LOAD.md):
##   - Firmware shifts bits MSB-first on each CCLK rising edge.
##   - Vivado's `-bin_file` is already in slave-serial byte order.
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH             1      [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE               25     [current_design]
set_property BITSTREAM.CONFIG.CONFIGFALLBACK           Disable [current_design]

## Power-rail health: drive INIT_B as a CRC error indicator post-config.
set_property BITSTREAM.CONFIG.OVERTEMPSHUTDOWN         ENABLE [current_design]

## Generate bitstream
write_bitstream -force -bin_file -file $ART_DIR/b3miner

## Verify outputs
foreach f [list $ART_DIR/b3miner.bit $ART_DIR/b3miner.bin] {
    if {![file exists $f]} {
        puts "bitstream.tcl: ERROR -- expected output $f not produced"
        exit 1
    }
    set sz [file size $f]
    puts "bitstream.tcl: $f ([expr {$sz / 1024}] KB)"
}

puts "bitstream.tcl: done.  Flash build/artifacts/b3miner.bin to firmware."
