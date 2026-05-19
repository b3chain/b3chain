# ============================================================================
# sim/verilator/Makefile -- one Verilator binary per TB.
#
# Usage from b3miner-rtl/:
#   make sim                  # via ../../Makefile (runs every TB)
#   make sim-one TB=tb_xxx    # ditto, single TB
#
# Direct usage from this dir:
#   make all
#   make run TB=tb_blake3_compress
#   make WAVES=1 run TB=tb_blake3_compress   # produces waves.vcd
# ============================================================================

ROOT      := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
RTL_DIR   := $(ROOT)/rtl
TB_DIR    := $(ROOT)/sim/tb
VECT_DIR  := $(ROOT)/sim/vectors
OBJ_DIR   := obj_dir

VERILATOR ?= verilator

# Every TB in sim/tb -- one binary each.
TBS := $(notdir $(basename $(wildcard $(TB_DIR)/tb_*.sv)))

# All RTL files compiled into every TB.  Verilator only links what's
# actually instantiated, so an unused module is free.
RTL := $(sort $(wildcard $(RTL_DIR)/*.sv))

# Common Verilator flags.
VFLAGS := -Wall -Wno-fatal --cc --exe --build \
          -j 4 \
          -CFLAGS -O2 \
          --top-module
ifdef WAVES
VFLAGS += --trace -CFLAGS -DWAVES
SIM_CPP_DEFS := -DWAVES -DVTOP_INCLUDE='"V$(TB).h"' -DVTOP=V$(TB)
else
SIM_CPP_DEFS := -DVTOP_INCLUDE='"V$(TB).h"' -DVTOP=V$(TB)
endif

# Force Verilator to pass -DSIM into the SV source so TBs can use $fopen with
# relative paths anchored at the vector directory.
VLT_DEFS := +define+SIM=1 +define+VECT_DIR=\"$(VECT_DIR)\"

INC_DIRS := +incdir+$(TB_DIR) +incdir+$(RTL_DIR)

.PHONY: all run clean help

help:
	@echo "Verilator harness for b3miner-rtl"
	@echo "  make TB=<tb_name> run         # build + run one TB"
	@echo "  make all                      # build every TB binary"
	@echo "  make clean                    # drop obj_dir/"

# Build any single TB binary.
$(OBJ_DIR)/V%/V%: $(RTL) $(TB_DIR)/%.sv sim_main.cpp
	@mkdir -p $(OBJ_DIR)/V$*
	$(VERILATOR) $(VFLAGS) $* \
	    $(VLT_DEFS) $(INC_DIRS) \
	    --Mdir $(OBJ_DIR)/V$* \
	    -o V$* \
	    $(RTL) $(TB_DIR)/$*.sv \
	    sim_main.cpp \
	    -CFLAGS "$(SIM_CPP_DEFS) -DVTOP_INCLUDE='\"V$*.h\"' -DVTOP=V$*"

run:
ifndef TB
	$(error "set TB=<tb_name>, e.g. make run TB=tb_blake3_compress")
endif
	$(MAKE) $(OBJ_DIR)/V$(TB)/V$(TB)
	cd $(VECT_DIR) && $(CURDIR)/$(OBJ_DIR)/V$(TB)/V$(TB)

all:
	@for tb in $(TBS); do \
	    echo "--- building $$tb ---"; \
	    $(MAKE) $(OBJ_DIR)/V$$tb/V$$tb || exit 1; \
	done

clean:
	rm -rf $(OBJ_DIR) waves.vcd
