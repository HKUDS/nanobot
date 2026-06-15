---
name: subconscious
description: Background memory bridge between nanobot and the Obsidian vault at /home/ab/Obsidian.
always: false
---

# Subconscious — Obsidian Vault Memory

The subconscious is nanobot's persistent background memory layer, inspired by OpenHuman's memory_tree architecture.
It continuously ingests your Obsidian vault notes into a searchable index and exports nanobot's memories back to the vault.

## Vault Location

- **Vault path**: `/home/ab/Obsidian`
- **Nanobot export folder**: `/home/ab/Obsidian/_nanobot/`
- **Index database**: `~/.nanobot/subconscious.db`

## How It Works

1. **Ingestion**: On startup, nanobot scans the vault and chunks each note into ≤3000-token fragments stored in SQLite FTS5.
2. **Watching**: A background watcher monitors the vault for file changes and re-ingests modified notes automatically.
3. **Export**: After each Dream cycle, nanobot exports `MEMORY.md`, `USER.md`, and `SOUL.md` to `/home/ab/Obsidian/_nanobot/`.
4. **Entity Graph**: `[[wiki-links]]` and `@mentions` are tracked as a knowledge graph.

## Available Tools

### `subconscious_search`
Full-text search over all vault notes. Use this to retrieve context before answering user questions.
```
subconscious_search(query="progetto foolish branding", limit=8)
```

### `subconscious_recall`
List recently modified vault notes to understand what the user has been working on.
```
subconscious_recall(limit=15)
```

### `subconscious_sync`
Force an immediate vault re-scan and memory export.
```
subconscious_sync(force=False)   # only new/modified files
subconscious_sync(force=True)    # re-index everything
```

### `subconscious_entities`
Return the vault knowledge graph: entities (people, projects, linked notes) and their connections.
```
subconscious_entities(limit=30)
```

## When to Use

- **Before answering a question**: run `subconscious_search` to check if the vault has relevant context
- **On startup or after editing Obsidian notes**: run `subconscious_sync`
- **To understand user's ongoing projects**: run `subconscious_recall` or `subconscious_entities`
- **When user asks about notes, projects, or past work**: always search the vault first

## Vault Structure

The vault at `/home/ab/Obsidian` contains these folders:
- `business/` — business notes and strategies
- `context/` — context and background documents
- `daily/` — daily notes
- `frank-test/` — test notes
- `notes/` — general notes
- `projects/` — project documentation
- `research/` — research notes
- `_templates/` — note templates
- `_nanobot/` — *(auto-generated)* nanobot memory exports

## Notes

- The FTS index supports boolean operators: `AND`, `OR`, `NOT`, phrase search `"exact phrase"`
- Tags extracted from `#tag` syntax and YAML frontmatter
- Wiki-links `[[note name]]` are tracked as entity connections
- The subconscious runs entirely locally — no data leaves the machine
