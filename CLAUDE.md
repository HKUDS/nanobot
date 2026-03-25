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
make check    # lint + typecheck + import-check + prompt-check + test + integration (full validation)
```

Before committing, also review documentation: check that READMEs, CHANGELOG, ADRs, docstrings, and inline comments are accurate and up to date with the changes being committed.

## Python Conventions

- **Target**: Python 3.10+ (use `|` union syntax, not `Union[X, Y]`)
- **Every module** starts with `from __future__ import annotations`
- **Type hints** on all function signatures and class attributes
- **Pydantic** for config/schema validation (`nanobot/config/schema.py`)
- **Dataclasses** with `slots=True` for value objects (e.g. `ToolResult`)
- **`Protocol`** for interface types to avoid circular imports (see `_ChatProvider` in `context.py`)
- **Async/await** for all I/O — never block the event loop

## Architecture Layers

The codebase is organized into layers with strict dependency direction. Outer layers
may import from inner layers, never the reverse.

**Entry points** — `cli/`, `cron/`, `heartbeat/`. Parse input, wire subsystems, invoke
the agent. May import from any layer.

**Orchestration** — `agent/`. Owns the Plan-Act-Observe-Reflect loop, message processing,
and the composition root (`agent_factory.py`). Orchestrates subsystems — never owns
domain logic for tools, memory, or coordination.

**Domain subsystems** — each owns a single bounded context:
- `coordination/` — Multi-agent routing, delegation, missions, scratchpad
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

## Package Growth Limits — Early Warning Thresholds

These thresholds exist because the `agent/` monolith (25k LOC, 68 files, 23 `__init__.py`
exports) accumulated gradually across many sessions. No single session caused the problem;
every session thought it was adding "just one more file." These limits make the cost of
growth visible before it becomes a restructuring project.

**Hard limits — violations are bugs, fix immediately:**

| Metric | Threshold | Why |
|--------|-----------|-----|
| Top-level `.py` files in a package (excluding `__init__.py`) | **≤ 15** | More than 15 files signals the package contains multiple concerns. Extract a subpackage or a new top-level package. |
| `__init__.py` exports (`__all__` entries) | **≤ 12** | More than 12 exports means the package's public API spans too many concepts. It's doing too much. |
| Single file LOC | **≤ 500** | Files over 500 LOC are doing too much. Extract a class, split by concern, or decompose into submodules. Exceptions require a comment: `# size-exception: <reason>` |

**Advisory limits — trigger a design review before proceeding:**

| Metric | Threshold | Action |
|--------|-----------|--------|
| Package total LOC | **> 5,000** | Pause. Ask: does this package still own a single bounded context? If not, plan an extraction. |
| Single file LOC | **> 300** | Review: is this file doing more than one thing? Can it be split without artificial indirection? |
| Constructor parameters | **> 7** | The class is likely composing too many concerns. Consider a builder, a components dataclass, or decomposition. |

**How to check:**
```bash
# File count per package
find nanobot/<package> -maxdepth 1 -name '*.py' ! -name '__init__.py' | wc -l

# Package LOC
find nanobot/<package> -name '*.py' -exec cat {} + | wc -l

# __init__.py export count
grep -c ',' nanobot/<package>/__init__.py  # rough count from __all__
```

## Before Adding Any File — Placement Gate

**Every new `.py` file must pass this checklist before creation.** This gate exists because
the monolith formed through dozens of individually-reasonable file additions that each skipped
the question "does this belong here?"

1. **Name the owning package.** Which package's bounded context does this file serve?
   If the answer is "it serves multiple packages" — stop. Either:
   - It belongs in the package whose domain vocabulary it uses most, or
   - It's cross-cutting infrastructure that belongs in an existing infrastructure package, or
   - The design is wrong — restructure so the file serves one context.

2. **Check the file count.** Will this addition push the package over 15 top-level files?
   If yes, plan a restructuring first.

3. **Infrastructure vs. implementation?** Tool infrastructure (base classes, registries,
   executors) lives at `tools/` level. Tool *implementations* live in `tools/builtin/`.
   Never mix them. Apply the same principle to any package with infrastructure/implementation
   separation.

