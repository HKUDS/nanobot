---
name: knowledge-extractor
description: Automatic knowledge extraction during memory consolidation.
metadata: {"nanobot":{"emoji":"🔍"}}
---

# Knowledge Extractor

Knowledge extraction runs automatically during memory consolidation — the same process that writes to MEMORY.md and HISTORY.md.

When the conversation session exceeds the memory window, old messages are processed by the LLM. Alongside the history summary and memory update, the LLM also identifies knowledge entries worth extracting into the structured knowledge base.

## How It Works

1. **Trigger**: Memory consolidation runs automatically when the session exceeds `memory_window` messages (default: 50)
2. **Input**: The old messages that are about to be trimmed from the session — the LLM sees the full conversation before it's lost
3. **Output**: Three things are produced in a single LLM call:
   - A **history entry** appended to `workspace/memory/HISTORY.md`
   - An updated **long-term memory** in `workspace/memory/MEMORY.md`
   - Zero or more **knowledge entries** written to `workspace/knowledge/`

## What Gets Extracted

Knowledge entries are created for information that deserves a standalone, structured entry in the knowledge base:

- **Topics** — subjects discussed in depth or repeatedly (includes concepts, ideas, frameworks)
- **People** — individuals mentioned with meaningful context
- **Decisions** — choices made with reasoning, insights, or lessons learned
- **Facts** — concrete, stable information worth retaining (configurations, setups, accounts)
- **Preferences** — user preferences for tools, styles, approaches
- **Projects** — ongoing work spanning multiple topics, people, or decisions
- **References** — books, articles, laws, theorems, films, music, art, websites

## Knowledge Entry Format

All entries follow the conventions defined in the knowledge management skill:
```
read_file(path="workspace/skills/knowledge/SKILL.md")
```

Each entry gets:
- YAML frontmatter with type, dates, related links, and tags
- A Summary section (also added to INDEX.md)
- A Details section with full content
- An Evolution section tracking changes over time

## Guidelines

- Not every conversation contains knowledge worth extracting — many will produce zero entries
- Existing entries are updated rather than duplicated (checked against INDEX.md)
- Knowledge base is for structured, topic-organized, long-lived information
- MEMORY.md is for facts the agent needs every turn (keep it small)
- HISTORY.md is for chronological, grep-searchable event log
- Don't duplicate information across these three outputs — use the right one

## Manual Extraction

The agent can also create knowledge entries manually during conversations by following the knowledge skill conventions. This is useful for:
- Extracting knowledge from conversations that haven't triggered consolidation yet
- Creating entries the user explicitly asks for
- Organizing information shared by the user outside of normal conversation flow
