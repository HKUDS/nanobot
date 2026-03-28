# Architectural Review: Nanobot Project Structure

> Date: 2026-03-23
> Status: Completed — all 7 PRs merged — to be revisited after `loop.py` decomposition refactor

---

## Executive Summary

The **outer architecture is solid**. The module boundaries between `bus/`, `channels/`, `config/`, `providers/`, `session/`, and `agent/` are well-defined, enforced by static analysis (`scripts/check_imports.py`), and documented in ADRs. The import-check enforcement is genuinely good practice.

The problem is that **`agent/` is a monolith within a monolith**. It accounts for ~25,350 lines across 68 files, and its internal organization does not reflect clear architectural boundaries. The ADR-002 decomposition helped (extracting `TurnOrchestrator`, `MessageProcessor`, etc.), but it was a *code-level* decomposition, not an *architectural* one. Files were extracted from `loop.py` and left flat in the same directory. The result: `agent/` has become a catch-all namespace containing at least 6 distinct concerns with no structural separation.

---

## Current State: Quantitative Overview

### Project-Wide Structure

```
nanobot/
├── agent/       28 top-level .py files + memory/ + tools/  (~25,350 LOC total)
├── bus/          3 modules   (417 LOC)
├── channels/     9 modules   (2,612 LOC)
├── cli/          ~8 modules  (2,822 LOC)
├── config/       2 modules   (1,196 LOC)
├── cron/         2 modules   (450 LOC)
├── heartbeat/    1 module    (197 LOC)
├── providers/    5 modules   (1,180 LOC)
├── session/      1 module    (273 LOC)
├── web/          ~4 modules  (1,264 LOC)
├── utils/        1 module    (103 LOC)
├── errors.py                 (207 LOC)
└── metrics.py
```

### agent/ Top-Level Modules (8,974 LOC, 28 files)

| File | LOC | Purpose |
|------|-----|---------|
| loop.py | 1,025 | Main orchestrator: ingest -> context -> LLM -> tools -> state |
| delegation.py | 1,002 | Multi-agent routing, scratchpad I/O, cycle detection |
| turn_orchestrator.py | 847 | Turn-based PAOR state machine |
| context.py | 709 | Prompt assembly + token budgeting |
| message_processor.py | 679 | Message ingestion and processing pipeline |
| skills.py | 521 | Skill discovery and loading |
| mission.py | 483 | Background mission manager |
| observability.py | 477 | Langfuse OTEL tracing |
| capability.py | 360 | Unified capability registry (ADR-009) |
| coordinator.py | 357 | Multi-agent intent routing |
| verifier.py | 307 | Answer verification via LLM + confidence |
| failure.py | 236 | Failure classification + loop detection |
| tool_setup.py | 202 | Tool registration bootstrap |
| delegation_advisor.py | 184 | Delegation heuristics |
| streaming.py | 179 | Streaming LLM calls with think-tag stripping |
| tool_loop.py | 168 | Shared think->act->observe loop |
| scratchpad.py | 162 | Session-scoped artifact sharing |
| consolidation.py | 148 | Memory consolidation orchestration |
| tracing.py | 144 | Correlation ID context |
| tool_executor.py | 141 | Tool batching (parallel/sequential) |
| role_switching.py | 131 | Turn-scoped role management |
| prompt_loader.py | 100 | Load prompts from templates/ |
| bus_progress.py | 91 | Bus event handling |
| registry.py | 89 | Agent role registry |
| callbacks.py | 86 | Progress event types |
| __init__.py | 64 | Public API (23 exports from 15 modules) |
| reaction.py | 57 | Reaction classification |
| metrics.py | 25 | Metrics re-exports |

### agent/memory/ (11,505 LOC, 30 files)

