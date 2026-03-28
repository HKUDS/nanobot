.PHONY: install install-all test test-verbose test-cov test-integration lint format typecheck check ci pre-push import-check structure-check prompt-check phase-todo-check doc-check memory-eval live-eval clean worktree-clean pre-commit-install

PYTHON ?= $(shell python3 --version >/dev/null 2>&1 && echo python3 || echo python)

install:
	$(PYTHON) -m pip install -e ".[dev]"

install-all:
	$(PYTHON) -m pip install -e ".[dev,oauth]"
	cd bridge && npm install

test:  ## Fast unit tests only (every edit)
	$(PYTHON) -m pytest tests/ --ignore=tests/integration -x -q

test-verbose:
	$(PYTHON) -m pytest tests/ --ignore=tests/integration -v

test-cov:
	$(PYTHON) -m pytest tests/ --ignore=tests/integration --cov=nanobot --cov-report=term-missing --cov-report=json --cov-fail-under=85

test-integration:  ## Integration tests (before push, LLM tests need API key)
	$(PYTHON) -m pytest tests/integration/ -v --tb=short -x

lint:
	ruff check nanobot/ tests/
	ruff format --check nanobot/ tests/

format:
	ruff format nanobot/ tests/
	ruff check --fix nanobot/ tests/

typecheck:
	$(PYTHON) -m mypy nanobot/

check: lint typecheck import-check structure-check prompt-check phase-todo-check doc-check test test-integration

ci: lint typecheck import-check structure-check prompt-check phase-todo-check doc-check test-cov test-integration

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

structure-check:
	$(PYTHON) scripts/check_structure.py

prompt-check:
	$(PYTHON) scripts/check_prompt_manifest.py

phase-todo-check:
	$(PYTHON) scripts/check_phase_todos.py

doc-check:
	$(PYTHON) scripts/check_doc_references.py

memory-eval:
	$(PYTHON) scripts/memory_eval_trend.py \
		--workspace /tmp/memory_eval_workspace \
		--cases-file case/memory_eval_cases.json \
		--seed-events case/memory_seed_events.jsonl \
		--seed-profile case/memory_seed_profile.json \
		--output-file artifacts/memory_eval_latest.json \
		--history-file artifacts/memory_eval_history.json \
		--summary-file artifacts/memory_eval_summary.md

live-eval:
	$(PYTHON) scripts/eval_agent_live.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .pytest_cache *.egg-info dist build .ruff_cache

worktree-clean:
	@echo "Pruning stale worktrees..."
	git worktree prune
	@echo "Active worktrees:"
	git worktree list

pre-commit-install:
	pre-commit install