4. **Is it a catch-all?** Files named `utils.py`, `helpers.py`, `common.py`, or `misc.py`
   are prohibited. The logic belongs in the package that owns the concept.

5. **Will `__init__.py` need new exports?** If adding the export would exceed 12, the
   package is doing too much. Plan an extraction first.

## Before Growing a File — Size Gate

**Before adding logic to an existing file, check its size.** This gate exists because
`loop.py` grew to 1,025 LOC and `delegation.py` to 1,002 LOC across many sessions, each
adding "just one more method."

- **If the file is already > 400 LOC:** Before adding code, assess whether the file
  handles multiple concerns. If yes, extract the secondary concern *before* adding new code.
- **If your addition would push a file past 500 LOC:** Stop. Extract first, then add.
  The extraction is not optional and not a TODO — it happens now, in this session.
- **The only exception** is data-heavy files (schemas, constants, type definitions) that
  are large by nature. Mark these with `# size-exception: data definitions`.

## Coding Standards

- **Linter**: ruff (line-length 100, select E/F/I/N/W, ignore E501)
- **Formatter**: `ruff format`
- **`__all__`** in every `__init__.py` — list all public exports explicitly
- **Tool results**: return `ToolResult.ok(output)` or `ToolResult.fail(error)`, never bare strings
- **Error handling**: use typed exceptions from `nanobot/errors.py` — never bare `Exception`
- **`except Exception`**: narrow to specific types when possible; mark intentionally-broad catches with `# crash-barrier: <reason>`
- **Imports**: stdlib → third-party → local (enforced by ruff `I` rules)

## Testing

- **Framework**: pytest + pytest-asyncio (auto mode)
- **Mock LLM**: `ScriptedProvider` in `tests/test_agent_loop.py` for deterministic tests
- **Coverage**: `@pytest.mark.parametrize` for variant coverage

### Test Tiers

| Tier | Command | What runs | When to run |
|------|---------|-----------|-------------|
| **Unit** | `make test` | `tests/` excluding `tests/integration/` — fast, deterministic, no external deps | After every edit |
| **Integration** | `make test-integration` | `tests/integration/` — real subsystems wired together, LLM tests skip without API key | Before push |
| **Full** | `make check` | Unit + integration + lint + typecheck + boundary checks | Before commit |

`make test` must stay fast (< 30s). Integration tests may do real I/O and are excluded
from the fast loop. `make check` runs both tiers — never commit without it passing.

## Memory System Architecture

The memory subsystem (`nanobot/memory/`) uses a **unified SQLite storage** strategy:

1. **Write path**: Events extracted by `MemoryExtractor` (LLM-based) → stored in `UnifiedMemoryDB` (SQLite + FTS5 + sqlite-vec)
2. **Read path**: Vector search (sqlite-vec) + full-text search (FTS5) → RRF fusion → cross-encoder re-ranking via ONNX Runtime (`reranker.py`, `onnx_reranker.py`)
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
7. Reference: `ReadFileTool` in `nanobot/tools/builtin/filesystem.py`

## Adding a New Skill

1. Create `nanobot/skills/your-skill/SKILL.md` with YAML frontmatter:
   ```yaml
   ---
   name: your-skill
   description: What it does
   tools: [tool_name]  # optional custom tools
   ---
   ```