| File | LOC | Purpose |
|------|-----|---------|
| retriever.py | 1,107 | High-level retrieval orchestrator |
| ingester.py | 895 | Event write path (classify, deduplicate, merge, store) |
| mem0_adapter.py | 874 | mem0 vector store adapter with health checks |
| profile_io.py | 756 | Profile CRUD + caching + versioning |
| conflicts.py | 640 | Conflict detection and resolution |
| graph.py | 608 | Knowledge graph (networkx) |
| context_assembler.py | 596 | Prompt rendering for memory context |
| entity_classifier.py | 590 | Entity type classification |
| extractor.py | 510 | LLM + heuristic event extraction |
| maintenance.py | 476 | Reindex, seed, health checks |
| ontology_rules.py | 430 | Relationship rules and validation |
| eval.py | 401 | Behavioral correctness evaluation |
| store.py | 393 | Facade (compose ingester, retriever, etc.) |
| retrieval_planner.py | 370 | Query decomposition for better recall |
| consolidation_pipeline.py | 309 | Consolidation orchestration |
| retrieval.py | 289 | Local BM25 fallback |
| ontology_types.py | 285 | Entity/Relationship type definitions |
| reranker.py | 262 | Reranker protocol + composite |
| profile_correction.py | 230 | Live user correction orchestrator |
| onnx_reranker.py | 214 | ONNX Runtime cross-encoder |
| helpers.py | 204 | Utility functions |
| rollout.py | 199 | Feature flags for gradual rollout |
| snapshot.py | 196 | MEMORY.md rebuilder |
| event.py | 126 | MemoryEvent Pydantic model + KnowledgeTriple |
| token_budget.py | 125 | Memory token estimation |
| __init__.py | 113 | Package exports |
| constants.py | 97 | Shared constants + tool schemas |
| persistence.py | 87 | Low-level file I/O (events.jsonl, profile.json) |
| ontology.py | 69 | Ontology re-exports |
| entity_linker.py | 54 | Entity linking and resolution |

### agent/tools/ (4,871 LOC, 17 files)

| File | LOC | Purpose |
|------|-----|---------|
| excel.py | 1,102 | Spreadsheet tools (pandas) |
| powerpoint.py | 670 | Presentation tools (python-pptx) |
| result_cache.py | 427 | Large result cache + LLM summarization |
| web.py | 398 | WebFetch + WebSearch |
| delegate.py | 279 | Multi-agent delegation tools |
| shell.py | 256 | Shell execution with deny/allow security |
| filesystem.py | 248 | File read/write/edit/list with path validation |
| registry.py | 247 | ToolRegistry (registration, lookup, batch execution) |
| mission.py | 229 | Background mission tools |
| feedback.py | 194 | User feedback capture |
| base.py | 173 | Tool ABC + ToolResult dataclass |
| cron.py | 137 | Scheduled task creation |
| message.py | 132 | Outbound messaging |
| mcp.py | 105 | Model Context Protocol |
| scratchpad.py | 73 | Scratchpad read/write |
| __init__.py | 9 | Package exports |

---

## Dependency Analysis

### Module Boundary Compliance

Enforced by `scripts/check_imports.py`:

```
channels/**/*.py  -> agent.loop, agent.tools, agent.memory    FORBIDDEN
providers/**/*.py -> agent.*, channels.*                       FORBIDDEN
config/**/*.py    -> agent.*, channels.*, providers.*          FORBIDDEN
bus/**/*.py       -> agent.*, channels.*, providers.*          FORBIDDEN
agent/tools/**    -> channels.*                                FORBIDDEN
agent/memory/**   -> channels.*, agent.tools.*                 FORBIDDEN
```

**Actual compliance:**

| Boundary | Status |
|----------|--------|
| Bus isolation | PASS — perfect |
| Config isolation | PASS — perfect |
| Session isolation | PASS — perfect |
| Cron isolation | PASS — perfect |
| Web isolation | PASS — perfect |
| Providers isolation | PASS |
| Channels isolation | MINOR VIOLATION — telegram.py imports GroqTranscriptionProvider from providers |
| Agent dependencies | PASS — correctly imports bus, config, session, providers, cron |
| CLI orchestration | PASS — correctly imports all modules as top-level orchestrator |

### Key Design Patterns Observed

1. **Protocol-based decoupling**: `context.py` defines `_ChatProvider` Protocol to avoid circular imports with providers
2. **TYPE_CHECKING guards**: `capability.py`, `heartbeat.py` use conditional imports for type hints only
3. **Composition over inheritance**: `CapabilityRegistry` composes ToolRegistry + SkillsLoader + AgentRegistry
4. **Dependency injection**: `AgentLoop` constructor receives major collaborators
5. **Lazy imports**: `loop.py` uses TYPE_CHECKING for Coordinator, ChannelsConfig

### Internal agent/ Dependency Graph (Simplified)

