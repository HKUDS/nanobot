# Source Provenance on Memory Events — Design Spec

> Date: 2026-03-31
> Status: Draft
> Related: [Source Conflation Research](../reports/2026-03-31-source-conflation-research.md) §7.6

## Problem

Memory events stored by the micro-extractor and full extractor carry no meaningful
provenance. The `source` field defaults to `"chat"` for every event. When memory is
injected into the agent's prompt, facts appear as:

```
- [2026-03-25] (fact) DS10540 planned duration is 186 days [sem=0.85, src=vector]
```

The `src=vector` indicates the retrieval method, not the origin. The agent cannot
determine whether the fact was extracted from an Obsidian tool result, stated by the
user in WhatsApp, or inferred during consolidation. This contributes to source
conflation — the agent blends memory facts with tool results without distinguishing
their provenance.

## Goal

Every memory event carries meaningful provenance: which channel the conversation
happened on and which tools (if any) produced the data. When rendered in the prompt,
provenance is visible:

```
- [2026-03-25] (fact, from: cli, exec:obsidian, read_file) DS10540 planned duration is 186 days [sem=0.85]
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Attribution granularity | Session-level (all events from a turn get the same provenance) | Event-level requires the LLM extractor to do source attribution — an unreliable, token-expensive correlation task |
| Session identity | Channel name + turn timestamp | No new ID generation; uses data already available at the call site |
| Storage mechanism | Existing `source` column + `metadata` JSON | No schema migration; `source` column already exists, metadata uses existing `_extra` packing |
| Tool hint format | `exec:<first-word-of-command>` | First word identifies the external system (obsidian, git, grep); subcommands are too granular for provenance |
| Legacy events | Left as `source="chat"` | Treated as "unknown legacy"; rendered without provenance label |

## Data Model

### `MemoryEvent.source` field (existing, repurposed)

The `source` field changes from a meaningless `"chat"` default to actual provenance:

| Scenario | `source` value |
|----------|---------------|
| User stated fact in CLI, no tools | `"cli"` |
| User stated fact in WhatsApp | `"whatsapp"` |
| Tools used in CLI session | `"cli,exec:obsidian,read_file"` |
| Tools used in web session | `"web,exec:grep"` |
| Pre-existing events (not migrated) | `"chat"` |

Format: comma-separated, channel first, then deduplicated tool hints sorted
alphabetically. No spaces around commas.

### `MemoryEvent.metadata` dict (existing, new key)

| Key | Value | Example |
|-----|-------|---------|
| `source_timestamp` | ISO timestamp of the conversation turn | `"2026-03-25T14:30:00"` |

### No schema changes

The `source` column already exists in the `events` table. The `source_timestamp` key
is stored in the `metadata` JSON blob via the existing `_extra` packing mechanism in
the ingester. No `ALTER TABLE`, no migration logic.

## Write Path

### 1. `message_processor.py` — boundary transformation

A private function `_extract_tool_hints` converts `ToolAttempt` objects (agent-layer
types) into primitive strings before crossing the agent→memory boundary:

| `tool_name` | Logic | Result |
|-------------|-------|--------|
| Not `exec` | Use tool name as-is | `"read_file"`, `"list_dir"` |
| `exec` with `command` arg | First word of command value | `"exec:obsidian"`, `"exec:git"` |
| `exec` without `command` arg | Just `"exec"` | `"exec"` |

Deduplication: convert to a set. The turn may call `exec` 5 times with obsidian
commands — only `"exec:obsidian"` appears once.

The message processor passes three new primitive values to both extractors:

```python
await self._micro_extractor.submit(
    user_message=msg.content,
    assistant_message=final_content,
    channel=msg.channel,
    tool_hints=tool_hints,        # list[str], e.g. ["exec:obsidian", "read_file"]
    turn_timestamp=now_iso(),     # str, e.g. "2026-03-31T14:30:00"
)
```

Only primitive types (`str`, `list[str]`) cross the boundary. No agent-layer types
leak into the memory subsystem.

### 2. Micro-extractor and full extractor — source stamping

Both extractors gain three new optional parameters: `channel`, `tool_hints`,
`turn_timestamp`. Internally, each builds the source string:

```python
def _build_source(channel: str, tool_hints: list[str]) -> str:
    ch = channel or "unknown"
    parts = [ch] + sorted(set(tool_hints))
    return ",".join(p for p in parts if p)
