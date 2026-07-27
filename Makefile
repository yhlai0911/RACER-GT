.PHONY: test build clean simulate paper

test:
	PYTHONPATH=src pytest -q

build: clean
	python -m build

simulate:
	PYTHONPATH=src python examples/run_monte_carlo.py

paper:
	cd paper && latexmk -xelatex -interaction=nonstopmode -halt-on-error RACER_GT_Methodology_zh_TW.tex

clean:
	rm -rf build dist .pytest_cache src/*.egg-info src/racergt.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
