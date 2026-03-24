# Nanobot Architecture

> Living document. Updated as the codebase evolves.
> Last updated: 2026-03-18.

## Overview

Nanobot is a modular, asynchronous Python framework for building tool-augmented
AI agents and coordinated multi-agent systems.

The system runs as a single-process async runtime organized as a modular
monolith with clearly defined subsystem boundaries for agent orchestration,
tool execution, memory management, LLM provider abstraction, and
multi-channel messaging.

```
┌──────────────────────────────────────────────────────────┐
│                     CLI / Gateway                        │
│                  nanobot/cli/commands.py                  │
└────────────┬─────────────────┬───────────────────────────┘
             │                 │
     ┌───────▼───────┐  ┌─────▼──────┐  ┌───────────────┐
     │ ChannelManager │  │ AgentLoop  │  │  CronService  │
     │  (channels/)   │  │ (agent/)   │  │   (cron/)     │
     └───────┬───────┘  └─────┬──────┘  └───────────────┘
             │                │
             │         ┌──────┴──────────────────────┐
             │         │          │          │        │
             │    ToolRegistry  LLMProvider  Memory  Context
             │    (tools/)    (providers/) (memory/) (context.py)
             │
             └──► MessageBus (bus/) ◄── 6 Channel adapters
```

## Module Ownership

Each module has a clear responsibility, a public API, and boundaries it must not cross.

### `agent/` — Core Agent Engine

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `loop.py` | Orchestration: ingest → context → LLM → tools → state → continue/stop | `AgentLoop.run()`, `AgentLoop.run_tool_loop()` | `channels/`, `cli/` |
| `streaming.py` | Streaming LLM call with think-tag stripping | `StreamingLLMCaller.call()`, `strip_think()` | `channels/`, `cli/` |
| `verifier.py` | Answer verification via LLM + grounding confidence | `AnswerVerifier.verify()`, `.should_force_verification()` | `channels/`, `cli/` |
| `consolidation.py` | Memory consolidation orchestration + fallback archival | `ConsolidationOrchestrator.consolidate()`, `.fallback_archive_snapshot()` | `channels/`, `cli/` |
| `tool_executor.py` | Tool batching (parallel readonly / sequential write), timeouts, result shaping | `ToolExecutor.execute()` | `channels/`, `cli/` |
| `delegation.py` | Delegation routing, sub-loop dispatch, scratchpad I/O, cycle detection | `DelegationDispatcher` | `channels/`, `cli/` |
| `prompt_loader.py` | Load system prompts from `templates/prompts/` Markdown files | `prompts` (dict-like access) | `channels/`, `cli/` |
| `context.py` | Prompt assembly, token budgeting, context compression | `ContextBuilder.build()` | `channels/`, `cli/`, `bus/` |
| `coordinator.py` | Multi-agent intent routing, role classification | `Coordinator.classify()`, `Coordinator.route()` | `channels/`, `cli/` |
| `registry.py` | Agent role registry (name → config mapping) | `AgentRegistry.get()`, `.register()` | `channels/`, `cli/`, `providers/` |
| `scratchpad.py` | Session-scoped JSONL artifact sharing | `Scratchpad.write()`, `.read()` | `channels/`, `providers/` |
| `skills.py` | Skill discovery and YAML frontmatter loading | `SkillsLoader.load()` | `channels/`, `providers/` |
| `mission.py` | Background mission manager (async delegated tasks) | `MissionManager`, `Mission`, `MissionStatus` | `channels/`, `cli/` |
| `tool_loop.py` | Shared lightweight think→act→observe loop | `run_tool_loop()` | `channels/`, `cli/` |
| `observability.py` | Langfuse OTEL tracing: init, shutdown, spans, scoring | `init_langfuse()`, `shutdown()`, `trace_request()`, `tool_span()`, `span()`, `reset_trace_context()`, `tracing_health()`, `flush()` | `channels/`, `cli/` |
| `tracing.py` | Correlation IDs via contextvars, structured log binding | `TraceContext`, `bind_trace()` | `channels/`, `cli/` |
| `capability.py` | Unified capability registry (ADR-009): composes ToolRegistry, SkillsLoader, AgentRegistry with health tracking | `CapabilityRegistry` | `channels/`, `cli/` |
| `failure.py` | Failure classification and tool-call loop detection | `FailureClass`, `ToolCallTracker`, `_build_failure_prompt()` | `channels/`, `cli/` |

