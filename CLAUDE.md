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
make check    # lint + typecheck + test (full validation)
```

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
│   ├── skills.py        # Skill discovery and loading
│   ├── subagent.py      # Subagent spawning
│   ├── metrics.py       # In-memory metrics
│   ├── memory/          # Memory subsystem
│   │   ├── store.py     # MemoryStore — primary public API (mem0-first with local fallback)
│   │   ├── retrieval.py # Local keyword retrieval (fallback when mem0 unavailable)
│   │   ├── extractor.py # LLM + heuristic event extraction
│   │   ├── persistence.py # JSONL events + profile.json + MEMORY.md file I/O
│   │   ├── mem0_adapter.py # mem0 vector store adapter with health checks
│   │   ├── reranker.py  # Optional cross-encoder re-ranking
│   │   └── constants.py # Shared constants and tool schemas
│   └── tools/           # Tool implementations
│       ├── base.py      # Tool ABC + ToolResult dataclass
│       ├── registry.py  # ToolRegistry — dynamic registration + parallel/sequential execution
│       ├── shell.py     # ExecTool — deny/allow pattern security model
│       ├── filesystem.py # File read/write/edit/list tools with path validation
│       ├── web.py       # WebFetch + WebSearch
│       ├── mcp.py       # Model Context Protocol
│       └── ...          # feedback, cron, message, spawn tools
├── config/              # Pydantic config models + loader with migration
├── channels/            # Chat platforms (Telegram, Discord, Slack, WhatsApp, ...)
│   ├── base.py          # BaseChannel ABC + ChannelHealth
│   ├── retry.py         # Shared retry helpers, health tracking, reconnection loop
│   ├── manager.py       # ChannelManager (multi-channel orchestration + dead-letter queue)
│   └── ...              # 9 platform adapters
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
2. **Read path**: Query mem0 first → fallback to local keyword search (`retrieval.py`) → optional cross-encoder re-ranking (`reranker.py`)
3. **Persistence**: `MemoryPersistence` manages `events.jsonl` (append-only JSONL), `profile.json` (user profile state), `MEMORY.md` (active knowledge snapshot), `HISTORY.md` (event log)
4. **Consolidation**: Periodic pass merges events, updates profile, compacts MEMORY.md

**Warning**: Never modify `case/memory_eval_cases.json` or `case/memory_eval_baseline.json` without re-running `make memory-eval` to verify metrics.

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
make test           # Run tests (stop on first failure)
make lint           # Ruff lint check
make format         # Auto-format with ruff
make typecheck      # mypy type checker
make check          # Full validation: lint + typecheck + test
make memory-eval    # Deterministic memory retrieval benchmark
make clean          # Remove __pycache__, .mypy_cache, etc.
```

## Architecture & Refactoring

- Architecture decisions: `docs/adr/` (ADR-001 through ADR-005)
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
