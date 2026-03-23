# CLAUDE.md — Nanobot Agent Framework

> Instructions for Claude Code and other Claude-based development agents.

## Project Overview

Nanobot is an ultra-lightweight personal AI agent framework (~4,000 lines of core code).
Architecture: async bus-based message routing, provider-agnostic LLM integration, plugin
skill system. Single-process design — no microservices.

## After Every Edit

```bash
make lint && make typecheck
```

Run this after every code change. Fix any errors before proceeding.

Before committing:

```bash
make check    # lint + typecheck + import-check + prompt-check + test (full validation)
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

## Project Structure

```
nanobot/
├── agent/                # Core agent engine
│   ├── loop.py          # Plan-Act-Observe-Reflect main loop
│   ├── streaming.py     # Streaming LLM call with think-tag stripping
│   ├── verifier.py      # Answer verification via LLM + grounding confidence
│   ├── consolidation.py # Memory consolidation orchestration + fallback archival
│   ├── context.py       # Prompt assembly + token budgeting
│   ├── coordinator.py   # Multi-agent intent routing, role classification
│   ├── delegation.py    # Delegation routing, cycle detection, contract construction
│   ├── tool_executor.py # Tool batching (parallel readonly / sequential write)
│   ├── registry.py      # AgentRegistry: maps role names to AgentRoleConfig
│   ├── scratchpad.py    # Session-scoped JSONL artifact sharing (multi-agent)
│   ├── skills.py        # Skill discovery and loading
│   ├── mission.py       # Background mission manager (async delegated tasks)
│   ├── capability.py    # Unified capability registry (ADR-009): ToolRegistry + SkillsLoader + AgentRegistry
│   ├── failure.py       # Failure classification + tool-call loop detection (FailureClass, ToolCallTracker)
│   ├── tool_loop.py     # Shared lightweight think→act→observe loop
│   ├── observability.py # Langfuse OTEL tracing: init, shutdown, spans, scoring
│   ├── tracing.py       # Correlation IDs via contextvars, structured log binding
│   ├── memory/          # Memory subsystem
│   │   ├── store.py     # MemoryStore — primary public API (mem0-first with local fallback)
│   │   ├── event.py     # MemoryEvent Pydantic model + KnowledgeTriple
│   │   ├── retrieval.py # Local keyword retrieval (fallback when mem0 unavailable)
│   │   ├── extractor.py # LLM + heuristic event extraction
│   │   ├── persistence.py # JSONL events + profile.json + MEMORY.md file I/O
│   │   ├── mem0_adapter.py # mem0 vector store adapter with health checks
│   │   ├── reranker.py  # Cross-encoder re-ranking via ONNX Runtime
│   │   ├── constants.py # Shared constants and tool schemas
│   │   ├── graph.py     # Knowledge graph support via networkx
│   │   ├── ontology.py  # Ontology management (re-exports classifier, linker)
│   │   ├── entity_classifier.py # Entity type classification
│   │   └── entity_linker.py    # Entity linking and resolution
│   └── tools/           # Tool implementations
│       ├── base.py      # Tool ABC + ToolResult dataclass
│       ├── registry.py  # ToolRegistry — dynamic registration + parallel/sequential execution
│       ├── shell.py     # ExecTool — deny/allow pattern security model
│       ├── filesystem.py # File read/write/edit/list tools with path validation
│       ├── web.py       # WebFetch + WebSearch
│       ├── mcp.py       # Model Context Protocol
│       ├── delegate.py  # Multi-agent delegation tools
│       ├── result_cache.py # Large result caching + LLM summarization
│       ├── email.py     # On-demand email checking (CheckEmailTool)
│       ├── excel.py     # Spreadsheet read, query, describe, find tools
│       ├── cron.py      # Scheduled task tool
│       ├── feedback.py  # User feedback capture tool
│       ├── message.py   # Outbound message tool
│       ├── mission.py   # Background mission launch, status, list, cancel tools
│       └── scratchpad.py # Scratchpad read/write tools
├── config/              # Pydantic config models + loader with migration
├── channels/            # Chat platforms (Telegram, Discord, Slack, WhatsApp, ...)
│   ├── base.py          # BaseChannel ABC + ChannelHealth
│   ├── retry.py         # Shared retry helpers, health tracking, reconnection loop
│   ├── manager.py       # ChannelManager (multi-channel orchestration + dead-letter queue)
│   ├── telegram.py      # Telegram (group mention policy, media handling)
│   ├── discord.py       # Discord
│   ├── slack.py         # Slack
│   ├── whatsapp.py      # WhatsApp (localhost bridge)
│   ├── email.py         # Email (IMAP/SMTP)
│   └── web.py           # Web/HTTP channel
├── providers/           # LLM providers (litellm, OpenAI Codex, custom)
├── bus/                 # Async message bus (decoupled channel↔agent)
├── session/             # Conversation session management
├── cron/                # Scheduled task service
├── heartbeat/           # Periodic task execution (reads HEARTBEAT.md)
├── skills/              # Built-in skills (weather, github, summarize, cron, ...)
├── cli/                 # Typer CLI (onboard, agent, gateway, memory, cron commands)
├── errors.py            # Error taxonomy: NanobotError → ToolExecutionError, ProviderError, etc.
└── utils/               # Helpers (workspace paths, sanitization)
```

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
- **Commands**: `make test` (fast), `make test-cov` (with coverage report)

## Memory System Architecture

The memory subsystem (`nanobot/agent/memory/`) uses a **mem0-first strategy**:

1. **Write path**: Events extracted by `MemoryExtractor` (LLM-based) → stored in mem0 vector store + appended to `events.jsonl` (local backup)
2. **Read path**: Query mem0 first → fallback to local keyword search (`retrieval.py`) → cross-encoder re-ranking via ONNX Runtime (`reranker.py`, `onnx_reranker.py`)
3. **Persistence**: `MemoryPersistence` manages `events.jsonl` (append-only JSONL), `profile.json` (user profile state), `MEMORY.md` (active knowledge snapshot), `HISTORY.md` (event log)
4. **Consolidation**: Periodic pass merges events, updates profile, compacts MEMORY.md

**Note**: `case/memory_eval_cases.json` is used by the advisory trend benchmark (`make memory-eval`). Behavioral correctness is enforced by contract tests in `tests/contract/` and LLM round-trip tests in `tests/test_memory_roundtrip.py`.

## Adding a New Tool

1. Create a class extending `Tool` in `nanobot/agent/tools/base.py`
2. Define `name`, `description`, `parameters` (JSON Schema dict)
3. Implement `async def execute(self, **kwargs) -> ToolResult`
4. Return `ToolResult.ok(output)` or `ToolResult.fail(error, error_type="...")`
5. Register in `AgentLoop.__init__` via `self.registry.register(YourTool(...))`
6. Reference: `ReadFileTool` in `nanobot/agent/tools/filesystem.py`

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
3. Auto-discovered by `SkillsLoader` (`nanobot/agent/skills.py`)
4. Template: `nanobot/skills/weather/`

## Security Rules

- **Never** hardcode API keys — config lives in `~/.nanobot/config.json` (0600 perms)
- **Shell commands**: `_guard_command()` in `nanobot/agent/tools/shell.py` enforces deny patterns + optional allowlist mode
- **Filesystem**: path traversal protection in filesystem tools — validate against workspace root
- **Network**: WhatsApp bridge binds 127.0.0.1 only

## Dev Commands

```bash
make install        # Install dev dependencies
make install-all    # Install with optional extras (reranker, oauth) + npm bridge
make test           # Run tests (stop on first failure)
make test-verbose   # Run tests with verbose output
make test-cov       # Run tests with coverage report (85% gate)
make lint           # Ruff lint + format check
make format         # Auto-format with ruff
make typecheck      # mypy type checker
make check          # Full validation: lint + typecheck + import-check + prompt-check + test
make ci             # CI pipeline: lint + typecheck + import-check + prompt-check + test-cov
make pre-push       # CI + merge-readiness check (run before pushing PRs)
make import-check   # Check module boundary violations
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

## Architecture & Refactoring

- Architecture decisions: `docs/adr/` (ADR-001 through ADR-009)
- Module ownership and import rules: `docs/architecture.md`
- Refactoring guidelines: `docs/refactoring-principles.md`
- Reusable prompts: `.github/prompts/`

### Module Boundaries

- `channels/` must **never** import from `agent/loop`, `agent/tools/`, or `agent/memory/`
- `providers/` must **never** import from `agent/` or `channels/`
- `config/` must **never** import from `agent/`, `channels/`, or `providers/`
- `bus/` must **never** import from `agent/`, `channels/`, or `providers/`
- `agent/tools/` must **never** import from `channels/`

### Refactoring Rules

- Refactor by seams, not by folders
- One PR, one change
- Tests first, then extract
- Preserve `__all__` exports without an ADR
- No speculative abstraction
- Run `make lint && make typecheck` after every edit

## Known Gotchas

- **`MemorySubsystemError` (formerly `MemoryError`)**: `nanobot/errors.py` previously defined `MemoryError` which shadowed Python's built-in `MemoryError`. It was renamed to `MemorySubsystemError` (LAN-57). A backward-compat alias remains in `errors.py`. Never reintroduce a class named `MemoryError` in this codebase.
