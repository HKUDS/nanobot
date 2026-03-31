# ADR-012: Memory Context Header Pattern

## Status
Accepted — 2026-03-31

## Context

The agent's system prompt includes memory sections (semantic, episodic, profile, etc.)
injected by `ContextAssembler`. The sub-headers on these sections directly influence
whether the LLM treats memory facts as authoritative or as hints requiring verification.

### The problem: competing instructions

Three iterations of sub-header styles were deployed and tested against the DS10540
source-conflation case (Langfuse traces 2026-03-31, sessions at 11:19, 12:35, 13:34):

| Style | Example | Result |
|-------|---------|--------|
| **Authority-granting** | `"cite these verbatim"`, `"use these exact terms when answering"` | Agent cited stale memory as fact. Worst conflation. |
| **Metadata-only labels** | `[MEMORY — from previous sessions, may be stale]` | Haiku ignored them entirely. Identical conflation. |
| **Action-oriented** | `(verify with tools before citing)` | Haiku follows the directive. Promising but lacked provenance. |

Key finding: **Haiku follows behavioral directives but ignores metadata labels.** Larger
models (Sonnet, Opus) are expected to use provenance information for source attribution,
but we have no empirical traces to confirm this.

### The design tension

- Small models need **explicit action instructions** ("verify before citing") right next
  to the data — distant header instructions are overridden by closer text.
- Large models benefit from **provenance metadata** ("from previous sessions") to
  distinguish memory-sourced claims from tool-sourced claims in their reasoning.
- Using only actions helps Haiku but starves larger models of attribution context.
- Using only metadata helps (maybe) larger models but is invisible to Haiku.

## Decision

Use a unified **(origin — action)** pattern on every memory sub-header:

```
## Section Name (origin — action)
```

Where:
- **origin** = provenance hint — where the data came from (e.g., "from previous sessions",
  "derived relationships", "project-specific")
- **action** = behavioral directive — what the model should do (e.g., "verify before citing",
  "verify with tools", "may already be resolved")

### Applied pattern

| Section | Header |
|---------|--------|
| Memory (outer header) | `(from previous sessions — verify before citing)` |
| Long-term Memory | `(from previous sessions, project-specific — verify before citing)` |
| Profile Memory | `(from previous sessions — verify before citing)` |
| Semantic Memories | sub-line: `(from previous sessions — verify with tools before citing)` |
| Entity Graph | `(derived relationships — verify before citing)` |
| Episodic Memories | sub-line: `(from previous sessions — verify with tools)` |
| Reflection Memories | `(from previous sessions — check if still relevant)` |
| Unresolved Tasks | `(from previous sessions — check if still open)` |

Semantic and Episodic use a two-line format (heading + description line) because they
contain item lists that benefit from an introductory description. The other sections
use inline parentheticals.

### Why not separate tags?

The `[MEMORY — ...]` bracket notation was tested (PR #111) and shown to have zero
behavioral impact on Haiku in Langfuse traces. Embedding provenance inside the
action-oriented parenthetical costs no extra tokens and serves both model sizes
with one string.

## Consequences

### Positive
- Single consistent pattern across all memory sections
- Works for both small models (action directive) and large models (provenance hint)
- No wasted tokens on metadata-only labels that small models ignore
- Self-documenting — reading the header tells you both what the data is and what to do

### Negative
- Provenance information is coarser than structured metadata (no session IDs, timestamps)
- Effectiveness on larger models is theoretical — not yet validated with traces
- Pattern must be maintained manually when adding new memory section types

### Future work
- Validate with Sonnet/Opus traces once model switching is deployed
- Consider Anthropic Citations API (structural enforcement) as a complement — see
  `docs/superpowers/reports/2026-03-31-source-conflation-research.md` section 7.4
