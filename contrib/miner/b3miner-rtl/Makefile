# b3miner-rtl top-level Makefile
# Targets thin-wrap the scripts in ci/ and build/.
# Run `make help` to list everything.

SHELL := /bin/bash

PYTHON ?= python3
VIVADO ?= vivado
VERILATOR ?= verilator

REF_DIR    := ref
SIM_DIR    := sim
RTL_DIR    := rtl
BUILD_DIR  := build
CI_DIR     := ci

VECTORS_DIR := $(SIM_DIR)/vectors
ARTIFACTS   := $(BUILD_DIR)/artifacts

.PHONY: help
help:
	@echo "B3Miner-RTL targets:"
	@echo "  make ref-test    run pytest on ref/ (Python reference correctness)"
	@echo "  make vectors     regenerate sim/vectors/*.hex from ref/b3pow_ref.py"
	@echo "  make lint        verilator --lint-only -Wall on rtl/"
	@echo "  make sim         run every TB under sim/tb/ via Verilator"
	@echo "  make sim-one TB=tb_blake3_compress   run a single TB"
	@echo "  make synth-oc    OOC synth each leaf module (Vivado)"
	@echo "  make synth       full design synth (Vivado)"
	@echo "  make impl        place + route (Vivado)"
	@echo "  make bin         write b3miner.bin into build/artifacts/ (Vivado)"
	@echo "  make report      collect timing / utilisation reports"
	@echo "  make clean       drop generated files (keeps SPEC/RTL/refs)"

# --- Python reference ----------------------------------------------------

.PHONY: ref-test
ref-test:
	cd $(REF_DIR) && $(PYTHON) -m pytest -q

.PHONY: vectors
vectors:
	mkdir -p $(VECTORS_DIR)
	cd $(REF_DIR) && $(PYTHON) gen_vectors.py --out ../$(VECTORS_DIR)

# --- Verilator ----------------------------------------------------------

.PHONY: lint
lint:
	bash $(CI_DIR)/lint.sh

.PHONY: sim
sim: vectors
	bash $(CI_DIR)/sim.sh

.PHONY: sim-one
sim-one: vectors
	$(MAKE) -C $(SIM_DIR)/verilator TB=$(TB) run

# --- Vivado --------------------------------------------------------------

.PHONY: synth-oc
synth-oc:
	bash $(CI_DIR)/synth_oc.sh

.PHONY: synth
synth:
	$(VIVADO) -mode batch -source $(BUILD_DIR)/create_project.tcl
	$(VIVADO) -mode batch -source $(BUILD_DIR)/synth.tcl

.PHONY: impl
impl:
	$(VIVADO) -mode batch -source $(BUILD_DIR)/implement.tcl

.PHONY: bin
bin: | $(ARTIFACTS)
	$(VIVADO) -mode batch -source $(BUILD_DIR)/bitstream.tcl

.PHONY: report
report:
	$(VIVADO) -mode batch -source $(BUILD_DIR)/reports.tcl

.PHONY: timing-explore
timing-explore:
	$(VIVADO) -mode batch -source $(BUILD_DIR)/timing_explore.tcl

$(ARTIFACTS):
	mkdir -p $@

# --- Clean ---------------------------------------------------------------

.PHONY: clean
clean:
	rm -rf $(VECTORS_DIR)/*.hex
	rm -rf $(SIM_DIR)/verilator/obj_dir
	rm -rf $(BUILD_DIR)/b3miner.* $(BUILD_DIR)/*.cache \
	       $(BUILD_DIR)/*.runs $(BUILD_DIR)/*.sim \
	       $(BUILD_DIR)/*.gen $(BUILD_DIR)/*.hw $(BUILD_DIR)/*.ip_user_files \
	       $(BUILD_DIR)/*.srcs $(BUILD_DIR)/*.xpr $(BUILD_DIR)/.Xil \
	       $(BUILD_DIR)/artifacts/* $(BUILD_DIR)/reports/* \
	       vivado*.{jou,log}
