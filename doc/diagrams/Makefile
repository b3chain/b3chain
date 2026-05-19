# Render B3PoW-Scratch v1.1 launch diagrams to SVG and PDF.
#
# Tooling: mermaid-cli (mmdc). Install with:
#   npm install -g @mermaid-js/mermaid-cli
#
# Outputs land in ./out/ (gitignored). The whitepaper Makefile in
# ../whitepaper/ expects the SVGs to already exist (it does not invoke
# mmdc itself) — build the diagrams before rendering the whitepaper:
#
#   cd doc/diagrams  && make svg
#   cd ../whitepaper && make pdf
#
# Targets:
#   make svg     # render every .mmd to out/*.svg
#   make pdf     # render every .mmd to out/*.pdf
#   make all     # both
#   make check   # parse every .mmd through mmdc into a throwaway tmp file
#   make clean   # remove ./out/

MMDC      ?= mmdc
OUT_DIR   := out
SRC       := $(wildcard *.mmd)
SVGS      := $(SRC:%.mmd=$(OUT_DIR)/%.svg)
PDFS      := $(SRC:%.mmd=$(OUT_DIR)/%.pdf)

.PHONY: all svg pdf check clean check-mmdc

all: svg pdf

svg: check-mmdc $(SVGS)

pdf: check-mmdc $(PDFS)

check-mmdc:
	@command -v $(MMDC) >/dev/null 2>&1 || { \
	  echo "ERROR: mermaid-cli (mmdc) is not installed."; \
	  echo "Install with: npm install -g @mermaid-js/mermaid-cli"; \
	  exit 1; }

$(OUT_DIR):
	@mkdir -p $(OUT_DIR)

$(OUT_DIR)/%.svg: %.mmd | $(OUT_DIR)
	$(MMDC) -i $< -o $@

$(OUT_DIR)/%.pdf: %.mmd | $(OUT_DIR)
	$(MMDC) -i $< -o $@

# Parse-only sanity check: render each .mmd into a throwaway tempdir and
# discard the artifacts.  Used in CI and pre-commit.
check: check-mmdc
	@set -e; \
	tmpdir=$$(mktemp -d); \
	trap "rm -rf $$tmpdir" EXIT; \
	for f in $(SRC); do \
	  echo "checking $$f ..."; \
	  $(MMDC) -i $$f -o $$tmpdir/$$(basename $$f .mmd).svg >/dev/null; \
	done; \
	echo "OK: all $(words $(SRC)) diagram(s) parsed"

clean:
	rm -rf $(OUT_DIR)
