# Source Labels & Source-Tracking Design

> Date: 2026-03-31
> Status: Approved
> Origin: sections 7.2 and 7.3 of `docs/superpowers/reports/2026-03-31-source-conflation-research.md`

## Problem

The agent blends facts from declarative memory, tool results, and model training data
into composite answers without distinguishing their provenance. The LLM receives an
undifferentiated context blob where memory sections have no source labels, making it
impossible for the model to reliably attribute claims to their origin.

## Solution

Two targeted changes from the source conflation research:

1. **Source labels on memory and tool results** (7.2) — label every memory section
   with `[MEMORY — ...]` and every tool result with `[TOOL RESULT — ...]`
2. **Source-tracking in reasoning protocol** (7.3) — add a 5th question to the
   `[REASONING]` block requiring source attribution before acting

## Design

### Change 1: Source Labels on Memory Sections

**File: `nanobot/memory/read/context_assembler.py`** (Phase 4 assembly, lines ~278-312)

Replace generic section headers with source-labeled headers:

| Current Header | New Header |
|---------------|------------|
| `## Long-term Memory (project-specific — cite these verbatim)` | `## Long-term Memory [MEMORY — from previous sessions, may be stale]` |
| `## Profile Memory` | `## Profile Memory [MEMORY — from previous sessions, may be stale]` |
| `## Relevant Semantic Memories` | `## Relevant Semantic Memories [MEMORY — may be stale, verify before citing]` |
| `## Entity Graph` | `## Entity Graph [MEMORY — derived relationships, verify before citing]` |
| `## Relevant Episodic Memories` | `## Relevant Episodic Memories [MEMORY — past events, verify if still current]` |
| `## Recent Unresolved Tasks/Decisions` | `## Recent Unresolved Tasks/Decisions [MEMORY — may already be resolved]` |
| `## Relevant Reflection Memories` | `## Relevant Reflection Memories [MEMORY — past reflections]` |

Sub-headings ("User-specific facts...", "Retrieved factual knowledge...", etc.) are
removed — the `[MEMORY]` label makes the provenance explicit and the sub-headings
become redundant.

**File: `nanobot/templates/prompts/memory_header.md`**

Update the wrapper template to include the source label in the top-level heading:

```markdown
# Memory [MEMORY — from previous sessions, may be stale]

These are facts from previous conversations. They may be outdated.
Use them as hints for WHERE to look, not as authoritative answers.
Always verify memory facts with fresh tool results before citing them.
Use the exact names, regions, and terms below — do not substitute general knowledge.

{memory}
```

**File: `nanobot/context/context.py`** (`add_tool_result` method)

Add a `[TOOL RESULT — fresh data from this conversation]` label before the XML tags:

```python
wrapped = (
    f"[TOOL RESULT — fresh data from this conversation]\n"
    f"<tool_result>\n{result}\n</tool_result>"
)
```

The existing `<tool_result>` tag check (`if result.startswith("<tool_result>")`) is
preserved for backward compatibility with pre-wrapped results.

### Change 2: Source-Tracking in Reasoning Protocol

**File: `nanobot/templates/prompts/reasoning.md`**

Add a 5th question to the `[REASONING]` block:

```
5. Source check: Am I about to cite memory or tool results? If memory, have I verified it with a tool?
```

This forces the model to explicitly consider provenance before its first tool call.

**File: `nanobot/templates/prompts/self_check.md`**

Strengthen item 4 to reference the new `[MEMORY]` labels:

```
4. For claims from sections marked [MEMORY] — did you verify them with a tool this session?
   If not, either verify now or attribute them: "Based on previous sessions..."
```

### Token Impact

- Memory section headers: ~60 additional tokens across all sections (negligible)
- Tool result labels: ~10 tokens per tool call
- Reasoning protocol: ~15 tokens (one-time in system prompt)
- Self-check: ~5 tokens delta

Total: ~85 tokens in system prompt + ~10 per tool call. Well within budget.

## Files to Modify

1. `nanobot/memory/read/context_assembler.py` — section headers in `build()` Phase 4
2. `nanobot/templates/prompts/memory_header.md` — wrapper template heading
3. `nanobot/templates/prompts/reasoning.md` — add question 5 to REASONING block
4. `nanobot/templates/prompts/self_check.md` — strengthen source attribution check
5. `nanobot/context/context.py` — tool result labeling in `add_tool_result()`

## Tests to Update

- Tests asserting on context_assembler section headers
- Tests asserting on tool result wrapping format
- Prompt regression tests (if they check exact content)

## Out of Scope

- Citations API integration (7.4) — separate, larger initiative
- "Wrong source" guardrail (7.5) — separate initiative
- Source provenance on memory events (7.6) — schema change, separate initiative
- Fixing competing instructions (7.1) — already done in PR #109