### `agent/memory/` — Memory Subsystem

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `store.py` | Primary memory API: retrieve, append, consolidate | `MemoryStore` | `channels/`, `cli/`, `tools/` |
| `event.py` | Typed `MemoryEvent` Pydantic model with validation | `MemoryEvent`, `KnowledgeTriple` | `channels/`, `cli/` |
| `retrieval.py` | Local keyword-based fallback retrieval | `local_retrieve()` | `providers/`, `channels/` |
| `extractor.py` | LLM + heuristic event extraction | `MemoryExtractor.extract()` | `channels/`, `tools/` |
| `persistence.py` | File I/O: events.jsonl, profile.json, MEMORY.md | `MemoryPersistence` | `providers/`, `channels/` |
| `mem0_adapter.py` | mem0 vector store adapter with health checks | `_Mem0Adapter` | `channels/`, `tools/` |
| `reranker.py` | Optional cross-encoder re-ranking | `rerank()` | `providers/`, `channels/` |
| `constants.py` | Shared constants and tool schemas for consolidation | `_SAVE_MEMORY_TOOL`, `_SAVE_EVENTS_TOOL` | `providers/`, `channels/` |
| `graph.py` | Knowledge graph support (optional, needs neo4j) | `KnowledgeGraph` | `providers/`, `channels/` |
| `ontology.py` | Ontology re-exports: classifier, linker, rules, types | `classify_entity_type()`, `link_entity()` | `providers/`, `channels/` |
| `entity_classifier.py` | Multi-signal entity type classification | `classify_entity_type()` | `providers/`, `channels/` |
| `entity_linker.py` | Entity linking and resolution | `link_entity()` | `providers/`, `channels/` |

### `agent/tools/` — Tool System

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `base.py` | Tool ABC + ToolResult dataclass | `Tool`, `ToolResult` | Everything except `errors.py` |
| `registry.py` | Tool registration, validation, execution | `ToolRegistry` | `channels/`, `providers/` |
| `shell.py` | Shell execution with deny/allow patterns | `ExecTool` | `channels/`, `memory/` |
| `filesystem.py` | File read/write/edit/list with path validation | `ReadFileTool`, `WriteFileTool`, etc. | `channels/`, `memory/`, `providers/` |
| `web.py` | Web fetch + search | `WebFetchTool`, `WebSearchTool` | `channels/`, `memory/` |
| `mcp.py` | Model Context Protocol integration | `MCPToolWrapper`, `connect_mcp_servers()` | `channels/`, `memory/` |
| `delegate.py` | Multi-agent delegation tools | `DelegateTool`, `DelegateParallelTool` | `channels/` |
| `result_cache.py` | Large result caching + LLM summarization | `ToolResultCache`, `CacheGetSliceTool` | `channels/`, `memory/` |
| `excel.py` | Spreadsheet read, query, describe, find | `ReadSpreadsheetTool`, `QueryDataTool`, etc. | `channels/`, `memory/` |
| `cron.py` | Scheduled task creation tool | `CronTool` | `channels/`, `memory/` |
| `email.py` | On-demand email checking via IMAP | `CheckEmailTool` | `channels/`, `memory/` |
| `feedback.py` | User feedback capture tool | `FeedbackTool` | `channels/`, `memory/` |
| `message.py` | Outbound message tool | `MessageTool` | `memory/` |
| `mission.py` | Background mission launch, status, list, cancel | `MissionStartTool`, `MissionStatusTool`, `MissionListTool`, `MissionCancelTool` | `channels/`, `memory/` |
| `scratchpad.py` | Scratchpad read/write tools | `ScratchpadWriteTool`, `ScratchpadReadTool` | `channels/`, `memory/` |

