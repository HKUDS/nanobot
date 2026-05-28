---
title: "Port OpenClaw's typed memory model to nanobot"
tags: [sketch]
created: 2026-05-28
status: draft
---

# Port OpenClaw's typed memory model to nanobot

This nanobot fork shares OpenClaw's workspace conventions
([[claude-code-on-server]] notes the lineage informally) but has diverged
on the memory model. OpenClaw's three-layer typed-and-promoted design is
materially better at preserving safety-relevant specifics — see
[[memory-consolidation-loses-safety-specifics]] for the failure mode
this addresses, and the Telegram thread on 2026-05-27 for the
discussion that prompted this sketch.

This is the architectural target. Smaller, ship-able slices below.

## What's wrong with the current model

Two files, lossy summariser as the only path between them:

| File | Cap | Update mechanism |
|--|--|--|
| `MEMORY.md` | 200 lines hard truncate | Full LLM rewrite per consolidation |
| `HISTORY.md` | 500 lines FIFO | Paragraph appended per consolidation |

Failure modes observed in practice:

1. **Generic consolidator prompt** — `"You are a memory consolidation agent. Call save_memory with your consolidation."` No priorities, no schema, no signal about what's safety-critical or otherwise irreplaceable.
2. **Consolidator is blind to USER.md / SOUL.md** — the main agent sees them every turn, the compressor doesn't. So the compressor has no priors about what kind of user this is.
3. **Hard 200-line cap on MEMORY.md** — when a write exceeds it, lines past the cap are silently dropped. Iroh's MEMORY.md is currently at 258 lines; next write loses 58 lines.
4. **HISTORY.md entries decay specifics on the way in** — concrete crisis context ("PTSD panic with visual hallucinations, 4-2-6 breathing + 5-4-3-2-1 worked") compressed within one consolidation cycle to a generic phrase ("stabilised using grounding techniques").
5. **HISTORY.md is not auto-loaded** — agent has to remember to grep. In practice, doesn't.
6. **Out-of-order entries** — Iroh's HISTORY.md has dates inserted out of chronological order, breaking temporal reasoning.
7. **One-shot rewrite means stale baselines compound** — when the consolidator fails (`LLM did not call save_memory, skipping` — Peewee's hit this twice in the last 24h), the *next* consolidation rewrites from the stale baseline.

## OpenClaw's model, restated

Three roles, separated by file and by lifecycle:

- **`MEMORY.md`** — durable facts, preferences, decisions. Auto-loaded *at session start* (not every turn). On-disk file is the source of truth; if it overflows the context budget, only the **injected copy** is truncated.
- **`memory/YYYY-MM-DD.md`** — daily notes, raw observations, session summaries. Indexed for `memory_search` / `memory_get` tools. **Retrieved by query, not auto-injected.**
- **`DREAMS.md`** *(optional)* — consolidation diary for human review.

The promotion path is the key insight:

- A "dreaming" pass collects short-term signals from daily notes
- Scores candidates (recall frequency, query diversity, score gates)
- **Promotes only qualified items** into `MEMORY.md`

So the durable-facts file accumulates *evidence-weighted* facts, not LLM-paraphrased summaries.

Stated principle: *"The model only 'remembers' what gets saved to disk — there is no hidden state."*

## What the port looks like in nanobot terms

### M1 — minimum-viable split (1 day)

Goal: stop the silent fact loss without changing the consolidator's job.

- Add `memory/YYYY-MM-DD.md` as a new artifact alongside MEMORY.md / HISTORY.md
- During consolidation, write the **full raw concatenation of the consolidated message window** (or a less-lossy rendering) to today's daily file, append-only
- Add `memory_search(query, days=30)` tool: greps `memory/YYYY-MM-DD.md` files within the window, returns matches with date stamps
- Add `memory_get(date)` tool: returns one daily file
- Leave existing MEMORY.md / HISTORY.md untouched

Wins: even if MEMORY.md loses something, the raw daily note is recoverable via grep. Costs: no schema, no scoring.

### M2 — soft cap, no on-disk truncation (½ day)

Goal: stop the 200-line cap from silently dropping facts.

- Change `MemoryStore.write_long_term`: keep the full file on disk, only the injected copy gets truncated (with a `[Context truncated — full file at <path>]` marker)
- Add a `memory_get_section(heading)` tool so the agent can pull in sections it knows it needs

### M3 — promotion / dreaming (2-3 days)

Goal: replace the one-shot rewrite with evidence-weighted promotion.

- Each daily note entry gets a salience tag (extracted by a small LLM pass: `safety`, `decision`, `preference`, `event`, `transient`)
- A "dreaming" pass runs on a schedule (nightly, or on heartbeat)
- For each candidate fact: compute score from (frequency it appears across daily notes) × (how often it's referenced in conversations via memory_search) × (salience tag weight)
- Above threshold → promote (upsert into MEMORY.md by key, append-with-source)
- Below threshold → leave in daily notes for later promotion or natural decay

### M4 — schema-aware sections (1 day)

Goal: typed MEMORY.md with declared merge policies.

- MEMORY.md becomes a markdown file with declared sections (`## facts`, `## events`, `## preferences`, `## open-loops`, `## people`)
- Section schema is declared per-agent in `MEMORY_SCHEMA.md` (sibling of USER.md). Iroh declares a `safety` section with merge=append, decay=never; Peewee declares `calendar`, `household`; Scribe declares `drafts`, `captures`.
- Architecture doesn't know about safety — *the agent's schema* does. This generalises [[memory-consolidation-loses-safety-specifics]]'s Iroh-specific patches.

## Order of work

M1 → M2 → M3 → M4. M1+M2 alone closes most of the immediate safety-info-loss gap; M3+M4 move to the principled architecture.

Each slice ships standalone. M1 backstops the current model; M2 fixes the hardest cap; M3 replaces the consolidator's job; M4 generalises.

## Out of scope

- Vector embeddings / semantic search. Daily-note grep is sufficient for the volumes nanobot bots see (Iroh: ~150 lines of HISTORY.md over 2 months).
- Cross-bot shared memory. Bots remain siloed.
- Migration tooling for existing MEMORY.md / HISTORY.md content. Existing files stay as-is; new structure accumulates alongside.
