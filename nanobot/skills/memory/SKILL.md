---
name: memory
description: Automatic memory system — facts are extracted from conversations and stored in a database.
always: true
---

# Memory

## How Memory Works

Memory is managed automatically. You do NOT need to write to files manually.

- **Your memory context** is included in the system prompt (see the Memory section above).
- **Consolidation** runs automatically after conversations grow large — it extracts facts, preferences, relationships, and events into the memory database.
- **Profile updates** (preferences, stable facts) are extracted by the consolidation pipeline.

## Searching Past Events

Use the CLI to search for past events and facts:

```bash
nanobot memory inspect --query "keyword"
```

## Memory Maintenance

```bash
nanobot memory rebuild    # Rebuild memory snapshot from database
nanobot memory verify     # Check memory integrity
```

## Important

- Do NOT use `edit_file` or `write_file` on memory files — the consolidation system manages storage automatically.
- Memory context in your prompt comes from the database, not from files on disk.
