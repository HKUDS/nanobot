---
name: memory
description: Enhanced memory system with two layers - grep-based MEMORY.md/HISTORY.md (always available) plus optional OpenViking semantic search for structured conversation storage and advanced recall. When OpenViking is enabled, native tools (openviking_read, openviking_search, user_memory_search, openviking_memory_commit, etc.) are available directly. Use when users ask to remember information, search past conversations, recall previous discussions, or work with documents.
always: true
---

# Memory System

A dual-approach memory system combining simple markdown files with optional semantic search via OpenViking.

## Core Layer (Always Available)

The foundational memory system that works without any dependencies:

### Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep-style tools or in-memory filters. Each entry starts with [YYYY-MM-DD HH:MM].

### Search Past Events

Choose the search method based on file size:

- Small `memory/HISTORY.md`: use `read_file`, then search in-memory
- Large or long-lived `memory/HISTORY.md`: use the `exec` tool for targeted search

Examples:
- **Linux/macOS:** `grep -i "keyword" memory/HISTORY.md`
- **Windows:** `findstr /i "keyword" memory\HISTORY.md`
- **Cross-platform Python:** `python -c "from pathlib import Path; text = Path('memory/HISTORY.md').read_text(encoding='utf-8'); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"`

Prefer targeted command-line search for large history files.

### When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

### Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this. When OpenViking is enabled, conversations are also committed to OpenViking during consolidation for semantic indexing.

---

## Enhanced Layer (OpenViking) — Native Integration

When OpenViking is enabled in config, you have **native tools** registered directly — no CLI scripts needed:

### Available Tools

| Tool | Purpose |
|------|---------|
| `user_memory_search` | Semantic search over user memories |
| `openviking_search` | Semantic search across all resources |
| `openviking_read` | Read content at 3 levels: abstract, overview, full |
| `openviking_list` | List resources in a path |
| `openviking_grep` | Regex search within resources |
| `openviking_glob` | Glob pattern matching |
| `openviking_memory_commit` | Commit messages for persistent memory |
| `openviking_add_resource` | Ingest files for semantic indexing |

### When to use OpenViking tools

- User explicitly requests semantic search or advanced recall
- Conversation contains important technical details worth structured storage
- User provides documents/files that need persistent context
- User asks "what did we discuss about X?" where grep might miss semantic connections

### When NOT to use OpenViking tools

- Simple fact storage (use MEMORY.md directly — it's faster)
- Quick grep searches (grep is sufficient for keyword lookup)
- User hasn't provided enough context to warrant structured storage

---

## OpenViking: Memory Recall

Use a **tiered approach** to minimize token usage:

### Step 1: Search (Find Relevant URIs)

```
user_memory_search(query="authentication flow")
```

Or search across all resources:

```
openviking_search(query="authentication flow", target_uri="viking://resources/")
```

### Step 2: Triage (Filter with Abstract)

For each result, get a ~100 token summary:

```
openviking_read(uri="viking://resources/docs/auth.md", level="abstract")
```

### Step 3: Full Content (Read)

When confirmed relevant, read the full content:

```
openviking_read(uri="viking://resources/docs/auth.md", level="read")
```

**Workflow: search → abstract → read (only relevant ones)**

---

## OpenViking: Conversation Storage

### Commit Messages

Use the `openviking_memory_commit` tool to persist important conversations:

```
openviking_memory_commit(messages=[
  {"role": "user", "content": "I prefer TypeScript..."},
  {"role": "assistant", "content": "I've noted your preference..."}
])
```

**When to commit:**
- Conversation reaches 8-10 turns
- User shares important information (preferences, decisions, technical details)
- User explicitly says "remember this" or similar
- Session ending signals ("thanks", "goodbye")

**Auto-commit:** Conversations are also automatically committed to OpenViking during session consolidation via hooks.

---

## OpenViking: File Ingestion

```
openviking_add_resource(local_path="/path/to/file.pdf", description="API documentation", wait=true)
```

Set `wait=true` so the content is immediately searchable after ingestion.

---

## Choosing the Right Approach

| Task | Use This |
|------|----------|
| Store simple fact | Edit MEMORY.md directly |
| Search for keyword | grep on HISTORY.md |
| Semantic search ("concepts related to X") | `user_memory_search` or `openviking_search` |
| Read resource details | `openviking_read` (abstract → overview → read) |
| Commit conversation to memory | `openviking_memory_commit` |
| Ingest user's documents | `openviking_add_resource` |
| Keyword search ("find 'deadline'") | grep HISTORY.md |

---

## URI Namespaces (OpenViking)

| Namespace | Contents |
|-----------|----------|
| `viking://resources/` | Ingested documents and data |
| `viking://user/{user_id}/memories/` | User preferences and context (auto-extracted from sessions) |
| `viking://agent/{agent_space}/memories/` | Agent-learned patterns (auto-extracted from sessions) |

---

## Important Notes

**Automatic context enrichment**: When OpenViking is enabled, related memories from past conversations are automatically injected into the system prompt based on the current message. This happens transparently — you'll see a "Semantic Memory" section in your context.

**Fallback**: If OpenViking is unavailable or fails, always fall back to the core layer (MEMORY.md + HISTORY.md + grep). The core layer is the foundation.

**CLI fallback**: The script `scripts/openviking_client.py` is still available as a CLI fallback via `exec`, but prefer the native tools when available.

---

## Reference

- Core layer: `memory/MEMORY.md` (facts), `memory/HISTORY.md` (events)
- OpenViking tools: `user_memory_search`, `openviking_read`, `openviking_search`, `openviking_memory_commit`, etc.
- OpenViking CLI (fallback): `scripts/openviking_client.py --help`
- URI scheme: `viking://resources/`, `viking://user/memories/`, `viking://agent/memories/`
