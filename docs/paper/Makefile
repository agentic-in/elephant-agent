# Makefile for the Elephant Agent system report
# Usage:
#   make        - full PDF build
#   make quick  - single pdflatex pass
#   make clean  - remove generated files
#   make wc     - approximate word count
#   make check  - inspect the latest log for common issues

MAIN     = main
OUTNAME  = Elephant_Agent__Agency_First_Personal_AI
TEX      = pdflatex
BIB      = bibtex
TEXFLAGS = -interaction=nonstopmode -halt-on-error -file-line-error -jobname=$(OUTNAME)

SECTIONS = $(wildcard sections/*.tex)
SOURCES  = $(MAIN).tex $(SECTIONS) references.bib elephant.cls assets/elephant-logo.png assets/logo_AIL.png assets/agentic-intelligence-lab-logo.png assets/agentic-intelligence-lab-lockup.png
RESOURCE_FIGURES = ../../apps/site/static/assets/resources/paper-1.png ../../apps/site/static/assets/resources/paper-2.png ../../apps/site/static/assets/resources/paper-3.png ../../apps/site/static/assets/resources/paper-4.png ../../apps/site/static/assets/resources/paper-5.png ../../apps/site/static/assets/resources/paper-6.png ../../apps/site/static/assets/resources/paper-7.png
AUX_EXTS = aux bbl blg log out toc lof lot fls fdb_latexmk synctex.gz nav snm vrb run.xml bcf

.PHONY: all quick clean wc check

all: $(OUTNAME).pdf

$(OUTNAME).pdf: $(SOURCES) $(RESOURCE_FIGURES)
	$(TEX) $(TEXFLAGS) $(MAIN)
	$(BIB) $(OUTNAME) || true
	$(TEX) $(TEXFLAGS) $(MAIN)
	$(TEX) $(TEXFLAGS) $(MAIN)
	@echo ""
	@echo "=== Build complete: $(OUTNAME).pdf ==="

quick:
	$(TEX) $(TEXFLAGS) $(MAIN)
	@echo ""
	@echo "=== Quick build complete: $(OUTNAME).pdf ==="

clean:
	@for ext in $(AUX_EXTS); do \
		rm -f $(OUTNAME).$$ext; \
	done
	@rm -f $(OUTNAME).pdf
	@echo "=== Cleaned ==="

wc:
	@echo "=== Approximate word count ==="
	@cat sections/*.tex | \
		sed 's/\\[a-zA-Z]*\(\[[^]]*\]\)\?{[^}]*}//g' | \
		sed 's/\\[a-zA-Z]*//g' | \
		sed 's/[{}$$\\]//g' | \
		wc -w | \
		xargs -I{} echo "  Body text: ~{} words"
	@echo "  Sections:  $$(ls sections/*.tex | wc -l) files"
	@echo "  Total TeX: $$(cat $(MAIN).tex sections/*.tex | wc -l) lines"

check:
	@echo "=== Checking for common issues ==="
	@echo "Undefined references:"
	@grep -c 'undefined' $(OUTNAME).log 2>/dev/null || echo "  (none or not yet compiled)"
	@echo "Missing citations:"
	@grep -c 'Citation.*undefined' $(OUTNAME).log 2>/dev/null || echo "  (none or not yet compiled)"
	@echo "Overfull boxes:"
	@grep -c 'Overfull' $(OUTNAME).log 2>/dev/null || echo "  (none or not yet compiled)"
