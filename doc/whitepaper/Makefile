# Render the B3PoW-Scratch v1.1 whitepaper to PDF and HTML.
#
# Tooling: pandoc + (xelatex | tectonic). Install on Debian/Ubuntu with:
#   sudo apt install pandoc texlive-xetex texlive-fonts-recommended \
#                    texlive-latex-extra librsvg2-bin
# Install on macOS with:
#   brew install pandoc tectonic librsvg
#
# A reproducible build is also wired through CI (.github/workflows/release.yml)
# and produces SHA256-pinned PDF artefacts attached to each tagged release.

SOURCE     := B3POW-SCRATCH-WHITEPAPER.md
PDF        := B3POW-SCRATCH-WHITEPAPER.pdf
HTML       := B3POW-SCRATCH-WHITEPAPER.html
TEMPLATE   := template.tex
DIAGRAMS   := ../diagrams
PANDOC     := pandoc
PANDOC_OPTS := --from=markdown+yaml_metadata_block+pipe_tables+fenced_code_blocks+raw_html \
               --toc --number-sections \
               --resource-path=.:$(DIAGRAMS) \
               --highlight-style=tango \
               -V documentclass=article \
               -V geometry:margin=1in \
               -V mainfont="Latin Modern Roman" \
               -V monofont="Latin Modern Mono" \
               -V colorlinks=true \
               -V linkcolor=blue \
               -V urlcolor=blue \
               -V toccolor=black

.PHONY: all pdf html clean lint

all: pdf html

pdf: $(PDF)

html: $(HTML)

$(PDF): $(SOURCE) $(TEMPLATE)
	$(PANDOC) $(PANDOC_OPTS) \
	  --template=$(TEMPLATE) \
	  --pdf-engine=xelatex \
	  -o $@ $(SOURCE)

$(HTML): $(SOURCE)
	$(PANDOC) $(PANDOC_OPTS) \
	  --standalone \
	  --self-contained \
	  --css=../diagrams/whitepaper.css \
	  -o $@ $(SOURCE)

# Sanity-check: every internal markdown link should resolve.
lint: $(SOURCE)
	@command -v markdown-link-check >/dev/null || { \
	  echo "markdown-link-check not installed; npm i -g markdown-link-check"; \
	  exit 1; }
	markdown-link-check --quiet $(SOURCE) || true

clean:
	rm -f $(PDF) $(HTML) *.aux *.log *.out *.toc

# Reproducible-build helper: emits SHA256 of every generated artefact
# under SOURCE_DATE_EPOCH-pinned build conditions.
.PHONY: repro
repro:
	SOURCE_DATE_EPOCH=$$(git log -1 --pretty=%ct $(SOURCE)) $(MAKE) all
	sha256sum $(PDF) $(HTML)