2. Optionally add `tools.py` with `Tool` subclasses
3. Auto-discovered by `SkillsLoader` (`nanobot/context/skills.py`)
4. Template: `nanobot/skills/weather/`

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
make test-integration # Integration tests (LLM tests skip without API key)
make lint           # Ruff lint + format check
make format         # Auto-format with ruff
make typecheck      # mypy type checker
make check          # Full validation: lint + typecheck + import-check + structure-check + prompt-check + test + integration
make ci             # CI pipeline: lint + typecheck + import-check + structure-check + prompt-check + test-cov + integration
make pre-push       # CI + merge-readiness check (run before pushing PRs)
make import-check   # Check module boundary violations
make structure-check # Check structural rules (file size, crash-barriers, __all__, catch-all filenames)
make prompt-check   # Check prompt manifest consistency
make memory-eval    # Advisory memory retrieval trend (non-gating)
make live-eval      # Run live agent evaluation
make clean          # Remove __pycache__, .mypy_cache, etc.
make worktree-clean # Prune stale git worktrees and list active ones
make pre-commit-install  # Install pre-commit hooks
```

## Git Worktree Protocol

Use worktrees to isolate experimental or parallel work from the main checkout.

### Lifecycle

1. **Create** a worktree for a branch:

   ```bash
   git worktree add ../nanobot-<branch-name> -b <branch-name>
   ```

2. **Work** inside the worktree directory — it has its own working tree but shares
   `.git` history, so all branches and commits are visible.

3. **Finish** — merge/PR from within the worktree or push the branch, then remove it:

   ```bash
   git worktree remove ../nanobot-<branch-name>
   # or, if the worktree has untracked files:
   git worktree remove --force ../nanobot-<branch-name>
   ```

4. **Prune** — clean up stale worktree metadata (e.g. after manually deleting the dir):

   ```bash
   make worktree-clean   # runs `git worktree prune` + lists remaining worktrees
   ```

### Rules

- Never leave abandoned worktrees — they block branch deletion and confuse `git status`.
- Run `make worktree-clean` periodically (or before releasing a branch) to prune stale entries.
- Do **not** run `make install` inside a worktree — dependencies are shared from the
  main checkout's virtual environment.
- Pre-commit hooks run normally inside worktrees; no special setup needed.

## Non-Negotiable Architectural Constraints

**These are hard constraints, not guidelines. Violations are bugs — fix them immediately.**

### Package Boundaries — Strict Import Direction

Each top-level package owns a single bounded context. Import direction is enforced
by `scripts/check_imports.py` in CI. These boundaries exist to prevent the architecture
from collapsing back into a monolith.

| Package | Owns | Must never import from |
|---------|------|----------------------|
| `agent/` | Orchestration engine (PAOR loop, message processing) | `channels/`, `cli/` |
| `coordination/` | Multi-agent routing, delegation, missions | `channels/`, `cli/` |
| `memory/` | Persistent memory, retrieval, knowledge graph | `channels/`, `tools/` |
| `tools/` | Tool infrastructure + domain implementations | `channels/` |
| `context/` | Prompt assembly, compression, skill discovery | `channels/`, `cli/` |
| `observability/` | Tracing, instrumentation, metrics | `channels/`, `cli/` |
| `channels/` | Chat platform adapters | `agent/`, `tools/`, `memory/`, `coordination/` |
| `providers/` | LLM provider abstraction | `agent/`, `channels/` |
| `config/` | Pydantic config models + loader | `agent/`, `channels/`, `providers/` |
| `bus/` | Async message bus | `agent/`, `channels/`, `providers/` |

**If you need to add an import that crosses a boundary, stop.** The design is wrong —
restructure the code so the dependency flows in the correct direction. Use `Protocol`
types or dependency injection to invert the dependency if needed.

### Package Responsibilities — Single Ownership

Every file belongs to exactly one package. Every concern has exactly one authoritative
location. If logic is expressed in two packages, one of them is wrong — deduplicate.

- **`agent/`** is only orchestration. If you're adding a tool, it goes in `tools/`. If you're
  adding delegation logic, it goes in `coordination/`. If you're adding memory logic, it
  goes in `memory/`. Agent orchestrates — it never owns domain logic for other concerns.
- **`tools/builtin/`** is for domain tool implementations. Tool infrastructure (base, registry,
  executor, capability) stays at `tools/` level. Never mix infrastructure with implementations.
- **`memory/`** has internal subdirectories (`write/`, `read/`, `ranking/`, `persistence/`,
  `graph/`) — respect them. Don't add flat files to `memory/` when they belong in a subdirectory.
- **`observability/`** is cross-cutting instrumentation. It is consumed by other packages but
  owns nothing about their domain logic.

### Composition Root — Single Wiring Point

`agent/agent_factory.py` (`build_agent()`) is the **only** place where subsystems are
constructed and wired together. This constraint exists because `AgentLoop.__init__` previously
grew into a service locator that constructed memory stores, tool registries, delegation
dispatchers, mission managers, and observability tracers — making it impossible to understand
the system's wiring without reading 1,000+ lines.

**Rules:**

1. `build_agent()` in `agent_factory.py` constructs all subsystems and returns an
   `_AgentComponents` dataclass.
2. `AgentLoop.__init__` is a **slim receiver** — it unpacks `_AgentComponents` and stores
   references. It must **never** call constructors, factory functions, or `setup_*` methods.
3. No other module may construct a subsystem that `build_agent()` is responsible for.
   If you find yourself writing `SomeSubsystem()` outside of `agent_factory.py`, you're
   in the wrong place.
4. If a new subsystem needs wiring, add it to `build_agent()` and `_AgentComponents`.
   Do not scatter construction across multiple modules.

**Detection test:** grep for class instantiation patterns (`SomeClass(`) in `loop.py`,
`turn_orchestrator.py`, `message_processor.py`. If any construct a subsystem (not a local
value object), it's a violation.

### Dependency Inversion — No Cross-Package Instantiation

**No package may import concrete classes from another package for the purpose of
instantiation.** This rule exists because `coordination/delegation.py` and
`coordination/mission.py` previously imported 8+ concrete tool classes from
`tools/builtin/` to construct tool registries — coupling coordination to specific
tool implementations.

**Allowed cross-package dependencies:**

| Pattern | Example | Why it's OK |
|---------|---------|-------------|
| Injected instances | Constructor receives `MemoryStore` | Dependency is provided, not constructed |
| Injected factories | Constructor receives `Callable[..., ToolRegistry]` | Defers construction to the caller |
| Protocol types | `TYPE_CHECKING: from nanobot.memory.store import MemoryStore` | Structural typing, no runtime coupling |
| Data objects | Pydantic models, dataclasses, enums, constants | Value types, not services |
| Base classes | `from nanobot.tools.base import Tool` for subclassing | Extension point, not instantiation |

**Forbidden:**

```python
# In coordination/delegation.py — WRONG
from nanobot.tools.builtin.filesystem import ReadFileTool
registry.register(ReadFileTool(workspace=self.workspace))  # cross-package instantiation

# CORRECT — receive a factory from the composition root
def __init__(self, ..., build_tools: Callable[..., ToolRegistry]):
    self._build_tools = build_tools
```

**Enforcement:** `scripts/check_imports.py` flags runtime imports from `tools/builtin/`
in `coordination/`, and runtime imports from `coordination/` in `tools/`. The script
skips imports inside `if TYPE_CHECKING:` blocks.

**Detection test:** grep for import lines from another package's concrete modules
(e.g., `from nanobot.tools.builtin.*` in non-tools code). If found outside
`agent_factory.py` or `tools/setup.py`, it's a violation.
value object), it's a violation.

### No Architectural Debt by Design

Do not introduce code with the intent to "fix it later." There is no later — the next
session starts with a blank context. Every change must be correctly placed, boundary-safe,
and tested before it is considered done.

- Never add a `# TODO: move this to the right package` comment. Move it now.
- Never add a backward-compatibility shim for internal imports. Update all callers.
- Never add a catch-all module (`utils.py`, `helpers.py`) at the package level. If
  shared logic is needed, place it in the package that owns the concept.

## Architecture References

- Architecture decisions: `docs/adr/` (ADR-001 through ADR-009)
- Module ownership and import rules: `docs/architecture.md`
- Refactoring guidelines: `docs/refactoring-principles.md`
- Architecture restructuring history: `docs/plans/2026-03-24-architecture-restructuring.md`
- Architecture review: `docs/architecture-review-2026-03.md`
- Reusable prompts: `.github/prompts/`

## Change Protocol

### Before implementing any change (including trivial ones)

**For every change — even a single new file or method:**
1. Name the owning package and why.
2. Confirm the file placement passes the Placement Gate (see above).
3. Confirm the file size stays within limits (see above).
4. Confirm no import boundary violations.

**For non-trivial changes (new features, refactors, multi-file changes), also:**
5. List files to create or modify.
6. Identify any risks to boundaries or coupling.
7. Do not start coding until placement is clear. If placement is ambiguous, resolve the
   design question first.

### Before any structural refactoring (extracting, promoting, moving packages)

This gate exists because the March 2026 restructuring introduced 4 critical issues
(duplicated methods, fragile wiring, re-export chains, Protocol surface area gaps) that
would have been caught by reviewing extraction boundaries against actual call paths.

**Before writing an extraction plan:**
1. **Trace call paths** that cross the proposed extraction boundary. For each call path,
   document: caller → callee, and what contract the caller depends on (return type,
   side effects, state mutations).
2. **Identify shared methods** — methods that both sides of the boundary will need after
   extraction. These must be placed once, in the package that owns the concept.
3. **Identify post-construction wiring** — patterns where subsystem A reaches into
   subsystem B's internals after construction. These must be surfaced and resolved
   (via dependency injection or Protocol interfaces) before extraction, not after.
4. **Check for re-export chains** — if module A re-exports from module B, and module B
   re-exports from module C, the chain will break during extraction. Flatten to direct
   imports first.
5. **Verify Protocol surface area** — if extraction requires a new Protocol interface,
   define it and verify that the concrete implementation satisfies it *before* moving files.
6. **Check mutable state propagation** — if the extracted component receives any
   field at construction time that the parent class can modify at runtime (model,
   temperature, role_name, etc.), verify the extracted component has a propagation
   path for runtime updates — not a stale copy. Add an integration test that
   modifies the field on the parent, runs a turn, and asserts the component used
   the updated value. See `tests/contract/test_role_propagation.py` for the pattern.

### After completing changes

Confirm:
- No logic leaked into the wrong package
- No new imports violating boundary rules (`make import-check`)
- Package growth limits still within thresholds
- Tests cover the new behavior
- `make lint && make typecheck` passes
- Documentation updated if public API changed

### Refactoring Rules

- Refactor by seams, not by folders
- One PR, one change
- Tests first, then extract
- Preserve `__all__` exports without an ADR
- No speculative abstraction
- Run `make lint && make typecheck` after every edit

## Prohibited Patterns

These are not suggestions — they are errors. Fix immediately if detected.

**Package structure violations:**
- Business logic in `agent/` that belongs in `coordination/`, `memory/`, or `tools/`
- Direct construction of subsystems in `AgentLoop.__init__` (use `agent_factory.py`)
- Import direction violations — outer packages importing from inner ones
- New flat files in `memory/` that should be in a subdirectory
- Tool implementations at `tools/` level instead of `tools/builtin/`
- Catch-all modules (`utils.py`, `helpers.py`, `common.py`) with mixed ownership
- A package exceeding 15 top-level `.py` files without planned extraction
- An `__init__.py` with more than 12 `__all__` exports

**Code quality violations:**
- Magic numbers outside of config schema or named constants
- `except Exception` without `# crash-barrier: <reason>` comment
- Circular imports resolved by `TYPE_CHECKING` guards that mask a real boundary violation
- Files exceeding 500 LOC without `# size-exception: <reason>`

**Wiring violations:**
- Subsystem construction outside `agent_factory.py` (grep for `SomeSubsystem(` in
  orchestration modules)
- Post-construction wiring that reaches into private attributes of another subsystem
- Re-export chains (A re-exports from B re-exports from C) — flatten to direct imports
- Concrete class imports across package boundaries where a Protocol should be used
- Extracted components caching mutable state that the parent class modifies at
  runtime (e.g., fields updated by role switching, configuration reloads, or
  per-turn overrides). If a field on `AgentLoop` can change after construction,
  every extracted component that reads that field must have a propagation path
  (per-call parameters, shared reference, or `TurnState` fields) — not a stale
  construction-time copy. See `tests/contract/test_role_propagation.py` for the
  pattern.

**Growth violations:**
- Adding a file to a package at its file-count limit without extracting first
- Adding code that pushes a file past 500 LOC without extracting first
- Adding an `__init__.py` export that pushes past 12 without extracting first

## Known Gotchas

- **`MemorySubsystemError` (formerly `MemoryError`)**: `nanobot/errors.py` previously defined `MemoryError` which shadowed Python's built-in `MemoryError`. It was renamed to `MemorySubsystemError` (LAN-57). Never reintroduce a class named `MemoryError` in this codebase.
