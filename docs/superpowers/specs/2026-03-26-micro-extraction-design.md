# Micro-Extraction — Design Spec

**Date:** 2026-03-26
**Status:** Draft
**Problem:** 95% of nanobot sessions never consolidate — memory extraction only triggers after 50 messages, but most sessions are 2-30 messages. Learned facts, preferences, corrections, and project context are lost.

---

## Context

### The Gap

Nanobot has a sophisticated memory system (9 data types, knowledge graph, belief lifecycle, reranking) but it almost never writes to it. Analysis of 61 sessions shows:
- 60 sessions never consolidated (0 events extracted)
- Only 3 sessions reached the 50-message consolidation threshold
- 95% of conversations lose all learned information

The memory system is architecturally sound — the problem is purely a write-timing issue. The retrieval pipeline, scoring, reranking, and graph augmentation all work correctly on an almost empty database.

### Industry Context

The emerging best practice (Zep, mem0, LangMem) is a two-tier approach:
1. **Lightweight per-turn extraction** — captures facts immediately after every meaningful turn
2. **Periodic deep consolidation** — comprehensive extraction, deduplication, profile management, snapshot rebuild

This mirrors human memory formation: immediate encoding (fast, imprecise) followed by consolidation during sleep (slow, deep integration).

### Design Principle

Micro-extraction is a best-effort, additive optimization. Full consolidation remains the authoritative memory pipeline. Micro-extracted events feed into the same storage as consolidation events — deduplication handles overlap automatically.

---

## Design

### MicroExtractor Class

**File:** `nanobot/memory/write/micro_extractor.py`

A standalone service that extracts memory events from individual conversation turns.

```python
class MicroExtractor:
    """Lightweight per-turn memory extraction.

    After each agent turn, extracts structured memory events from the
    user message + assistant response. Runs asynchronously in the
    background. Events are written to the same SQLite events table
    used by full consolidation.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        ingester: EventIngester,
        model: str = "gpt-4o-mini",
        enabled: bool = False,
    ) -> None: ...

    async def submit(self, user_message: str, assistant_message: str) -> None:
        """Submit a turn for background extraction. Returns immediately."""
```

**Constructor receives:**
- `provider` — LLM provider for the extraction call
- `ingester` — EventIngester for writing events (reuses existing dedup, embed, graph pipeline)
- `model` — configurable extraction model (default `gpt-4o-mini`)
- `enabled` — feature gate (default off)

**`submit()` method:**
1. Returns immediately if `enabled is False`
2. Submits `_extract_and_ingest()` as a background `asyncio.Task`
3. Returns immediately (non-blocking)

**`_extract_and_ingest()` internal method:**
1. Calls `provider.chat()` with micro-extraction prompt + tool schema
2. Parses tool call arguments (events array)
3. If empty array or no tool call → return (nothing worth extracting)
4. Calls `ingester.append_events(events)`
5. On any exception → log warning, return (silent drop — consolidation is the safety net)

### Extraction Prompt

**File:** `nanobot/templates/prompts/micro_extract.md`

```markdown
You are a memory extraction agent. Analyze this conversation exchange and extract
any facts, preferences, decisions, corrections, or relationships worth remembering
across sessions.

Return ONLY items that would be valuable in future conversations. Skip:
- Greetings, acknowledgments, small talk
- Transient task details (tool outputs, intermediate steps)
- Information the assistant already knows from its training

If nothing is worth remembering, call the tool with an empty events array.
```

The user message and assistant response are passed as conversation messages (not formatted text):

```python
messages = [
    {"role": "system", "content": prompt},
    {"role": "user", "content": user_message},
    {"role": "assistant", "content": assistant_message},
]
```

### Tool Schema

Subset of the existing `_CONSOLIDATE_MEMORY_TOOL` schema — compatible event format, fewer fields:

```python
_MICRO_EXTRACT_TOOL = [{
    "type": "function",
    "function": {
        "name": "save_events",
        "description": "Save extracted memory events. Return empty array if nothing worth remembering.",
        "parameters": {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "preference", "fact", "task",
                                    "decision", "constraint", "relationship",
                                ],
                            },
                            "summary": {"type": "string"},
                            "entities": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "confidence": {"type": "number"},
                        },
                        "required": ["type", "summary"],
                    },
                },
            },
            "required": ["events"],
        },
    },
}]
```

**Differences from full consolidation schema:**
- No `history_entry` — no history writing per-turn
- No `profile_updates` — events only, profile managed by full consolidation
- No `triples` — graph ingestion derives triples from entities during event ingestion
- No `salience`, `ttl_days`, `source_span` — simplifies the model's job

### Integration Point

**Where:** `MessageProcessor._process_message()`, after `_save_turn()` and session save.

```python
if self._micro_extractor is not None:
    await self._micro_extractor.submit(
        user_message=msg.content,
        assistant_message=final_content,
    )
```

**What is passed:** Only the user's words and the agent's final text response. No tool results, tool call metadata, or system messages — only the meaningful exchange.

**Wiring in `agent_factory.py`:**

