.PHONY: install install-all test test-verbose test-cov lint format typecheck check ci pre-push import-check prompt-check memory-eval live-eval clean pre-commit-install

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
	$(PYTHON) -m pytest tests/ --cov=nanobot --cov-report=term-missing --cov-fail-under=85

lint:
	ruff check nanobot/ tests/
	ruff format --check nanobot/ tests/

format:
	ruff format nanobot/ tests/
	ruff check --fix nanobot/ tests/

typecheck:
	$(PYTHON) -m mypy nanobot/

check: lint typecheck import-check prompt-check test

ci: lint typecheck import-check prompt-check test-cov

pre-push: ## Full CI validation + merge-readiness check (run before pushing PRs)
	@echo "=== Syncing with origin/main ==="
	git fetch origin main
	@if ! git merge-base --is-ancestor origin/main HEAD; then \
		echo "ERROR: Branch is behind origin/main. Run: git merge origin/main"; \
		exit 1; \
	fi
	@echo "=== Running full CI pipeline ==="
	$(MAKE) ci
	@echo ""
	@echo "✓ All checks passed — safe to push."

import-check:
	$(PYTHON) scripts/check_imports.py

prompt-check:
	$(PYTHON) scripts/check_prompt_manifest.py

memory-eval:
	$(PYTHON) scripts/memory_eval_ci.py \
		--workspace /tmp/memory_eval_workspace \
		--cases-file case/memory_eval_cases.json \
		--seed-events case/memory_seed_events.jsonl \
		--seed-profile case/memory_seed_profile.json \
		--baseline-file case/memory_eval_baseline.json \
		--output-file artifacts/memory_eval_latest.json \
		--history-file artifacts/memory_eval_history.json \
		--summary-file artifacts/memory_eval_summary.md \
		--strict

live-eval:
	$(PYTHON) scripts/eval_agent_live.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .pytest_cache *.egg-info dist build .ruff_cache

pre-commit-install:
	pre-commit install
