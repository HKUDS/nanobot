# Nanobot Architecture

> Living document. Updated as the codebase evolves.
> Last updated: 2026-03-27.

## Overview

Nanobot is a modular, asynchronous Python framework for building tool-augmented
AI agents and coordinated multi-agent systems.

The system runs as a single-process async runtime organized as a modular
monolith with clearly defined subsystem boundaries for agent orchestration,
tool execution, memory management, LLM provider abstraction, and
multi-channel messaging.

```
┌──────────────────────────────────────────────────────────────┐
│                     CLI / Gateway                            │
│                  nanobot/cli/commands.py                      │
└────────────┬─────────────────┬───────────────────────────────┘
             │                 │
     ┌───────▼───────┐  ┌─────▼──────┐  ┌───────────────┐
     │ ChannelManager │  │ AgentLoop  │  │  CronService  │
     │  (channels/)   │  │ (agent/)   │  │   (cron/)     │
     └───────┬───────┘  └─────┬──────┘  └───────────────┘
             │                │
             │         ┌──────┴────────────────────────────────┐
             │         │          │          │        │         │
             │    Tools     Coordination  Memory  Context  Observability
             │   (tools/)  (coordination/) (memory/) (context/) (observability/)
             │
             └──► MessageBus (bus/) ◄── 6 Channel adapters
```

## Top-Level Package Map

| Package | Concern | Key Classes |
|---------|---------|-------------|
| `agent/` | Orchestration engine (tool-use loop, guardrails) | `AgentLoop`, `TurnRunner`, `GuardrailChain`, `MessageProcessor` |
| `coordination/` | Multi-agent delegation and missions | `Coordinator`, `DelegationDispatcher`, `MissionManager` |
| `memory/` | Persistent memory with hybrid retrieval | `MemoryStore`, `UnifiedMemoryDB`, `KnowledgeGraph` |
| `tools/` | Tool infrastructure + domain implementations | `Tool`, `ToolRegistry`, `ToolExecutor`, `CapabilityRegistry` |
| `context/` | Prompt assembly and skill discovery | `ContextBuilder`, `SkillsLoader`, `PromptLoader` |
| `observability/` | Instrumentation and tracing | `init_langfuse()`, `TraceContext`, `bind_trace()` |
| `bus/` | Async message bus | `MessageBus`, `InboundMessage`, `OutboundMessage` |
| `channels/` | Chat platform adapters | `ChannelManager`, `BaseChannel` |
| `providers/` | LLM provider abstraction | `LLMProvider`, `LiteLLMProvider` |
| `config/` | Pydantic config models + loader | `Config`, `load_config()` |
| `session/` | Conversation session management | `SessionManager`, `Session` |
| `cron/` | Scheduled task service | `CronService`, `CronJob` |
| `eval/` | Memory retrieval benchmarks | `EvalRunner` |

## Dependency Rules

### Import DAG

```
errors.py, utils/, metrics.py  ← imported by all
config/                        ← imported by agent/, channels/, cli/, cron/
bus/events.py                  ← imported by agent/, channels/
providers/base.py              ← imported by agent/ (via Protocol)
session/                       ← imported by agent/
observability/                 ← imported by agent/, coordination/, memory/, tools/
context/                       ← imported by agent/, coordination/, memory/, tools/
tools/base.py                  ← imported by tools/builtin/*, context/skills
memory/                        ← imported by agent/, context/
coordination/                  ← imported by agent/, tools/
agent/                         ← imported only by cli/, cron/, heartbeat/
channels/                      ← imported only by cli/, channels/manager
cli/                           ← top-level entry point, imports everything
```

### Forbidden Imports (enforced by `scripts/check_imports.py`)

**All imports (runtime + TYPE_CHECKING):**

| From | Must not import |
|------|-----------------|
| `channels/*` | `agent/`, `tools/`, `memory/`, `coordination/` |
| `providers/*` | `agent/`, `channels/` |
| `config/*` | `agent/`, `channels/`, `providers/` |
| `bus/*` | `agent/`, `channels/`, `providers/` |
| `tools/*` | `channels/` |
| `memory/*` | `channels/`, `tools/` |
| `agent/*` | `channels/`, `cli/` |
| `coordination/*` | `channels/`, `cli/` |
| `context/*` | `channels/`, `cli/` |
| `observability/*` | `channels/`, `cli/` |

**Runtime-only imports (TYPE_CHECKING allowed):**

| From | Must not runtime-import | Reason |
|------|------------------------|--------|
| `coordination/*` | `tools.builtin` | No cross-package instantiation |
| `tools/*` | `coordination` | No cross-package instantiation |
| `agent/*` | `tools.builtin`, `coordination` | Use composition root (`agent_factory.py`) |
| `context/*` | `memory`, `tools.builtin` | Dependencies injected from factory |

Files in COMPOSITION_ROOTS (`agent_factory.py`, `tools/setup.py`) are exempt from
runtime-only rules — they construct and wire subsystems by design.

### Approved Exceptions

