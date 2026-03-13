# Nanobot Architecture

> Living document. Updated as the codebase evolves.
> Last updated: 2026-06-23.

## Overview

Nanobot is a single-process async Python agent framework (~4,000 lines of core code).

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
             └──► MessageBus (bus/) ◄── 9 Channel adapters
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
| `subagent.py` | Subagent spawning for parallel tasks | `spawn_subagent()` | `channels/` |
| _(removed)_ | Legacy `MetricsCollector` removed — observability now via Langfuse | — | — |

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

### `channels/` — Chat Platform Adapters

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `base.py` | Channel ABC + health tracking | `BaseChannel`, `ChannelHealth` | `agent/`, `providers/` |
| `retry.py` | Shared retry helpers and reconnection loop | `ChannelHealth`, `is_transient()`, `connection_loop()` | `agent/`, `providers/` |
| `manager.py` | Multi-channel orchestration, outbound dispatch, dead-letter queue | `ChannelManager` | `agent/loop`, `agent/tools/` |
| Platform files | Platform-specific connection + message handling | Each channel's `start()`, `stop()`, `send()` | `agent/`, `providers/` |

### `providers/` — LLM Provider Abstraction

| Sub-module | Owns | Public API | Must never import from |
|---|---|---|---|
| `base.py` | Provider ABC, response types | `LLMProvider`, `LLMResponse`, `StreamChunk`, `ToolCallRequest` | `agent/`, `channels/`, `tools/` |
| `litellm_provider.py` | litellm wrapper (100+ models) | `LiteLLMProvider` | `agent/`, `channels/` |
| `registry.py` | Provider discovery | `get_provider()` | `agent/`, `channels/` |

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
- **Metrics**: Observability counters captured via Langfuse (legacy `MetricsCollector` removed)
- **Request audit**: Each completed request emits `request_complete` log with duration, tool count
- **JSON log sink**: Optional via `config.log.json_file` (loguru serialize mode, 10MB rotation)