```python
micro_extractor = MicroExtractor(
    provider=provider,
    ingester=memory_store.ingester,
    model=config.micro_extraction_model or "gpt-4o-mini",
    enabled=config.micro_extraction_enabled,
)
```

Passed to `MessageProcessor` via `_ProcessorServices`.

### Interaction with Full Consolidation

The two extraction paths coexist without conflict:

**Deduplication handles overlap.** When full consolidation eventually runs, it processes ALL unconsolidated messages — including turns micro-extraction already covered. `EventIngester.append_events()` prevents duplicates via:
1. Exact ID match → merge
2. Semantic duplicate detection → merge with similarity score
3. Semantic supersession → old event marked superseded

**Full consolidation remains unchanged.** It still triggers at `memory_window` threshold, extracts events + profile + history, rebuilds snapshot, and uses the main model for higher quality.

**Complementary roles:**

| Aspect | Micro-extraction | Full Consolidation |
|---|---|---|
| Timing | Per-turn (async) | Every 50 messages (async) |
| Model | gpt-4o-mini (configurable) | Main model |
| Cost | ~$0.001/turn | ~$0.05/run |
| Extracts | Events only | Events + profile + history |
| Quality | Good enough | Comprehensive |
| Purpose | Immediate searchability | Deep integration + cleanup |

### Configuration

New fields in `AgentConfig`:

```python
micro_extraction_enabled: bool = False    # Opt-in feature gate
micro_extraction_model: str | None = None # None = "gpt-4o-mini"
```

### Error Handling

Silent drop on any failure. The extraction runs in a background task — exceptions are caught, logged as warnings, and swallowed. Rationale:
- The information isn't lost — it's in session messages
- Full consolidation is the safety net for anything micro-extraction misses
- No user-visible impact from extraction failures

---

## File Impact

**Files created:**

| File | Package | Purpose | LOC estimate |
|---|---|---|---|
| `nanobot/memory/write/micro_extractor.py` | `memory/write/` | MicroExtractor class | ~80-100 |
| `nanobot/templates/prompts/micro_extract.md` | templates | Extraction prompt | ~10 |
| `tests/test_micro_extraction.py` | tests | Unit tests | ~120-150 |
| `tests/integration/test_micro_extraction.py` | tests/integration | Real LLM integration test | ~40-50 |

**Files modified:**

| File | Change | LOC added |
|---|---|---|
| `nanobot/config/schema.py` | Add `micro_extraction_enabled`, `micro_extraction_model` | ~3 |
| `nanobot/agent/agent_factory.py` | Construct MicroExtractor, pass to services | ~10 |
| `nanobot/agent/agent_components.py` | Add `micro_extractor` to `_ProcessorServices` | ~2 |
| `nanobot/agent/message_processor.py` | Call `micro_extractor.submit()` after `_save_turn()` | ~5 |
| `nanobot/memory/write/__init__.py` | Export MicroExtractor | ~1 |

**Boundary compliance:**
- MicroExtractor in `memory/write/` — memory's bounded context, write subdirectory
- Receives `LLMProvider` and `EventIngester` via dependency injection — no cross-package instantiation
- Construction in `agent_factory.py` (composition root)
- `memory/write/` grows from 3 to 4 files — well under 15-file limit

---

## Testing Strategy

**Unit tests** (`tests/test_micro_extraction.py`):
- `test_submit_when_disabled_does_nothing` — enabled=False, provider never called
- `test_submit_extracts_and_ingests_events` — mock provider returns 2 events, verify ingester called correctly
- `test_submit_empty_events_skips_ingestion` — empty array, ingester not called
- `test_submit_no_tool_call_skips_ingestion` — text response, ingester not called
- `test_submit_is_nonblocking` — returns immediately
- `test_submit_failure_logs_warning` — provider exception, warning logged, no propagation
- `test_submit_ingestion_failure_logs_warning` — ingester exception, warning logged
- `test_tool_schema_has_required_fields` — type and summary required
- `test_tool_schema_event_types` — 6 valid event types

**Integration test** (`tests/integration/test_micro_extraction.py`):
- `test_micro_extraction_real_llm` — uses real `gpt-4o-mini`, sends realistic exchange ("I always work on DS10540 with Alice. We use PostgreSQL."), asserts extracted events contain relevant entities. Skips without API key.

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Gate strategy | Combined gate + extraction in one LLM call | Model returns empty array for trivial turns; one call, one code path |
| Execution | Async background task | Zero latency impact; 2-3 second gap negligible for real users |
| Model | Configurable, default gpt-4o-mini | Extraction from 2-message exchange doesn't need gpt-4o reasoning |
| Scope | Events only, no profile updates | Profile management too complex for per-turn cheap model |
| Schema | Subset of consolidation event schema | Compatible with EventIngester, no new storage or parsing |
| Architecture | Standalone MicroExtractor class | Single responsibility, testable in isolation, clean wiring |
| Error handling | Silent drop with warning log | Consolidation is the safety net; retries add complexity for best-effort feature |
| Feature gate | Opt-in (enabled=False default) | New feature, validate before enabling by default |