### `channels/` — Chat Platform Adapters

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `base.py` | Channel ABC + health tracking | `BaseChannel`, `ChannelHealth` | `agent/`, `providers/` |
| `retry.py` | Shared retry helpers and reconnection loop | `ChannelHealth`, `is_transient()`, `connection_loop()` | `agent/`, `providers/` |
| `manager.py` | Multi-channel orchestration, outbound dispatch, dead-letter queue | `ChannelManager` | `agent/loop`, `agent/tools/` |
| `telegram.py` | Telegram (group mention policy, media handling) | `TelegramChannel` | `agent/`, `providers/` |
| `discord.py` | Discord | `DiscordChannel` | `agent/`, `providers/` |
| `slack.py` | Slack | `SlackChannel` | `agent/`, `providers/` |
| `whatsapp.py` | WhatsApp (localhost bridge) | `WhatsAppChannel` | `agent/`, `providers/` |
| `email.py` | Email (IMAP/SMTP) | `EmailChannel` | `agent/`, `providers/` |
| `web.py` | Web/HTTP channel | `WebChannel` | `agent/`, `providers/` |

### `providers/` — LLM Provider Abstraction

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `base.py` | Provider ABC, response types | `LLMProvider`, `LLMResponse`, `StreamChunk`, `ToolCallRequest` | `agent/`, `channels/`, `tools/` |
| `litellm_provider.py` | litellm wrapper (100+ models) | `LiteLLMProvider` | `agent/`, `channels/` |
| `registry.py` | Provider discovery and metadata | `get_provider()`, `PROVIDERS` | `agent/`, `channels/` |
| `custom_provider.py` | Custom provider support | `CustomProvider` | `agent/`, `channels/` |
| `openai_codex_provider.py` | OpenAI Codex provider (optional, needs oauth) | `OpenAICodexProvider` | `agent/`, `channels/` |
| `transcription.py` | Voice transcription via Groq/Whisper | `TranscriptionProvider` | `agent/`, `channels/` |

### `config/` — Configuration

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `schema.py` | Pydantic config models | `Config`, all nested config classes | `agent/`, `channels/`, `providers/` |
| `loader.py` | Config file loading + migration | `load_config()`, `save_config()` | `agent/`, `channels/`, `providers/` |

### `bus/` — Message Bus

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `queue.py` | Async queue-based inbound/outbound routing | `MessageBus` | `agent/`, `channels/`, `providers/` |
| `events.py` | Message data classes | `InboundMessage`, `OutboundMessage` | `agent/`, `channels/`, `providers/` |

### `session/` — Session Management

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `manager.py` | Session lifecycle, JSONL persistence | `SessionManager`, `Session` | `agent/loop`, `channels/`, `providers/` |

### Other Modules

| Module | Owns | Notes |
|---|---|---|
| `cli/` | Typer CLI commands | Entry point; may import from any module |
| `cron/` | Scheduled task service | Imports from `agent/`, `config/` |
| `heartbeat/` | Periodic task execution | Reads HEARTBEAT.md, triggers agent |
| `skills/` | Built-in skill definitions | SKILL.md + optional tools.py per skill |
| `templates/` | Starter templates | Static assets, no imports |
| `errors.py` | Error taxonomy | Imported by all modules |
| `utils/` | Path helpers, sanitization | Imported by all modules |

## Agent Layer — New Module Boundaries (AgentLoop Decomposition)

- `turn_orchestrator.py` must **never** import from `channels/`, `bus/`, or `session/`
- `message_processor.py` must **never** import from `channels/`
- `bus_progress.py` must **never** import from `agent/loop`, `agent/turn_orchestrator`, or `agent/message_processor`
- `TurnState` is private to `turn_orchestrator.py` — never exported

## Data Flow

### Inbound Message Processing

```
Channel.start() → bus.publish_inbound(InboundMessage)
  → AgentLoop.run() consumes from bus
    → ContextBuilder.build() assembles prompt
    → LLMProvider.chat() calls model
    → ToolRegistry.execute() runs tools (if tool calls)
    → Loop continues until final answer or max iterations
  → bus.publish_outbound(OutboundMessage)
→ ChannelManager dispatches to correct channel
→ Channel.send() delivers response
```

