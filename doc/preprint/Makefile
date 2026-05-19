# Build the B3PoW-Scratch v1.1 IACR ePrint preprint.
#
# Target:  B3POW-SCRATCH-PREPRINT.pdf
# Engine:  XeLaTeX via latexmk (preferred) or xelatex+bibtex (fallback).
#
# Install (Debian / Ubuntu):
#   sudo apt install texlive-xetex texlive-latex-extra texlive-science \
#                    texlive-fonts-recommended latexmk biber
# Install (macOS):
#   brew install --cask mactex-no-gui          # or full mactex
# Install (Windows):
#   Install TeX Live or MiKTeX; add the bin directory to PATH.
#
# Style checks:
#   make check    # runs lacheck and chktex if present (warnings only)
#
# This Makefile intentionally does NOT depend on llncs.cls. See the
# header of B3POW-SCRATCH-PREPRINT.tex for how to switch the document
# class to llncs when targeting the actual ePrint submission.

NAME     := B3POW-SCRATCH-PREPRINT
SOURCE   := $(NAME).tex
BIB      := references.bib
PDF      := $(NAME).pdf

LATEXMK  := latexmk
XELATEX  := xelatex
BIBTEX   := bibtex
LACHECK  := lacheck
CHKTEX   := chktex

# latexmk flags. -interaction=nonstopmode keeps the build non-interactive
# in CI; -halt-on-error makes failure visible. -bibtex picks bibtex over
# biber, matching our `\bibliographystyle{unsrt}` (which biber tolerates
# but bibtex is the safer default for unsrt/splncs04).
LATEXMK_FLAGS := -xelatex -bibtex -interaction=nonstopmode -halt-on-error \
                 -file-line-error -shell-escape=0

.PHONY: all pdf clean distclean check tools

all: pdf

pdf: $(PDF)

# Preferred path: latexmk handles re-runs and bibtex passes for us.
# Fallback path (if latexmk is missing): manual xelatex + bibtex + xelatex
# + xelatex sequence.
$(PDF): $(SOURCE) $(BIB)
	@command -v $(LATEXMK) >/dev/null 2>&1 && { \
	  echo "Building with latexmk..."; \
	  $(LATEXMK) $(LATEXMK_FLAGS) $(NAME); \
	} || { \
	  echo "latexmk not found; falling back to manual xelatex passes."; \
	  command -v $(XELATEX) >/dev/null 2>&1 || { \
	    echo "ERROR: xelatex not installed."; \
	    echo "       Install TeX Live (see Makefile header)."; \
	    exit 1; }; \
	  command -v $(BIBTEX) >/dev/null 2>&1 || { \
	    echo "ERROR: bibtex not installed."; \
	    echo "       Install TeX Live (see Makefile header)."; \
	    exit 1; }; \
	  $(XELATEX) -interaction=nonstopmode -halt-on-error $(NAME); \
	  $(BIBTEX) $(NAME); \
	  $(XELATEX) -interaction=nonstopmode -halt-on-error $(NAME); \
	  $(XELATEX) -interaction=nonstopmode -halt-on-error $(NAME); \
	}

# Light style checks. Both `lacheck` and `chktex` are advisory; failures
# do not fail the build.
check:
	@if command -v $(LACHECK) >/dev/null 2>&1; then \
	  echo "--- lacheck ---"; $(LACHECK) $(SOURCE) || true; \
	else \
	  echo "lacheck not installed; skipping. (Debian/Ubuntu: apt install lacheck)"; \
	fi
	@if command -v $(CHKTEX) >/dev/null 2>&1; then \
	  echo "--- chktex ---"; $(CHKTEX) -q $(SOURCE) || true; \
	else \
	  echo "chktex not installed; skipping. (Debian/Ubuntu: apt install chktex)"; \
	fi

# Quick "what do I have?" introspection.
tools:
	@echo "latexmk : $$($(LATEXMK) -version 2>/dev/null | head -1 || echo 'NOT FOUND')"
	@echo "xelatex : $$($(XELATEX) -version 2>/dev/null | head -1 || echo 'NOT FOUND')"
	@echo "bibtex  : $$($(BIBTEX) -version 2>/dev/null | head -1 || echo 'NOT FOUND')"
	@echo "lacheck : $$(command -v $(LACHECK) 2>/dev/null || echo 'NOT FOUND')"
	@echo "chktex  : $$(command -v $(CHKTEX)  2>/dev/null || echo 'NOT FOUND')"

clean:
	@if command -v $(LATEXMK) >/dev/null 2>&1; then \
	  $(LATEXMK) -c $(NAME); \
	else \
	  rm -f $(NAME).aux $(NAME).bbl $(NAME).blg $(NAME).log $(NAME).toc \
	        $(NAME).out $(NAME).fls $(NAME).fdb_latexmk $(NAME).synctex.gz; \
	fi

distclean: clean
	rm -f $(PDF)
