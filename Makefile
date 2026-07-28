# Interpreter used by every target. The default assumes an activated environment,
# which is how these targets have always been invoked. There is no bare `python` on
# a stock macOS, so outside an activated venv pass it explicitly:
#     make PYTHON=.venv/bin/python check-facts
PYTHON ?= python

.PHONY: test lint build clean simulate docs checksums check-facts all

test:
	PYTHONPATH=src pytest -q

lint:
	ruff check src tests examples scripts

# Every document, both languages, into docs/pdf. Requires latexmk + XeLaTeX
# and the five Noto families listed at the top of docs/latex/_common.tex.
docs:
	$(PYTHON) scripts/build_docs.py

build: clean
	$(PYTHON) -m build

simulate:
	PYTHONPATH=src $(PYTHON) examples/run_monte_carlo.py

# Release integrity manifest. Regenerate whenever a tracked file changes,
# otherwise `shasum -a 256 -c SHA256SUMS_PROJECT.txt` reports stale failures.
# Uses git ls-files so the manifest and the repository cannot drift apart.
checksums:
	@git ls-files -z \
	  | grep -zv '^SHA256SUMS_PROJECT.txt$$' \
	  | xargs -0 shasum -a 256 > SHA256SUMS_PROJECT.txt
	@echo "wrote SHA256SUMS_PROJECT.txt ($$(wc -l < SHA256SUMS_PROJECT.txt | tr -d ' ') files)"

# Single source of truth for repeated numbers and retracted claims. Exits non-zero
# when a superseded claim survives outside the files that document the correction.
check-facts:
	$(PYTHON) scripts/check_facts.py

all: lint test docs build checksums

clean:
	rm -rf build dist .pytest_cache src/*.egg-info src/racergt.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