| Exception | Location | Reason |
|-----------|----------|--------|
| `config/schema.py` → `providers.registry` | Deferred import | Config resolves model-to-key mappings |
| `tools/builtin/mission.py` → `coordination.mission` | Data object | MissionStatus enum |
| `coordination/delegation.py` → `tools.builtin.delegate` | Data object | DelegationResult dataclass |

### Tool Lifecycle Hooks

The `Tool` base class (`tools/base.py`) provides lifecycle hooks so orchestration
can interact with tools without importing concrete types:

| Hook | Purpose | Default |
|------|---------|---------|
| `set_context(channel, chat_id, message_id, **kwargs)` | Per-turn routing context | No-op |
| `on_turn_start()` | Reset per-turn state | No-op |
| `on_session_change(**kwargs)` | Session-scoped dependencies (e.g. scratchpad) | No-op |
| `sent_in_turn` (property) | Whether tool sent output this turn | `False` |

Orchestration calls hooks on all tools via `ToolExecutor.all_tools()` — no isinstance
checks, no concrete type imports.

## Data Flow

### Inbound Message Processing

```
Channel.start() → bus.publish_inbound(InboundMessage)
  → AgentLoop.run() consumes from bus
    → ContextBuilder.build() assembles prompt
    → LLMProvider.chat() calls model
    → TurnRunner executes tool-use loop (tool calls + guardrail checkpoints)
    → Loop continues until final answer, guardrail recovery, or max iterations
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
  → EventIngester.append_events() → UnifiedMemoryDB (SQLite)
  → ConsolidationPipeline.consolidate() → update profile + snapshot
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
- [ADR-010: Lightweight Memory Dependencies](adr/ADR-010-lightweight-memory-deps.md)
- [ADR-011: Agent Cognitive Core Redesign](adr/ADR-011-agent-cognitive-redesign.md)

## Observability

- **Correlation IDs**: `request_id`, `session_id`, `agent_id` via `TraceContext` (contextvars)
- **Structured logs**: `bind_trace()` prefills log events with correlation IDs
- **Langfuse tracing** (`observability/langfuse.py`): OTEL-based integration via Langfuse v4
  - `trace_request()` — per-request root span
  - `tool_span()` — wraps each tool execution (in `tools/registry.py`)
  - `span()` — wraps context assembly, verification, coordination, delegation
  - `score_current_trace()` — attaches verification confidence scores
  - litellm auto-instrumented via `"otel"` callback
- **Lifecycle**: `init_langfuse()` at CLI startup, `shutdown_langfuse()` in all `finally` blocks

## Storage Layer

- **`memory/unified_db.py`** — Single SQLite database (`memory.db`) with FTS5 + sqlite-vec
- **`memory/embedder.py`** — `Embedder` protocol with `OpenAIEmbedder` and `LocalEmbedder`
- **`memory/migration.py`** — One-time file-to-SQLite migration
- **Knowledge graph** — entities and edges in SQLite tables; BFS via recursive CTE

## Memory Subsystem Internal Structure

```
memory/
├── store.py                  # Facade composing all subsystems
├── unified_db.py             # SQLite backend
├── embedder.py               # Embedding protocol + implementations
├── event.py                  # MemoryEvent model
├── write/                    # Ingestion pipeline
│   ├── extractor.py          # LLM + heuristic extraction
│   ├── ingester.py           # Event write path
│   └── conflicts.py          # Conflict detection
├── read/                     # Retrieval pipeline
│   ├── retriever.py          # Vector + FTS retrieval
│   ├── retrieval_planner.py  # Query planning
│   └── context_assembler.py  # Context assembly for prompts
├── ranking/                  # Reranking
│   ├── reranker.py           # Protocol + composite
│   └── onnx_reranker.py      # ONNX cross-encoder
├── persistence/              # Profile and snapshots
│   ├── profile_io.py         # Profile CRUD + caching
│   ├── snapshot.py           # MEMORY.md rebuild
│   └── profile_correction.py # Conflict resolution
└── graph/                    # Knowledge graph + ontology
    ├── graph.py              # SQLite-backed graph
    ├── entity_classifier.py  # Entity type classification
    ├── entity_linker.py      # Entity linking
    ├── ontology_types.py     # Type definitions
    └── ontology_rules.py     # Validation rules
```

## Enforcement Scripts

Architecture rules are enforced programmatically in pre-commit hooks and CI.

| Script | What it enforces | Runs in |
|--------|-----------------|---------|
| `scripts/check_imports.py` | Import direction rules + dependency inversion (RUNTIME_RULES) | Pre-commit + CI |
| `scripts/check_structure.py` | File size (500 LOC), package growth (15 files), `__init__.py` exports (12), crash-barriers, `__all__`, catch-all filenames, future annotations | Pre-commit + CI |
| `scripts/check_prompt_manifest.py` | Prompt file consistency | Pre-commit + CI |

`check_structure.py` uses a baseline file (`scripts/.structure-baseline`) to track
pre-existing violations. New violations block commits; existing ones are printed as
"tracked" but don't cause failure. As violations are fixed, entries are removed from
the baseline.
