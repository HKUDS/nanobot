# Nanobot — Copilot Instructions

## Project Overview

Nanobot is a personal AI agent framework.
Architecture: async bus-based message routing, provider-agnostic LLM integration, plugin
skill system, multi-agent coordination with knowledge-graph memory. Single-process design.

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
│   ├── streaming.py     # Streaming LLM call with think-tag stripping
│   ├── verifier.py      # Answer verification via LLM + grounding confidence
│   ├── consolidation.py # Memory consolidation orchestration + fallback archival
│   ├── context.py       # Prompt assembly + token budgeting
│   ├── coordinator.py   # Multi-agent coordinator with LLM-based intent routing
│   ├── registry.py      # AgentRegistry: maps role names to AgentRoleConfig
│   ├── scratchpad.py    # Session-scoped JSONL-backed artifact sharing (multi-agent)
│   ├── skills.py        # Skill discovery and loading (YAML frontmatter in SKILL.md)
│   ├── subagent.py      # Subagent spawning for parallel tasks
│   ├── metrics.py       # In-memory metrics with periodic flush
│   ├── memory/          # Memory subsystem (mem0-first with local fallback + knowledge graph)
│   │   ├── store.py     # MemoryStore: primary public API
│   │   ├── retrieval.py # Keyword-based local retrieval (fallback)
│   │   ├── extractor.py # LLM + heuristic event extraction
│   │   ├── persistence.py # JSONL events + profile.json + MEMORY.md I/O
│   │   ├── mem0_adapter.py # mem0 vector store adapter with health checks
│   │   ├── reranker.py  # Cross-encoder re-ranking (optional, needs sentence-transformers)
│   │   ├── constants.py # Shared constants and tool schemas
│   │   ├── graph.py     # Knowledge graph support (optional, needs neo4j)
│   │   ├── ontology.py  # Ontology management
│   │   ├── ontology_rules.py # Rule definitions for ontology
│   │   ├── ontology_types.py # Type definitions for ontology
│   │   ├── entity_classifier.py # Entity type classification
│   │   └── entity_linker.py    # Entity linking and resolution
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
│       ├── spawn.py     # Subagent spawning tool
│       ├── delegate.py  # Multi-agent peer-to-peer + parallel delegation
│       └── scratchpad.py # ScratchpadWriteTool for multi-agent artifacts
├── config/              # Configuration management
│   ├── schema.py        # Pydantic config models
│   └── loader.py        # Config file loading + migration
├── channels/            # Chat platform integrations
│   ├── base.py          # BaseChannel ABC
│   ├── retry.py         # Shared retry helpers, health tracking, reconnection loop
│   ├── manager.py       # ChannelManager (multi-channel orchestration)
│   ├── telegram.py      # Telegram (with group mention policy)
│   ├── discord.py       # Discord
│   ├── slack.py         # Slack
│   ├── whatsapp.py      # WhatsApp
│   ├── email.py         # Email
│   ├── dingtalk.py      # DingTalk
│   ├── feishu.py        # Feishu (Lark)
│   ├── mochat.py        # MoChat
│   └── qq.py            # Tencent QQ
├── providers/           # LLM provider abstraction
│   ├── base.py          # LLMProvider ABC, LLMResponse, StreamChunk
│   ├── litellm_provider.py  # Primary provider (100+ models via litellm)
│   ├── registry.py      # Provider discovery
│   ├── custom_provider.py   # Custom provider support
│   ├── openai_codex_provider.py # OpenAI Codex provider
│   └── transcription.py # Voice transcription provider
├── bus/                 # Message bus (decoupled channel↔agent communication)
├── session/             # Conversation session management
├── cron/                # Cron service for scheduled tasks
├── heartbeat/           # Periodic task execution service (reads HEARTBEAT.md)
├── skills/              # Built-in skills (weather, github, summarize, cron, tmux, ...)
├── templates/           # Starter templates (AGENTS.md, SOUL.md, USER.md, TOOLS.md, etc.)
├── cli/                 # Typer CLI (onboard, agent, gateway, memory, cron commands)
├── errors.py            # Structured error taxonomy (NanobotError hierarchy)
└── utils/               # Helpers (paths, sanitization)
```

## Error Hierarchy

```
NanobotError (base, has recoverable flag)
├── ToolExecutionError
│   ├── ToolNotFoundError
│   ├── ToolValidationError
│   ├── ToolTimeoutError
│   └── ToolPermissionError
├── ProviderError
│   ├── ProviderRateLimitError
│   └── ProviderAuthError
├── ContextOverflowError
└── MemoryError
    ├── MemoryRetrievalError
    └── MemoryConsolidationError
