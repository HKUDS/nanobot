## Plan: LLM Agent Development Hardening

Make the nanobot codebase significantly easier for LLM coding agents (GitHub Copilot, Claude Code, Codex CLI) to navigate, modify, and validate by adding agent instruction files, a Makefile task runner, type checking enforcement, pre-commit hooks, a contributing guide, and improved module-level documentation. Branch: `feature/agent-hardening`.

---

### TL;DR

Nanobot has strong foundations (95%+ type hints, structured errors, `__all__` exports, ruff configured, good async tests) but lacks the scaffolding that LLM agents rely on: no instruction files telling agents about project conventions, no task runner for validation commands, no type checker enforcement, no pre-commit hooks, and no contributor guide. This plan adds all of these with zero logic changes.

---

**Steps**

### Phase 1 — Agent Instruction Files (highest impact)

Agents read these files automatically to understand project conventions. This is the single biggest quality improvement for agent-assisted development.

**1. Create `.github/copilot-instructions.md`**

GitHub Copilot in VS Code reads this automatically. Content covers:
- Project overview: ultra-lightweight agent framework (~4K LOC core, bus-based, provider-agnostic)
- Python conventions: 3.10+ target, `|` union syntax (not `Union`), `from __future__ import annotations` in all modules
- Async patterns: `async/await` everywhere, `Protocol` for interfaces, parallel tool execution for readonly ops
- Config: Pydantic models in `nanobot/config/schema.py`, `AgentConfig` in `nanobot/agent/loop.py`
- Testing: pytest-asyncio, `ScriptedProvider` for mocks, `@pytest.mark.parametrize` for coverage
- Tool development: extend `Tool` base in `nanobot/agent/tools/base.py`, return `ToolResult`, register via `ToolRegistry`
- Coding standards: ruff (line-length 100, rules E/F/I/N/W), `__all__` in every `__init__.py`, structured `ToolResult` returns
- Security: never hardcode keys, shell commands go through `_guard_command()` in `nanobot/agent/tools/shell.py`, path traversal checks in filesystem tools
- Dev commands: `make test`, `make lint`, `make format`, `make typecheck`, `make check`

**2. Create `CLAUDE.md` at project root**

Claude Code reads this file. Same conventions as copilot-instructions plus:
- Explicit instruction to run `make lint && make typecheck` after edits
- Memory architecture: mem0-first store in `nanobot/agent/memory/store.py`, JSONL events in `nanobot/agent/memory/persistence.py`, hybrid retrieval in `nanobot/agent/memory/retrieval.py`
- Skill development: YAML frontmatter in `SKILL.md`, optional `tools.py`, reference `nanobot/skills/weather/` as template
- Warning: never modify `case/memory_eval_*.json` without re-running `make memory-eval`

**3. Create `AGENTS.md` at project root**

Generic agent instructions for Codex CLI and other agents. Core conventions shared with the above files.
- Note: the existing `nanobot/templates/AGENTS.md` is a user workspace template copied at `nanobot onboard` — completely different purpose, no naming conflict.

### Phase 2 — Developer Automation (Makefile)

LLM agents need simple, predictable commands to validate their work. A Makefile is universally understood by all agents.

**4. Create `Makefile`**

Targets:
- `install` — `pip install -e ".[dev]"`
- `install-all` — `pip install -e ".[dev,reranker,oauth]"` + `cd bridge && npm install`
- `test` — `python -m pytest tests/ -x -q`
- `test-verbose` — `python -m pytest tests/ -v`
- `test-cov` — `python -m pytest tests/ --cov=nanobot --cov-report=term-missing`
- `lint` — `ruff check nanobot/ tests/`
- `format` — `ruff format nanobot/ tests/ && ruff check --fix nanobot/ tests/`
- `typecheck` — `mypy nanobot/`
- `check` — `lint` + `typecheck` + `test` (full pre-push validation)
- `memory-eval` — `python scripts/memory_eval_ci.py --strict`
- `clean` — remove `__pycache__`, `.mypy_cache`, `.pytest_cache`, `*.egg-info`
- `pre-commit-install` — `pre-commit install`

### Phase 3 — Type Checking Enforcement

Agents produce significantly better code when a type checker catches mistakes immediately.

**5. Create `nanobot/py.typed`**

Empty PEP 561 marker file signaling the package ships inline type hints.

**6. Add `[tool.mypy]` config to `pyproject.toml`**

Gradual adoption strategy:
- `python_version = "3.10"`
- `strict = false` (tighten later)
- `warn_return_any = true`, `warn_unused_configs = true`
- `check_untyped_defs = true`
- `ignore_missing_imports = true` (third-party libs without stubs)
- Per-module strictness overrides for `nanobot.agent`, `nanobot.config`, `nanobot.errors` (these already have excellent type coverage)

**7. Add `mypy>=1.8` to dev dependencies**

In `[project.optional-dependencies]` `dev` list in `pyproject.toml`.

### Phase 4 — Pre-commit Hooks

Catches issues before commit. Agents that run `git commit` get immediate feedback.

**8. Create `.pre-commit-config.yaml`**

Hooks:
- `ruff` (lint + format) via `astral-sh/ruff-pre-commit`
- `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-json` via `pre-commit/pre-commit-hooks`
- `check-added-large-files` to prevent accidental binary commits