### Multi-Agent Delegation

```
Parent AgentLoop → DelegateTool.execute()
  → Coordinator.classify() determines target role
  → Child AgentLoop.run_tool_loop() executes bounded sub-task
  → Result written to Scratchpad
  → Parent reads via read_scratchpad tool
```

### Memory Write Path

```
Session ends → AgentLoop triggers consolidation
  → MemoryExtractor.extract(messages) → list[MemoryEvent]
  → MemoryStore.append_events() → mem0 + events.jsonl
  → MemoryStore.consolidate() → update profile.json + MEMORY.md
```

## Key Design Decisions

See [docs/adr/](adr/) for Architecture Decision Records:

- [ADR-001: Modular Monolith Strategy](adr/ADR-001-modular-monolith.md)
- [ADR-002: Agent Loop Ownership](adr/ADR-002-agent-loop-ownership.md)
- [ADR-003: Memory Architecture](adr/ADR-003-memory-architecture.md)
- [ADR-004: Tool Execution Contract](adr/ADR-004-tool-execution-contract.md)
- [ADR-005: Observability Standard](adr/ADR-005-observability.md)
- [ADR-006: Configuration Strategy](adr/ADR-006-configuration-strategy.md)
- [ADR-007: Channel Adapter Model](adr/ADR-007-channel-adapter-model.md)
- [ADR-008: Prompt Management](adr/ADR-008-prompt-management.md)
- [ADR-009: Capability Registry](adr/ADR-009-capability-registry.md)

## Dependency Rules

```
errors.py, utils/     ← imported by all
config/               ← imported by agent/, channels/, cli/, cron/
bus/events.py         ← imported by agent/, channels/
providers/base.py     ← imported by agent/ (via Protocol)
session/              ← imported by agent/
agent/tools/base.py   ← imported by agent/tools/*, skills/
agent/memory/         ← imported by agent/loop, agent/context
agent/loop            ← imported only by cli/, cron/, heartbeat/
channels/             ← imported only by cli/, channels/manager
cli/                  ← top-level entry point, imports everything
```

### Forbidden Imports

These imports **must never exist** (enforced by `scripts/check_imports.py` in CI):

| From | Must not import |
|---|---|
| `channels/*` | `agent/loop`, `agent/tools/*`, `agent/memory/*` |
| `providers/*` | `agent/*`, `channels/*` |
| `config/*` | `agent/*`, `channels/*`, `providers/*` |
| `bus/*` | `agent/*`, `channels/*`, `providers/*` |
| `agent/tools/*` | `channels/*` |
| `agent/memory/*` | `channels/*`, `agent/tools/*` |

### Approved Exceptions

| Exception | Location | Reason |
|---|---|---|
| `config/schema.py` imports `providers.registry` | `NanobotConfig._match_provider()` and `.get_api_base()` | These are **deferred** (inside method bodies, not at module top-level), so the import only happens at call time. `config` must look up provider metadata to resolve model-to-key mappings. Extracting this lookup into a separate `config/provider_bridge.py` helper was considered but rejected as over-engineering for a single query; the deferred import is the approved pattern. |

## Failure Modes & Recovery

| Failure | Detection | Recovery | Owner |
|---------|-----------|----------|-------|
| LLM provider timeout | `asyncio.TimeoutError` in streaming | User message: "ran out of time" | `agent/loop.py` crash-barrier |
| LLM rate limit (429) | Exception text matching | User message: "rate-limited" | `_user_friendly_error()` |
| LLM auth failure | Exception text matching | User message: "configuration issue" | `_user_friendly_error()` |
| Context window exceeded | `context_length` in error | User message: "conversation too long" | `_user_friendly_error()` |
| Tool execution failure | `ToolResult.success == False` | REFLECT phase: alternative strategy prompt | `_run_agent_loop()` |
| Consecutive LLM errors (≥3) | Error counter in loop | Bail with "trouble reaching model" | `_run_agent_loop()` |
| Content filter triggered (≥2) | `finish_reason == "content_filter"` | Bail with "content filter" message | `_run_agent_loop()` |
| Memory consolidation failure | Exception in consolidation task | Log + skip; session not cleared | `_process_message()` |
| Channel reconnection | Health check failure | Exponential backoff reconnect loop | `channels/retry.py` |
| Dead-letter messages | Channel send failure | Queue in `ChannelManager.dead_letter` | `channels/manager.py` |