```

## Coding Standards

- **Linter**: ruff (line-length 100, target py311, rules: E, F, I, N, W; E501 ignored)
- **Formatter**: `ruff format`
- **`__all__`** in every `__init__.py` — list all public exports
- **Tool results**: always return `ToolResult.ok(...)` or `ToolResult.fail(...)`, never bare strings
- **Error handling**: use typed exceptions from `nanobot/errors.py` — never bare `Exception`
- **`except Exception`**: narrow to specific types when possible; mark intentionally-broad catches with `# crash-barrier: <reason>`
- **Imports**: group as stdlib → third-party → local, enforced by ruff `I` rules

## Testing

- **Framework**: pytest + pytest-asyncio (auto mode — no need for `@pytest.mark.asyncio`)
- **Mock LLM**: use `ScriptedProvider` pattern from `tests/test_agent_loop.py` for deterministic tests
- **Parametrize**: use `@pytest.mark.parametrize` for variant coverage (see `tests/test_shell_safety.py`)
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
make install-all    # Install with optional extras (reranker, oauth) + npm bridge
make test           # Run tests (fast, stop on first failure)
make test-verbose   # Run tests with verbose output
make test-cov       # Run tests with coverage report
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

## Architecture & Refactoring Rules

Architecture decisions are recorded in `docs/adr/`. Read them before making structural
changes. The module ownership map and import rules are in `docs/architecture.md`.

### Module Boundaries

Each top-level package has explicit import rules. Key forbidden imports:

- `channels/` must **never** import from `agent/loop`, `agent/tools/`, or `agent/memory/`
- `providers/` must **never** import from `agent/` or `channels/`
- `config/` must **never** import from `agent/`, `channels/`, or `providers/`
- `bus/` must **never** import from `agent/`, `channels/`, or `providers/`
- `agent/tools/` must **never** import from `channels/`

### Refactoring Principles

- **Refactor by seams, not by folders** — extract sub-services before moving directories
- **One PR, one change** — never combine unrelated refactors
- **Tests first** — add test coverage before extracting code
- **Preserve public API** — `__all__` exports must not change without an ADR
- **No speculative abstraction** — only abstract when there are ≥2 implementations
- **Verify after every change** — run `make lint && make typecheck` after every edit

Full guidelines: `docs/refactoring-principles.md`

### Key ADRs

- **ADR-001**: Modular monolith — refactor within current package structure, no microservices
- **ADR-002**: Agent loop ownership — extract `ToolExecutor` and `DelegationDispatcher`
- **ADR-003**: Memory architecture — typed `MemoryEvent`, mem0-first with local fallback
- **ADR-004**: Tool execution contract — keep `Tool` ABC + `ToolResult`, extract executor
- **ADR-005**: Observability — structured logging + correlation IDs before OpenTelemetry

### Prompt Files

Reusable prompt files are available in `.github/prompts/`:

- `safe-refactor.prompt.md` — incremental refactoring with safety checks
- `add-tests.prompt.md` — adding tests following project patterns
- `write-adr.prompt.md` — creating Architecture Decision Records
- `extract-module.prompt.md` — extracting classes/responsibilities into new files
- `code-review.prompt.md` — reviewing changes against project standards
