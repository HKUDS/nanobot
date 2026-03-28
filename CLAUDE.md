# CLAUDE.md — Nanobot Agent Framework

> Instructions for Claude Code and other Claude-based development agents.

## Who Develops This

This project is developed **entirely through LLM-driven development** (Claude Code). There is no human writing code directly. This makes architectural discipline non-negotiable — there is no code review safety net, no team convention enforcement, no PR process catching drift. Claude must be its own architect, reviewer, and quality gate.

## Project Overview

Nanobot is a personal AI agent framework.

## After Every Edit

```bash
make lint && make typecheck
```

Run this after every code change. Fix any errors before proceeding.

Before committing:

```bash
make check    # lint + typecheck + import-check + prompt-check + doc-check + test + integration (full validation)
```

Before committing, also review documentation: check that READMEs, CHANGELOG, ADRs, docstrings, and inline comments are accurate and up to date with the changes being committed.

## Commit Message Convention

**All commits MUST use [Conventional Commits](https://www.conventionalcommits.org/) format.**
`python-semantic-release` reads these to determine version bumps automatically.
Also enforced by `.claude/hooks/validate-commit.sh`.

```
<type>(<scope>): <description>

<optional body>
```

| Type | Version bump | When to use |
|------|-------------|-------------|
| `feat` | **MINOR** (1.0.0 -> 1.1.0) | New feature or capability |
| `fix` | **PATCH** (1.0.0 -> 1.0.1) | Bug fix |
| `perf` | **PATCH** | Performance improvement |
| `feat!` or `BREAKING CHANGE:` | **MAJOR** (1.0.0 -> 2.0.0) | Breaking change |
| `refactor` | no bump | Code restructuring (no behavior change) |
| `docs` | no bump | Documentation only |
| `test` | no bump | Adding or fixing tests |
| `chore` | no bump | Maintenance (deps, CI, config) |
| `ci` | no bump | CI/CD changes |

**Rules:**
- Scope is optional but encouraged: `feat(memory):`, `fix(coordination):`
- The `!` suffix denotes a breaking change: `feat!: remove legacy API`
- Never manually edit `__version__` or `pyproject.toml` version — `python-semantic-release` manages both
- Version bumps happen automatically on merge to main via GitHub Actions

## Python Conventions

- **Target**: Python 3.10+ (use `|` union syntax, not `Union[X, Y]`)
- **Every module** starts with `from __future__ import annotations`
- **Type hints** on all function signatures and class attributes
- **Pydantic** for config/schema validation (`nanobot/config/schema.py`)
- **Dataclasses** with `slots=True` for value objects (e.g. `ToolResult`)
- **`Protocol`** for interface types to avoid circular imports (e.g. `_ChatProvider` in `compression.py`)
- **Async/await** for all I/O — never block the event loop

## Architecture Layers

The codebase is organized into layers with strict dependency direction. Outer layers
may import from inner layers, never the reverse.

**Entry points** — `cli/`, `cron/`, `heartbeat/`. Parse input, wire subsystems, invoke
the agent. May import from any layer.

**Orchestration** — `agent/`. Owns the tool-use loop (`TurnRunner`), guardrail checkpoints
(`GuardrailChain`), message processing, and the composition root (`agent_factory.py`).
Behavioral fixes go through extension points (guardrails, context contributors, prompt
templates) — the loop itself rarely changes. Orchestrates subsystems — never owns
domain logic for tools, memory, or coordination.

**Domain subsystems** — each owns a single bounded context:
- `coordination/` — Multi-agent delegation, missions, scratchpad
- `memory/` — Persistent memory with SQLite storage, hybrid retrieval, knowledge graph
  (internal subdirs: `write/`, `read/`, `ranking/`, `persistence/`, `graph/`)
- `tools/` — Tool infrastructure (`base`, `registry`, `executor`) and domain
  implementations (`builtin/`). Infrastructure and implementations are separated.
- `context/` — Prompt assembly, token compression, skill discovery

**Cross-cutting** — `observability/` (Langfuse tracing, correlation IDs, metrics).
Consumed by all domain packages but owns no domain logic.

**Infrastructure** — `bus/` (async message queue), `channels/` (chat platform adapters),
`providers/` (LLM abstraction), `config/` (Pydantic models), `session/` (conversation state).
These are foundational — they must never import from orchestration or domain subsystems.

For detailed module ownership and file-level documentation, see `docs/architecture.md`.

## Architectural Constraints

Strict import direction, single composition root, dependency inversion, single message
processing pipeline. Enforced by `scripts/check_imports.py` and `scripts/check_structure.py`.
Full rules in `.claude/rules/architecture-constraints.md`.

## Change Protocol

Placement gate, size gate, package growth limits, refactoring rules, post-change and
post-deletion checklists. Full procedures in `.claude/rules/change-protocol.md`.

## Prohibited Patterns

Package structure, code quality, wiring, and growth violations. All are bugs — fix
immediately if detected. Full list in `.claude/rules/prohibited-patterns.md`.

## Coding Standards

- **Linter**: ruff (line-length 100, select E/F/I/N/W, ignore E501)
- **Formatter**: `ruff format`
- **`__all__`** in every `__init__.py` — list all public exports explicitly
- **Tool results**: return `ToolResult.ok(output)` or `ToolResult.fail(error)`, never bare strings
- **Error handling**: use typed exceptions from `nanobot/errors.py` — never bare `Exception`
- **`except Exception`**: narrow to specific types when possible; mark intentionally-broad catches with `# crash-barrier: <reason>`
- **Imports**: stdlib -> third-party -> local (enforced by ruff `I` rules)

## Testing

- **Framework**: pytest + pytest-asyncio (auto mode)
- **Mock LLM**: `ScriptedProvider` in `tests/test_agent_loop.py` for deterministic tests
- **Coverage**: `@pytest.mark.parametrize` for variant coverage

### Test Tiers

| Tier | Command | What runs | When to run |
|------|---------|-----------|-------------|
| **Unit** | `make test` | `tests/` excluding `tests/integration/` — fast, deterministic, no external deps | After every edit |
| **Integration** | `make test-integration` | `tests/integration/` — real subsystems wired together, LLM tests fail without API key | Before push |
| **Full** | `make check` | Unit + integration + lint + typecheck + boundary checks | Before commit |

`make test` must stay fast (< 30s). Integration tests may do real I/O and are excluded
from the fast loop. `make check` runs both tiers — never commit without it passing.

### Test Data Requirements

Every test file that tests tool-related code MUST include:
- At least one test with mixed-type dict arguments (str, int, None, list, dict)
- At least one test with the EXACT data format production code produces
- Boundary condition tests (empty strings, max-length strings, edge values)

Do NOT use only simple `{"cmd": "ls"}` fixtures. Real tool arguments look like:
`{"command": "obsidian search query=\"DS10540\"", "working_dir": None, "timeout": 60}`

## Memory System Architecture

The memory subsystem (`nanobot/memory/`) uses a **unified SQLite storage** strategy:

1. **Write path**: Events extracted by `MemoryExtractor` (LLM-based) -> stored in `UnifiedMemoryDB` (SQLite + FTS5 + sqlite-vec)
2. **Read path**: Vector search (sqlite-vec) + full-text search (FTS5) -> RRF fusion -> cross-encoder re-ranking via ONNX Runtime (`reranker.py`, `onnx_reranker.py`)
3. **Persistence**: `UnifiedMemoryDB` manages all storage in a single SQLite database (events, profile, embeddings, knowledge graph)
4. **Consolidation**: Periodic pass merges events, updates profile, compacts snapshots

**Note**: `case/memory_eval_cases.json` is used by the advisory trend benchmark (`make memory-eval`). Behavioral correctness is enforced by contract tests in `tests/contract/` and LLM round-trip tests in `tests/test_memory_roundtrip.py`.

## Adding a New Tool

1. Create a class extending `Tool` in `nanobot/tools/base.py`
2. Define `name`, `description`, `parameters` (JSON Schema dict)
3. Implement `async def execute(self, **kwargs) -> ToolResult`
4. Return `ToolResult.ok(output)` or `ToolResult.fail(error, error_type="...")`
5. Register via `nanobot/tools/setup.py`
6. The new file goes in `nanobot/tools/builtin/` — never at the `tools/` level
7. **Caching**: Tools default to `cacheable = False` (full content always reaches the agent).
   Set `cacheable = True` only on data-retrieval tools (`read_file`, `exec`, `web_fetch`,
   `list_dir`) where a summary is acceptable and re-retrieval via `cache_get_slice` is
   available. Tools that return content the agent must see in full (instructions, skill
   content, messages) must keep the default `cacheable = False`.
8. Reference: `ReadFileTool` in `nanobot/tools/builtin/filesystem.py`

## Adding a New Skill

1. Create `nanobot/skills/your-skill/SKILL.md` with YAML frontmatter:
   ```yaml
   ---
   name: your-skill
   description: What it does
   ---
   ```
2. Auto-discovered by `SkillsLoader` (`nanobot/context/skills.py`)
3. Template: `nanobot/skills/weather/`
4. **Tool mapping**: Skills written for Claude Code are automatically transformed
   at load time — Claude Code tool names (Bash, Read, Write, etc.) are rewritten to
   nanobot equivalents and a tool-instruction preamble is prepended. No skill-side
   changes needed. See `docs/superpowers/specs/2026-03-25-skill-tool-mapping-design.md`.

## Security Rules

- **Never** hardcode API keys — config lives in `~/.nanobot/config.json` (0600 perms)
- **Shell commands**: `_guard_command()` in `nanobot/tools/builtin/shell.py` enforces deny patterns + optional allowlist mode
- **Filesystem**: path traversal protection in filesystem tools — validate against workspace root
- **Network**: WhatsApp bridge binds 127.0.0.1 only

## Dev Commands

```bash
make install        # Install dev dependencies
make install-all    # Install with optional extras (reranker, oauth) + npm bridge
make test           # Fast unit tests only (excludes integration)
make test-verbose   # Unit tests with verbose output
make test-cov       # Unit tests with coverage report (85% gate)
make test-integration # Integration tests (LLM tests fail without API key)
make lint           # Ruff lint + format check
make format         # Auto-format with ruff
make typecheck      # mypy type checker
make check          # Full validation: lint + typecheck + import-check + structure-check + prompt-check + doc-check + test + integration
make ci             # CI pipeline: lint + typecheck + import-check + structure-check + prompt-check + doc-check + test-cov + integration
make pre-push       # CI + merge-readiness check (run before pushing PRs)
make import-check   # Check module boundary violations
make structure-check # Check structural rules (file size, crash-barriers, __all__, catch-all filenames)
make prompt-check   # Check prompt manifest consistency
make doc-check      # Check docs/architecture.md references are still valid
make phase-todo-check # Check for TODOs referencing completed phases
make memory-eval    # Advisory memory retrieval trend (non-gating)
make live-eval      # Run live agent evaluation
make clean          # Remove __pycache__, .mypy_cache, etc.
make worktree-clean # Prune stale git worktrees and list active ones
make pre-commit-install  # Install pre-commit hooks
```

## Git Worktree Protocol

Use worktrees to isolate experimental or parallel work from the main checkout.
Full protocol (create, work, finish, prune, rules) in `.claude/rules/git-workflow.md`.

## Architecture References

- Architecture decisions: `docs/adr/` (ADR-001, ADR-003 through ADR-011)
- Module ownership and import rules: `docs/architecture.md`
- Memory subsystem: `docs/memory-system-reference.md`
- Deployment: `docs/deployment.md`

## Known Gotchas

- **`MemorySubsystemError` (formerly `MemoryError`)**: `nanobot/errors.py` previously defined `MemoryError` which shadowed Python's built-in `MemoryError`. It was renamed to `MemorySubsystemError` (LAN-57). Never reintroduce a class named `MemoryError` in this codebase.
