# AGENTS.md — Nanobot Development Agent Instructions

> Instructions for AI coding agents (Codex CLI, and other LLM-based development tools).
> For GitHub Copilot, see `.github/copilot-instructions.md`.
> For Claude Code, see `CLAUDE.md`.

## Project Overview

Nanobot is an ultra-lightweight personal AI agent framework (~4,000 lines of core code).
Architecture: async bus-based message routing, provider-agnostic LLM integration, plugin
skill system. Single-process Python design.

## Validation Commands

Run after every code change:

```bash
make lint && make typecheck    # Fast feedback
make check                     # Full: lint + typecheck + import-check + prompt-check + test
make pre-push                  # CI + merge-readiness check (run before pushing PRs)
```

## Python Conventions

- Python 3.10+ — use `X | Y` union syntax, not `Union[X, Y]`
- Every module starts with `from __future__ import annotations`
- Type hints on all function signatures and class attributes
- Pydantic for config validation (`nanobot/config/schema.py`)
- Dataclasses with `slots=True` for value objects
- `Protocol` for interfaces to avoid circular imports
- Async/await for all I/O — never block the event loop

## Project Structure

```
nanobot/
├── agent/               # Core: loop.py, streaming.py, verifier.py, consolidation.py, context.py, coordinator.py, delegation.py, tool_executor.py, mission.py, tool_loop.py, observability.py, tracing.py, tools/, memory/
├── config/              # Pydantic config models + loader
├── channels/            # Chat platforms (base.py, retry.py, manager.py + 6 adapters)
├── providers/           # LLM providers (litellm → 100+ models, OpenAI Codex, custom)
├── bus/                 # Async message bus (channel↔agent decoupling)
├── session/             # Conversation session management
├── cron/                # Scheduled tasks    │  heartbeat/  # Periodic tasks
├── skills/              # Plugin skills (weather, github, summarize, ...)
├── cli/                 # Typer CLI commands
├── errors.py            # Structured error taxonomy
└── utils/               # Path helpers, sanitization
```

## Coding Standards

- Linter: ruff (line-length 100, rules E/F/I/N/W, E501 ignored)
- Formatter: `ruff format`
- `__all__` in every `__init__.py`
- Tool results: `ToolResult.ok(...)` / `ToolResult.fail(...)` — never bare strings
- Errors: typed exceptions from `nanobot/errors.py` — never bare `Exception`
- `except Exception`: narrow to specific types or annotate with `# crash-barrier: <reason>`
- Imports: stdlib → third-party → local (ruff `I` rules)

## Testing

- pytest + pytest-asyncio (auto mode — no manual asyncio marks needed)
- Mock LLM: `ScriptedProvider` pattern in `tests/test_agent_loop.py`
- `@pytest.mark.parametrize` for variant coverage
- `make test` (fast) / `make test-cov` (with coverage)

## Key Patterns

### Adding a Tool
1. Subclass `Tool` from `nanobot/agent/tools/base.py`
2. Define `name`, `description`, `parameters` (JSON Schema)
3. `async def execute(self, **kwargs) -> ToolResult`
4. Register in `AgentLoop.__init__`
5. Template: `ReadFileTool` in `nanobot/agent/tools/filesystem.py`

### Adding a Skill
1. Create `nanobot/skills/<name>/SKILL.md` (YAML frontmatter)
2. Optional `tools.py` for custom tools
3. Auto-discovered by `SkillsLoader`
4. Template: `nanobot/skills/weather/`

### Memory System
- mem0-first strategy with local JSONL fallback
- `MemoryStore` in `nanobot/agent/memory/store.py` is the primary API
- `events.jsonl` (append-only), `profile.json`, `MEMORY.md` (snapshot)
- `case/memory_eval_cases.json` is used by the advisory trend benchmark (`make memory-eval`); behavioral correctness is enforced by contract tests and LLM round-trip tests

## Security

- Never hardcode API keys
- Shell commands: `_guard_command()` deny patterns in `nanobot/agent/tools/shell.py`
- Filesystem: path traversal protection against workspace root
- Network: localhost-only bindings for internal services

## Architecture & Refactoring

- Architecture decisions: `docs/adr/` (ADR-001 through ADR-009)
- Module ownership and import rules: `docs/architecture.md`
- Refactoring guidelines: `docs/refactoring-principles.md`
- Reusable prompt files: `.github/prompts/`
- Key rule: **refactor by seams, not by folders** — extract sub-services before moving directories
- Key rule: **one PR, one change** — never combine unrelated refactors
- Always run `make lint && make typecheck` after every edit