## Observability

- **Correlation IDs**: `request_id`, `session_id`, `agent_id` via `TraceContext` (contextvars)
- **Structured logs**: `bind_trace()` prefills log events with correlation IDs
- **Langfuse tracing** (`agent/observability.py`): OTEL-based integration via Langfuse v4
  - `trace_request()` — per-request root span with `session_id`, `user_id`, `tags` propagation
  - `tool_span()` — wraps each tool execution (in `tools/registry.py`)
  - `span()` — wraps context assembly, verification, coordination, delegation
  - `score_current_trace()` — attaches verification confidence scores
  - `update_current_span()` — enriches spans with model, channel, iteration metadata
  - litellm auto-instrumented via `"otel"` callback → GENERATION observations
  - `atexit.register(shutdown)` safety net + `auth_check()` on startup
  - Logging filters suppress benign warnings from litellm, langfuse, and OTEL SDK
  - `reset_trace_context()` — clears stale OTEL spans between bus-loop iterations
  - `flush()` — explicit trace export after each request (bus-loop path)
  - `tracing_health()` — diagnostic counters (`traces_created`, `traces_failed`, `last_trace_age_s`)
  - Crash-barrier log levels: WARNING (not DEBUG) for immediate visibility
- **Config**: `LangfuseConfig` — `enabled`, `public_key`, `secret_key`, `host`, `environment`, `sample_rate`, `debug`
- **Lifecycle**: `init_langfuse()` at CLI startup, `shutdown_langfuse()` in all `finally` blocks, `flush()` after each bus-loop request
- **Request audit**: Each completed request emits `request_complete` log with duration, tool count
- **JSON log sink**: Optional via `config.log.json_file` (loguru serialize mode, 10MB rotation)

## Memory Subsystem Module Boundaries (Post-Completion)

The following boundaries were established during the memory subsystem completion refactor:

- **`profile_io.py`** owns profile CRUD and caching (`ProfileStore`, `ProfileCache`). Never imports from `channels/`, `bus/`, `session/`, or `agent/loop`.
- **`profile_correction.py`** owns live user correction (`CorrectionOrchestrator`). Never imports from `channels/` or `bus/`.
- **`token_budget.py`** is pure logic (`TokenBudgetAllocator`, `SectionBudget`). Never imports from any `nanobot.agent.memory.*` or `nanobot.config.*` module.
- **`consolidation.py`** owns structured concurrency for consolidation (`ConsolidationOrchestrator`). Never imports from `channels/` or `agent/loop`. Must be used as an async context manager.
- **`ProfileCache`** is internal to `ProfileStore`; not exported from `nanobot/agent/memory/__init__.py`.

### Storage Layer (Post-Redesign)

- **`unified_db.py`** — Single SQLite database (`memory.db`) with FTS5 + sqlite-vec. All memory storage flows through this module. Replaces `persistence.py` + `mem0_adapter.py`.
- **`embedder.py`** — `Embedder` protocol with `OpenAIEmbedder` (production, 1536 dims) and `LocalEmbedder` (tests, ONNX, 384 dims). No hash-based fallback.
- **`migration.py`** — One-time file-to-SQLite migration. Runs on first access. Old files renamed to `.bak`.
- **Deleted modules:** `mem0_adapter.py` (874 lines), `retrieval.py` (285 lines), `persistence.py` (87 lines) — replaced by unified_db.py.
- **Knowledge graph** (`graph.py`, `entity_classifier.py`) — untouched, disabled by default. Phase 2 decision pending.
