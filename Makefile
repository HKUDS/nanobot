.PHONY: install install-all test test-verbose test-cov lint format typecheck check memory-eval clean pre-commit-install

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -e ".[dev]"

install-all:
	$(PYTHON) -m pip install -e ".[dev,reranker,oauth]"
	cd bridge && npm install

test:
	$(PYTHON) -m pytest tests/ -x -q

test-verbose:
	$(PYTHON) -m pytest tests/ -v

test-cov:
	$(PYTHON) -m pytest tests/ --cov=nanobot --cov-report=term-missing

lint:
	ruff check nanobot/ tests/

format:
	ruff format nanobot/ tests/
	ruff check --fix nanobot/ tests/

typecheck:
	$(PYTHON) -m mypy nanobot/

check: lint typecheck test

memory-eval:
	$(PYTHON) scripts/memory_eval_ci.py --strict

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .pytest_cache *.egg-info dist build .ruff_cache

pre-commit-install:
	pre-commit install