```

When creating `MemoryEvent` objects from LLM output, each event is stamped:

```python
event.source = _build_source(channel, tool_hints)
event.metadata["source_timestamp"] = turn_timestamp
```

Parameters default to empty values for backward compatibility — existing callers
(tests, consolidation) continue to work without changes.

### Example end-to-end

Turn: user asks "Summarize DS10540" in CLI. Agent calls `exec("obsidian files
folder=DS10540")`, then `read_file("PM/DS10540/Opportunity Brief.md")`.

1. `message_processor` extracts hints: `["exec:obsidian", "read_file"]`
2. Passes `channel="cli"`, `tool_hints=["exec:obsidian", "read_file"]`,
   `turn_timestamp="2026-03-31T14:30:00"` to micro-extractor
3. Micro-extractor builds: `source="cli,exec:obsidian,read_file"`
4. Each extracted event gets `source="cli,exec:obsidian,read_file"` and
   `metadata={"source_timestamp": "2026-03-31T14:30:00"}`
5. Ingester writes `source` to the existing column, `source_timestamp` packs
   into the JSON metadata blob via `_extra`

## Read Path

### `context_assembler.py` — prompt rendering

The `_memory_item_line` method changes:

**Before:**
```
- [2026-03-25] (fact) DS10540 planned duration is 186 days [sem=0.85, rec=0.72, src=vector]
```

**After:**
```
- [2026-03-25] (fact, from: cli, exec:obsidian, read_file) DS10540 planned duration is 186 days [sem=0.85, rec=0.72]
```

Rules:
- Include `from: <source>` when `source` is present and not `"chat"` (legacy)
- Drop `src=vector` / `src=fts` — retrieval method is an internal detail, not useful
  provenance for the agent
- Legacy events with `source="chat"` render as before: `(fact)` with no provenance label

### Token budget

The `from: ...` label adds ~5-15 tokens per memory item. With 10-20 items typical,
that's 50-300 extra tokens — negligible relative to the memory section budget.

### No retrieval changes

Vector search, FTS, reranking, and scoring operate on `summary` text. Provenance is
display-only and does not affect retrieval.

## Files Changed

| File | Change | LOC |
|------|--------|-----|
| `nanobot/agent/message_processor.py` | Add `_extract_tool_hints()`, pass channel + hints + timestamp to extractors | ~20 |
| `nanobot/memory/write/micro_extractor.py` | Accept provenance params, build source string, stamp events | ~15 |
| `nanobot/memory/write/extractor.py` | Same as micro-extractor | ~15 |
| `nanobot/memory/read/context_assembler.py` | Surface `source` in `_memory_item_line`, drop `src=vector` | ~10 |

**Total: ~60 lines across 4 files. No new files.**

## What Doesn't Change

- `MemoryEvent` model — uses existing `source` field and `metadata` dict
- `events` table schema — no migration
- `EventIngester` — events arrive with `source` already set
- `EventStore`, `MemoryDatabase` — no changes
- Retrieval, reranking, scoring — provenance is display-only
- Any other subsystem

## Architectural Compliance

- **Import direction**: only primitives (`str`, `list[str]`) cross the agent→memory
  boundary. No agent types in memory subsystem.
- **Domain logic placement**: source string construction lives in the extractors
  (`memory/write/`), not in orchestration (`agent/`).
- **Stable core untouched**: TurnRunner, GuardrailChain, ContextBuilder unchanged.
  Changes are in the volatile edge (data stamping, display formatting).
- **No new files**: changes to 4 existing files only.
- **No schema migration**: uses existing column and metadata mechanism.
- **Backward compatible**: new extractor parameters default to empty values.

## Testing

| Test | What it verifies |
|------|-----------------|
| `test_extract_tool_hints_exec` | `exec` with command → `"exec:<first-word>"` |
| `test_extract_tool_hints_non_exec` | `read_file` → `"read_file"` |
| `test_extract_tool_hints_dedup` | Multiple identical exec calls → single hint |
| `test_extract_tool_hints_no_command` | `exec` without command arg → `"exec"` |
| `test_build_source_channel_only` | No tools → `"cli"` |
| `test_build_source_with_tools` | Channel + tools → `"cli,exec:obsidian,read_file"` |
| `test_micro_extractor_stamps_source` | Events created with correct source and metadata |
| `test_memory_item_line_with_provenance` | Rendering includes `from: ...` label |
| `test_memory_item_line_legacy` | `source="chat"` renders without provenance |
| `test_memory_item_line_no_retrieval_method` | `src=vector` no longer in output |
