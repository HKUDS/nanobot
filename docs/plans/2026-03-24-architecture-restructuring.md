# Architecture Restructuring Plan

> Date: 2026-03-24
> Status: Approved — ready for implementation
> Companion: [Architecture Review](../architecture-review-2026-03.md)

---

## Goal

Restructure the `nanobot/` package so that directory layout reflects architectural
boundaries. The `agent/` package currently contains ~25,000 lines across 68 files
spanning 6+ distinct concerns. After this work, each top-level package will own a
single bounded context with a narrow public API.

## Principles

- **One PR, one structural move.** Each PR is independently mergeable and CI-validated.
- **No backward-compatibility shims.** All imports are internal — find-and-replace, no re-exports.
- **No logic changes.** Pure file moves + import rewrites. Refactoring internals is out of scope.
- **Each PR updates its own import-check rules.** No deferred cleanup.
- **Sequential execution.** Each PR merges to main before the next one starts.

## Before / After

### Before (current)

```
nanobot/
├── agent/                  # 34 top-level .py + memory/ + tools/  (~25k LOC)
│   ├── memory/             # 28 files, 10k LOC — full subsystem
│   ├── tools/              # 17 files, 5k LOC — infrastructure + domain tools
│   ├── loop.py             # orchestration
│   ├── turn_orchestrator.py
│   ├── message_processor.py
│   ├── agent_factory.py    # composition root
│   ├── coordinator.py      # multi-agent
│   ├── delegation.py       # multi-agent
│   ├── context.py          # prompt assembly
│   ├── observability.py    # instrumentation
│   ├── ... (26 more files)
│   └── __init__.py         # 25 exports from 15 modules
├── bus/
├── channels/
├── config/
├── providers/
├── session/
├── eval/
├── cron/
├── heartbeat/
├── cli/
├── web/
└── utils/
```

### After (target)

```
nanobot/
├── agent/                  # NARROWED — orchestration only (~11 files)
│   ├── loop.py
│   ├── turn_orchestrator.py
│   ├── turn_types.py
│   ├── message_processor.py
│   ├── streaming.py
│   ├── verifier.py
│   ├── failure.py
│   ├── reaction.py
│   ├── agent_factory.py
│   ├── agent_components.py
│   └── callbacks.py
│
├── memory/                 # PROMOTED from agent/memory/
│   ├── store.py            # facade
│   ├── unified_db.py       # SQLite backend
│   ├── embedder.py
│   ├── write/              # ingestion pipeline
│   ├── read/               # retrieval pipeline
│   ├── ranking/            # reranking
│   ├── persistence/        # profile, snapshot
│   ├── graph/              # knowledge graph + ontology
│   └── ...
│
├── tools/                  # PROMOTED from agent/tools/
│   ├── base.py             # Tool ABC + ToolResult
│   ├── registry.py         # ToolRegistry
│   ├── executor.py         # from agent/tool_executor.py
│   ├── tool_loop.py        # from agent/tool_loop.py
│   ├── setup.py            # from agent/tool_setup.py
│   ├── capability.py       # from agent/capability.py
│   ├── result_cache.py
│   └── builtin/            # domain tool implementations
│       ├── filesystem.py
│       ├── shell.py
│       ├── web.py
│       ├── excel.py
│       ├── powerpoint.py
│       └── ...
│
├── coordination/           # NEW — multi-agent routing + delegation
│   ├── coordinator.py
│   ├── delegation.py
│   ├── delegation_contract.py
│   ├── delegation_advisor.py
│   ├── task_types.py
│   ├── registry.py
│   ├── role_switching.py
│   ├── scratchpad.py
│   └── mission.py
│
├── observability/          # NEW — cross-cutting instrumentation
│   ├── langfuse.py         # from agent/observability.py
│   ├── tracing.py          # from agent/tracing.py
│   ├── metrics.py          # merged from agent/metrics.py + nanobot/metrics.py
│   └── bus_progress.py     # from agent/bus_progress.py
│
├── context/                # NEW — prompt assembly + skills
│   ├── context.py          # from agent/context.py
│   ├── compression.py      # from agent/compression.py
│   ├── prompt_loader.py    # from agent/prompt_loader.py
│   └── skills.py           # from agent/skills.py
│
├── bus/                    # unchanged
├── channels/               # unchanged
├── config/                 # unchanged
├── providers/              # unchanged
├── session/                # unchanged
├── eval/                   # unchanged
├── cron/                   # unchanged
├── heartbeat/              # unchanged
├── cli/                    # unchanged
├── web/                    # unchanged
└── utils/                  # unchanged
```