**9. Add `pre-commit>=3.6` to dev dependencies**

In `[project.optional-dependencies]` `dev` list in `pyproject.toml`.

### Phase 5 — Contributing Guide

A single reference for both human and AI contributors.

**10. Create `CONTRIBUTING.md`**

Sections:
1. **Quick Start** — clone, `make install`, `make check`
2. **Project Structure** — annotated directory tree with one-line module descriptions
3. **Development Workflow** — branch naming, commit message conventions, `make check` before push
4. **Coding Conventions** — `from __future__ import annotations`, type hints required on all new code, ruff rules, `ToolResult` pattern, `__all__` in `__init__.py`
5. **Testing** — how to run, how to add tests, `ScriptedProvider` pattern from `tests/test_agent_loop.py`, parametrize pattern
6. **Adding a New Tool** — extend `Tool` in `nanobot/agent/tools/base.py`, return `ToolResult`, register in `ToolRegistry` (`nanobot/agent/tools/registry.py`). Reference `ReadFileTool` in `nanobot/agent/tools/filesystem.py` as template.
7. **Adding a New Skill** — `SKILL.md` YAML frontmatter, optional `tools.py`. Reference `nanobot/skills/weather/` as template.
8. **Adding a New Channel** — extend `BaseChannel` in `nanobot/channels/base.py`. Reference existing channels.
9. **Memory System** — mem0 adapter, events.jsonl, profile.json, MEMORY.md snapshot, retrieval pipeline
10. **Security Rules** — shell safety model, path validation, no hardcoded keys

### Phase 6 — Module-Level Architecture Docs (docstrings only, zero logic changes)

Better docstrings help agents understand module boundaries without reading entire files.

**11. Enhance `nanobot/agent/memory/__init__.py`**

Add proper `__all__` export list covering: `MemoryStore`, `MemoryExtractor`, `CrossEncoderReranker`, and internal adapters.

**12. Improve module docstrings in 8 key files**

Add or expand module-level docstrings with architecture context:
- `nanobot/agent/memory/store.py` — mem0-first strategy, fallback to local, consolidation lifecycle
- `nanobot/agent/memory/retrieval.py` — hybrid retrieval (mem0 + local), re-ranker integration, scoring pipeline
- `nanobot/agent/memory/extractor.py` — entity/event extraction pipeline, LLM-based extraction
- `nanobot/agent/memory/persistence.py` — JSONL events + profile.json format, append-only design
- `nanobot/agent/tools/registry.py` — tool discovery, parallel vs sequential execution strategy
- `nanobot/agent/tools/shell.py` — security model: deny patterns, allowlist mode, workspace restriction
- `nanobot/agent/loop.py` — Plan-Act-Observe-Reflect cycle, iteration limits, streaming, planning gate
- `nanobot/agent/context.py` — token budgeting, 3-phase compression (truncate → drop → summarize)

**13. Create `nanobot/skills/__init__.py`**

Currently missing. Add with docstring explaining the skill plugin system: YAML frontmatter metadata, optional tools.py for custom Tool subclasses, skill discovery via `SkillsLoader`.

---

**Relevant files**

| Action | Path | What to do |
|--------|------|------------|
| CREATE | `.github/copilot-instructions.md` | Copilot agent instructions |
| CREATE | `CLAUDE.md` | Claude Code agent instructions |
| CREATE | `AGENTS.md` | Generic agent instructions (Codex CLI, etc.) |
| CREATE | `Makefile` | Developer automation task runner |
| CREATE | `nanobot/py.typed` | PEP 561 type marker (empty file) |
| CREATE | `.pre-commit-config.yaml` | Pre-commit hook configuration |
| CREATE | `CONTRIBUTING.md` | Contributor guide |
| CREATE | `nanobot/skills/__init__.py` | Missing package init with plugin docs |
| MODIFY | `pyproject.toml` | Add `[tool.mypy]` config + `mypy`, `pre-commit` to dev deps |
| MODIFY | `nanobot/agent/memory/__init__.py` | Add `MemoryExtractor` + `MemoryPersistence` to `__all__` |
| MODIFY | 8 module files | Improve module docstrings (no logic changes) |

---

**Verification**

1. `make install` — succeeds with no errors
2. `make lint` — ruff check passes cleanly
3. `make typecheck` — mypy runs without configuration errors (some existing type warnings expected)
4. `make test` — all existing tests still pass
5. `make check` — full pipeline (lint + typecheck + test) succeeds
6. `pre-commit run --all-files` — all hooks pass
7. VS Code: open project → Copilot chat → verify copilot-instructions appear in context
8. Claude Code: run `claude` in repo root → verify CLAUDE.md is loaded

---

**Decisions**

- **CI/CD expansion excluded** from this pass — can be added later.
- **Gradual mypy adoption**: start permissive (`strict = false`), tighten per-module over time.
- **Accept ~70% content duplication** across `copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md` — agents read one file, not cross-references. Duplication is a feature here.
- **Phase 6 is docstrings only** — zero risk of logic regressions, pure documentation improvement.
- **Root `AGENTS.md` vs template `AGENTS.md`**: Completely different purpose. Root is for coding agents working on nanobot source. Template is for user workspace agents using nanobot.