```
loop.py (main orchestrator)
  +-- streaming.py (LLM calls)
  +-- context.py (prompts)
  +-- coordinator.py (role classification)
  +-- delegation.py (multi-agent)
  +-- turn_orchestrator.py (PAOR loop)
  +-- message_processor.py (per-message pipeline)
  +-- verifier.py (quality gates)
  +-- failure.py (error handling)
  +-- consolidation.py (memory mgmt)
  +-- mission.py (background tasks)
  +-- capability.py (unified registry)
  +-- observability.py (tracing)
  +-- memory/ (MemoryStore)
  +-- tools/ (ToolRegistry)

delegation.py
  +-- coordinator.py
  +-- tool_loop.py
  +-- tools/delegate.py, tools/filesystem.py, tools/shell.py, tools/web.py
  +-- tools/registry.py

context.py
  +-- memory/ (MemoryStore)
  +-- skills.py (skill loader)
  +-- tools/feedback.py
  +-- observability.py
```

---

## Architectural Problems Identified

### Problem 1: `agent/` conflates multiple bounded contexts (ARCHITECTURE)

Distinct concerns sharing the `agent/` namespace:

| Concern | Files | LOC |
|---------|-------|-----|
| Orchestration | loop, turn_orchestrator, message_processor, streaming, bus_progress | ~2,821 |
| Multi-agent coordination | coordinator, delegation, delegation_advisor, registry, role_switching, scratchpad | ~1,925 |
| Memory | memory/* | ~11,505 |
| Tool infrastructure + implementations | tools/*, tool_executor, tool_setup, tool_loop, capability | ~5,741 |
| Observability | observability, tracing, metrics, callbacks | ~732 |
| Background tasks | mission, consolidation | ~631 |
| Prompt/context | context, prompt_loader, skills | ~1,330 |
| Verification/failure | verifier, failure, reaction | ~600 |

These have different rates of change, different testing strategies, different domain vocabularies, and different reasons to exist.

### Problem 2: `memory/` is a subsystem pretending to be a subpackage (ARCHITECTURE)

At 11,505 lines across 30 modules, the memory subsystem is larger than the rest of `agent/` combined. It contains:

- A full knowledge graph engine (graph.py, entity_classifier.py, entity_linker.py, ontology_*.py — ~2,000 LOC)
- A retrieval engine with query planning and reranking (~2,000 LOC)
- A write pipeline with conflict detection (~2,200 LOC)
- A persistence layer with profile management (~1,260 LOC)
- An evaluation framework (eval.py, rollout.py — ~600 LOC)
- A consolidation pipeline (~540 LOC)

The import boundary enforcement already treats it as independent. The directory structure hasn't caught up.

### Problem 3: Flat file sprawl in `agent/` (ORGANIZATION)

28 Python files at the top level with no grouping beyond memory/ and tools/. No discoverability. Inconsistent naming — some describe *what* they do (streaming.py), others *when* they act (consolidation.py), others *concepts* (mission.py, scratchpad.py).

### Problem 4: Tool implementations mixed with tool infrastructure (ORGANIZATION)

`tools/` contains both infrastructure (base.py, registry.py, result_cache.py) and domain tools (excel.py at 1,102 LOC, powerpoint.py at 670 LOC). The office tools alone are 1,772 LOC with heavy third-party deps (pandas, python-pptx).

### Problem 5: `__init__.py` re-exports everything (ARCHITECTURE SMELL)

`agent/__init__.py` re-exports 23 symbols from 15 different modules. When a package's public API spans that many concerns, the package is doing too much.

### Problem 6: Observability is scattered (ORGANIZATION)

observability.py (477 LOC), tracing.py (144 LOC), metrics.py (25 LOC), callbacks.py (86 LOC) sit scattered among unrelated files. nanobot/metrics.py exists at the top level separately.

### Problem 7: `loop.py` is a God Object (ARCHITECTURE)

At 1,025 lines, `AgentLoop.__init__` constructs and wires together everything: memory, tools, delegation, missions, skills, cron, observability, verification, consolidation. It's a service locator disguised as a constructor. **NOTE: This is being addressed by the ongoing loop.py decomposition refactor.**

### Problem 8: No dependency inversion at package boundaries (ARCHITECTURE) — RESOLVED

Concrete tool imports removed from coordination/delegation.py and coordination/mission.py.
Tool construction moved to build_delegation_tools() factory in tools/setup.py, injected
via composition root. Runtime import rules added to check_imports.py and enforced in
pre-commit hooks.

### Problem 9: The consolidation split is awkward (ARCHITECTURE) — RESOLVED

`consolidation.py` (orchestrator, 148 LOC) lives in `agent/`, while `consolidation_pipeline.py` (actual logic, 309 LOC) lives in `memory/`. After the restructuring, this split is actually correct: agent/ owns scheduling/concurrency (when and how to consolidate), memory/ owns domain logic (what consolidation does). The orchestrator calls `memory.consolidate()` — clean separation.

### Problem 10: `capability.py` has an identity crisis (ARCHITECTURE) — RESOLVED

Placement in tools/ is correct — 75% of its API is tool-centric. Cross-package
AgentRegistry instantiation removed; now injected from composition root.
TYPE_CHECKING guard added for coordination.registry import.

### Problem 11: `memory/` internal architecture is flat (ARCHITECTURE)

30 files with tangled internal dependencies. `ingester.py` (895 LOC) does classification, deduplication, merging, mem0 writes, and local writes. `retriever.py` (1,107 LOC) orchestrates mem0 queries, BM25 fallback, reranking, and filtering. Individual modules are doing too much internally.

### Problem 12: No clear composition root (ARCHITECTURE)

The system is wired together across multiple places: cli/gateway.py, cli/agent.py, AgentLoop.__init__, tool_setup.py. There's no single place where you can see "these are the components and this is how they connect."

---

## Proposed Directory Structure

### Principle

Group by **bounded context** (distinct domain responsibility with its own vocabulary), not by code-extraction history. Each package should have a narrow, coherent public API.

### Layout

```
nanobot/
├── agent/                    # NARROWED: only the orchestration engine
│   ├── __init__.py           # Exports: AgentLoop, MessageProcessor, TurnResult
│   ├── loop.py               # Main orchestrator
│   ├── turn_orchestrator.py  # PAOR state machine
│   ├── message_processor.py  # Per-message pipeline
│   ├── streaming.py          # Streaming LLM caller
│   ├── context.py            # Prompt assembly + token budgeting
│   ├── prompt_loader.py      # Prompt/skill instruction loading
│   ├── verifier.py           # Answer verification
│   ├── failure.py            # Failure classification + loop detection
│   └── callbacks.py          # Progress event types
│
├── coordination/             # NEW: multi-agent routing and delegation
│   ├── __init__.py
│   ├── coordinator.py        # Intent classification
│   ├── delegation.py         # Delegation routing + contracts
│   ├── delegation_advisor.py # Delegation heuristics
│   ├── registry.py           # Agent role registry
│   ├── role_switching.py     # Turn-scoped role management
│   ├── scratchpad.py         # Multi-agent artifact sharing
│   └── mission.py            # Background mission manager
│
├── memory/                   # PROMOTED: top-level bounded context
│   ├── __init__.py           # Exports: MemoryStore
│   ├── store.py              # Facade
│   ├── event.py              # MemoryEvent model
│   ├── write/                # Write path
│   │   ├── extractor.py
│   │   ├── ingester.py
│   │   └── conflicts.py
│   ├── read/                 # Read path
│   │   ├── retriever.py
│   │   ├── retrieval.py      # BM25 fallback
│   │   ├── retrieval_planner.py
│   │   └── context_assembler.py
│   ├── ranking/              # Reranking
│   │   ├── reranker.py
│   │   └── onnx_reranker.py
│   ├── persistence/          # Storage I/O
│   │   ├── persistence.py
│   │   ├── profile_io.py
│   │   ├── snapshot.py
│   │   └── profile_correction.py
│   ├── graph/                # Knowledge graph + ontology
│   │   ├── graph.py
│   │   ├── entity_classifier.py
│   │   ├── entity_linker.py
│   │   ├── ontology.py
│   │   ├── ontology_types.py
│   │   └── ontology_rules.py
│   ├── consolidation_pipeline.py
│   ├── maintenance.py
│   ├── mem0_adapter.py
│   ├── eval.py
│   ├── rollout.py
│   ├── constants.py
│   ├── helpers.py
│   └── token_budget.py
│
├── tools/                    # PROMOTED: top-level
│   ├── __init__.py           # Exports: Tool, ToolResult, ToolRegistry
│   ├── base.py               # Tool ABC + ToolResult
│   ├── registry.py           # ToolRegistry
│   ├── executor.py           # ToolExecutor (was agent/tool_executor.py)
│   ├── tool_loop.py          # Shared think->act->observe loop
│   ├── setup.py              # Tool bootstrap (was agent/tool_setup.py)
│   ├── result_cache.py       # Large result cache
│   ├── capability.py         # CapabilityRegistry (was agent/capability.py)
│   ├── builtin/              # Domain tool implementations
│   │   ├── filesystem.py
│   │   ├── shell.py
│   │   ├── web.py
│   │   ├── delegate.py
│   │   ├── excel.py
│   │   ├── powerpoint.py
│   │   ├── email.py
│   │   ├── cron.py
│   │   ├── feedback.py
│   │   ├── message.py
│   │   ├── mission.py
│   │   ├── scratchpad.py
│   │   └── mcp.py
│   └── skills/               # Moved from agent/
│       └── (skill discovery + loading)
│
├── observability/            # NEW: cross-cutting instrumentation
│   ├── __init__.py
│   ├── langfuse.py           # Was agent/observability.py
│   ├── tracing.py            # Correlation IDs
│   ├── metrics.py            # Unified metrics
│   └── bus_progress.py       # Bus progress adapter
│
├── bus/                      # UNCHANGED
├── channels/                 # UNCHANGED
├── config/                   # UNCHANGED
├── providers/                # UNCHANGED
├── session/                  # UNCHANGED
├── cron/                     # UNCHANGED
├── heartbeat/                # UNCHANGED
├── cli/                      # UNCHANGED
├── web/                      # UNCHANGED
├── utils/                    # UNCHANGED
└── errors.py                 # UNCHANGED
```

---

## Priority Assessment

### Structural changes (directory moves)

| Priority | Change | Impact |
|----------|--------|--------|
| HIGH | Promote `memory/` to top-level | 46% of agent/ by LOC, already has independent boundary rules |
| HIGH | Promote `tools/` to top-level, separate `builtin/` | Real architectural seam between infrastructure and implementations |
| HIGH | Extract `coordination/` | Delegation alone is 1,002 LOC; multi-agent coordination is growing |
| MEDIUM | Extract `observability/` | 4 files across 2 levels, ~730 LOC. Small effort, big discoverability win |
| MEDIUM | Add `read/`, `write/`, `graph/` subdirectories inside `memory/` | 30 files need internal structure |
| LOW | Consolidate top-level `metrics.py` with `agent/metrics.py` into `observability/` | Removes duplication |
| LOW | Resolve `consolidation.py` / `consolidation_pipeline.py` split | Tightly coupled but split across levels |

### Architectural changes (design fixes)

| Priority | Change | Impact |
|----------|--------|--------|
| **1** | Extract composition root / factory from `AgentLoop.__init__` | **IN PROGRESS** — loop.py decomposition refactor |
| **2** | Define Protocol interfaces at new package boundaries | Makes directory moves into real architectural boundaries |
| **3** | Decompose `memory/` internals (ingester, retriever) | Individual modules doing too much |
| **4** | Resolve `CapabilityRegistry` identity — dissolve or make it the composition root | Cross-cutting facade without a clear home |

---

## What NOT to Do

- **Don't reorganize channels/, bus/, config/, providers/, or session/.** They're clean and stable.
- **Don't refactor memory internals before promoting it.** Promote first, restructure internally in a follow-up.
- **Don't do this all in one PR.** Each extraction should be its own PR with updated import-check rules and ADR amendment.
- **Don't start structural moves until the loop.py decomposition is complete.** The outcome of that refactor will reshape what the right directory structure looks like.

---

## Key Insight

The directory restructuring is **necessary but not sufficient**. The deeper issue is that `AgentLoop` is both the orchestration engine *and* the composition root, and that modules depend on concrete implementations across what should be package boundaries. Fix the wiring first (or at least in parallel), and the directory moves become meaningful architectural boundaries instead of cosmetic groupings.

Without dependency inversion at package boundaries, the restructuring gives you cleaner directories but the same coupling graph — imports just get longer paths.