---

## PR Sequence

### PR 1 — Promote memory/ to top-level

| | |
|---|---|
| **Branch** | `refactor/promote-memory` |
| **Scope** | Move `nanobot/agent/memory/` → `nanobot/memory/` |
| **Files moved** | 28 (entire memory package) |
| **Import rewrites** | ~90 across agent core (6), cli/memory.py (~12), eval (2), scripts (2), tests (~68) |
| **Internal changes** | None — all 28 memory modules use relative imports |
| **Cross-package imports** | Memory imports `nanobot.context.prompt_loader` and `nanobot.observability.tracing` — these become cross-package; direction is correct (memory → agent utilities) |
| **Other changes** | Remove `MemoryStore` from `agent/__init__.py` exports; update `scripts/check_imports.py` boundary rules; update `consolidation.py` import |
| **Risk** | Low — pure move + rename, no logic changes |
| **Validation** | `make check` catches any missed imports |

### PR 2 — Promote tools/ to top-level

| | |
|---|---|
| **Branch** | `refactor/promote-tools` |
| **Scope** | Move `nanobot/agent/tools/` → `nanobot/tools/`; move `tool_executor.py`, `tool_loop.py`, `tool_setup.py`, `capability.py` from `agent/` into `nanobot/tools/`; create `builtin/` subdirectory for domain implementations |
| **Files moved** | ~21 (17 from tools/ + 4 from agent/) |
| **Import rewrites** | ~80+ across agent, coordination (future — at this point still in agent), cli, tests |
| **Key decisions** | `builtin/` contains: filesystem, shell, web, excel, powerpoint, email, cron, feedback, message, mission, scratchpad, delegate, mcp. Parent contains: base, registry, executor, tool_loop, setup, capability, result_cache |
| **Cross-package imports** | `delegation.py` imports specific tool classes (ReadFileTool, ExecTool, etc.) — these become cross-package imports from tools/builtin/ |
| **Risk** | Medium — more files moving, tool registration wiring in agent_factory.py needs careful updating |
| **Validation** | `make check` |

### PR 3 — Extract coordination/

| | |
|---|---|
| **Branch** | `refactor/extract-coordination` |
| **Scope** | Move 9 files from `nanobot/agent/` → `nanobot/coordination/`: coordinator, delegation, delegation_contract, delegation_advisor, task_types, registry, role_switching, scratchpad, mission |
| **Files moved** | 9 |
| **Import rewrites** | ~50+ across agent (loop, agent_factory, agent_components, turn_orchestrator, message_processor), cli, tests |
| **Cross-package imports** | coordination imports from tools/ (delegate tool classes), memory/ (scratchpad persistence), agent/ (streaming, callbacks). Agent imports from coordination/ (dispatcher, coordinator) |
| **Risk** | Medium — highest number of bidirectional imports between agent ↔ coordination |
| **Validation** | `make check` |

### PR 4 — Extract observability/

| | |
|---|---|
| **Branch** | `refactor/extract-observability` |
| **Scope** | Move `observability.py`, `tracing.py`, `metrics.py`, `bus_progress.py` from `agent/` → `nanobot/observability/`. Merge top-level `nanobot/metrics.py` into the new package |
| **Files moved** | 5 (4 from agent + 1 top-level merge) |
| **Import rewrites** | ~40+ across agent, memory, coordination, tools, cli, tests |
| **Key decisions** | `observability.py` → `langfuse.py` (more descriptive). Top-level `nanobot/metrics.py` absorbed into `observability/metrics.py` |
| **Risk** | Low — small package, observability is consumed everywhere but owns nothing |
| **Validation** | `make check` |

