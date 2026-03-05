# Nanobot — Copilot Instructions

## Project Overview

Nanobot is an ultra-lightweight personal AI agent framework (~4,000 lines of core code).
Architecture: async bus-based message routing, provider-agnostic LLM integration, plugin
skill system. Single-process design — no microservices.

## Python Conventions

- **Target**: Python 3.10+ (use `|` union syntax, not `Union[X, Y]`)
- **Every module** starts with `from __future__ import annotations`
- **Type hints** on all function signatures and class attributes
- **Pydantic** for config/schema validation (`nanobot/config/schema.py`)
- **Dataclasses** with `slots=True` for value objects (e.g. `ToolResult`)
- **`Protocol`** for interface types to avoid circular imports (see `_ChatProvider` in `context.py`)

## Async Patterns

- All I/O is `async/await` — never use blocking calls in the agent loop
- Tool execution: readonly tools run in parallel (`asyncio.gather`), write tools run sequentially
- Streaming: LLM responses stream token-by-token via `async for` on provider responses

## Project Structure

```
nanobot/
├── agent/                # Core agent engine
│   ├── loop.py          # Plan-Act-Observe-Reflect main loop
│   ├── context.py       # Prompt assembly + token budgeting
│   ├── skills.py        # Skill discovery and loading (YAML frontmatter in SKILL.md)
│   ├── subagent.py      # Subagent spawning for parallel tasks
│   ├── metrics.py       # In-memory metrics with periodic flush
│   ├── memory/          # Memory subsystem (mem0-first with local fallback)
│   │   ├── store.py     # MemoryStore: primary public API
│   │   ├── retrieval.py # Keyword-based local retrieval (fallback)
│   │   ├── extractor.py # LLM + heuristic event extraction
│   │   ├── persistence.py # JSONL events + profile.json + MEMORY.md I/O
│   │   ├── mem0_adapter.py # mem0 vector store adapter
│   │   ├── reranker.py  # Cross-encoder re-ranking (optional)
│   │   ├── constants.py # Shared constants and tool schemas
│   │   └── types.py     # Shared dataclasses and enums (if present)
│   └── tools/           # Tool implementations
│       ├── base.py      # Tool ABC + ToolResult dataclass
│       ├── registry.py  # ToolRegistry: dynamic registration + execution
│       ├── shell.py     # ExecTool with deny/allow security patterns
│       ├── filesystem.py # ReadFile, WriteFile, EditFile, ListDir tools
│       ├── web.py       # WebFetch + WebSearch tools
│       ├── mcp.py       # Model Context Protocol integration
│       ├── feedback.py  # User feedback capture tool
│       ├── cron.py      # Scheduled task tool
│       ├── message.py   # Outbound message tool
│       └── spawn.py     # Subagent spawning tool
├── config/              # Configuration management
│   ├── schema.py        # Pydantic config models
│   └── loader.py        # Config file loading + migration
├── channels/            # Chat platform integrations
│   ├── base.py          # BaseChannel ABC
│   ├── manager.py       # ChannelManager (multi-channel orchestration)
│   └── telegram.py, discord.py, slack.py, whatsapp.py, ...
├── providers/           # LLM provider abstraction
│   ├── base.py          # LLMProvider ABC, LLMResponse, StreamChunk
│   ├── litellm_provider.py # Primary provider (supports 100+ models)
│   └── registry.py      # Provider discovery
├── bus/                 # Message bus (decoupled channel↔agent communication)
├── session/             # Conversation session management
├── cron/                # Cron service for scheduled tasks
├── heartbeat/           # Periodic task execution service
├── skills/              # Built-in skills (weather, github, summarize, ...)
├── cli/                 # Typer CLI commands
├── errors.py            # Structured error taxonomy (NanobotError hierarchy)
└── utils/               # Helpers (paths, sanitization)
```

## Coding Standards

- **Linter**: ruff (line-length 100, rules: E, F, I, N, W; E501 ignored)
- **Formatter**: `ruff format`
- **`__all__`** in every `__init__.py` — list all public exports
- **Tool results**: always return `ToolResult.ok(...)` or `ToolResult.fail(...)`, never bare strings
- **Error handling**: use typed exceptions from `nanobot/errors.py` (`ToolExecutionError`, `ProviderError`, `MemoryError`, etc.) — never bare `Exception`
- **Imports**: group as stdlib → third-party → local, enforced by ruff `I` rules

## Testing

- **Framework**: pytest + pytest-asyncio (auto mode — no need for `@pytest.mark.asyncio`)
- **Mock LLM**: use `ScriptedProvider` pattern from `tests/test_agent_loop.py` for deterministic tests
- **Parametrize**: use `@pytest.mark.parametrize` for variant coverage (see `tests/test_shell_safety.py` for 40+ cases)
- **Run**: `make test` (quick) or `make test-cov` (with coverage)
- **Memory eval**: `make memory-eval` runs deterministic retrieval benchmark against `case/memory_eval_cases.json`

## Security Rules

- **Never** hardcode API keys — use `~/.nanobot/config.json` with 0600 permissions
- **Shell commands** go through `_guard_command()` in `nanobot/agent/tools/shell.py` (deny patterns + optional allowlist)
- **Filesystem tools** validate paths against workspace boundaries (path traversal protection)
- **Network**: WhatsApp bridge binds to 127.0.0.1 only

## Dev Commands

```bash
make install        # Install dev dependencies
make test           # Run tests (fast, stop on first failure)
make lint           # Ruff lint check
make format         # Auto-format with ruff
make typecheck      # Run mypy type checker
make check          # Full validation: lint + typecheck + test
make memory-eval    # Run memory retrieval benchmark
make clean          # Remove build artifacts
```

## Adding a New Tool

1. Create a class extending `Tool` in `nanobot/agent/tools/base.py`
2. Define `name`, `description`, `parameters` (JSON Schema dict)
3. Implement `async def execute(self, **kwargs) -> ToolResult`
4. Return `ToolResult.ok(output)` on success, `ToolResult.fail(error)` on failure
5. Register in `AgentLoop.__init__` via `self.registry.register(YourTool(...))`
6. Reference: `ReadFileTool` in `nanobot/agent/tools/filesystem.py`

## Adding a New Skill

1. Create `nanobot/skills/your-skill/SKILL.md` with YAML frontmatter (name, description, tools)
2. Optionally add `tools.py` for custom `Tool` subclasses
3. Skills are auto-discovered by `SkillsLoader` in `nanobot/agent/skills.py`
4. Reference: `nanobot/skills/weather/` as minimal template