### PR 5 — Extract context/

| | |
|---|---|
| **Branch** | `refactor/extract-context` |
| **Scope** | Move `context.py`, `compression.py`, `prompt_loader.py`, `skills.py` from `agent/` → `nanobot/context/` |
| **Files moved** | 4 |
| **Import rewrites** | ~30+ across agent, memory (consolidation_pipeline, extractor use prompt_loader), coordination, tests |
| **Cross-package imports** | context/ imports from memory/ (MemoryStore for context assembly), tools/ (ToolRegistry for schema), providers/ (LLMProvider for compression). Memory imports from context/ (prompt_loader) |
| **Risk** | Medium — context.py is central; many modules depend on ContextBuilder |
| **Validation** | `make check` |

### PR 6 — Memory internal subdirectories

| | |
|---|---|
| **Branch** | `refactor/memory-subdirs` |
| **Scope** | Organize `nanobot/memory/` internals into subdirectories: `write/` (extractor, ingester, conflicts), `read/` (retriever, retrieval_planner, context_assembler), `ranking/` (reranker, onnx_reranker), `persistence/` (profile_io, snapshot, profile_correction), `graph/` (graph, entity_classifier, entity_linker, ontology_types, ontology_rules) |
| **Files moved** | ~15 files reorganized into 5 subdirectories |
| **Import rewrites** | Internal only — relative imports within memory/ need updating. No external import changes (external consumers import from `nanobot.memory` top-level `__init__.py`) |
| **Key constraint** | `__init__.py` must continue to export all 48 public symbols — internal reorganization is invisible to consumers |
| **Risk** | Low — purely internal to memory package |
| **Validation** | `make check` |

### PR 7 — Final documentation update

| | |
|---|---|
| **Branch** | `refactor/update-architecture-docs` |
| **Scope** | Final pass on all documentation: `docs/architecture.md` (module ownership table, dependency rules, data flow diagrams), `CLAUDE.md` (project structure, module boundaries, import rules), `docs/architecture-review-2026-03.md` (mark completed items), ADR amendment or new ADR documenting the restructuring |
| **Files changed** | Documentation only — no code |
| **Risk** | None |
| **Note** | Each earlier PR includes minimal doc updates for its own scope. This PR ensures everything is consistent and complete |

---

## Dependency Graph Between PRs

```
PR1 (memory) → PR2 (tools) → PR3 (coordination) → PR4 (observability) → PR5 (context)
                                                                                 ↓
                                                                          PR6 (memory subdirs)
                                                                                 ↓
                                                                          PR7 (docs)
```

PRs 1-5 are strictly sequential — each changes the import landscape that later PRs
depend on. PR 6 depends on PR 1 (memory must be top-level first). PR 7 is last.

## Execution Protocol (per PR)

1. Create branch from main: `git checkout -b refactor/<name>`
2. Move files: `git mv` to preserve history
3. Find-and-replace imports across the entire codebase
4. Update `scripts/check_imports.py` boundary rules
5. Update `nanobot/agent/__init__.py` — remove moved exports
6. Minimal doc updates for the moved package
7. `make check` — must pass clean
8. Commit, push, open PR
9. Wait for CI green, merge to main
10. Next PR starts from updated main

## Out of Scope

- **No logic changes.** This plan is purely structural.
- **No dependency inversion.** Adding Protocol interfaces at package boundaries is a
  separate initiative (tracked in the architecture review as Problem #8).
- **No internal refactoring.** Files like `ingester.py` (919 LOC) and `retriever.py`
  (824 LOC) that are too large are not decomposed here.
- **No CapabilityRegistry redesign.** Its identity problem (Problem #10) is deferred.
- **No consolidation.py merge.** The awkward split between `agent/consolidation.py` and
  `memory/consolidation_pipeline.py` is preserved for now.
