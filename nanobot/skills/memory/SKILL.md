---
name: memory
description: Two-layer memory system with Dream-managed knowledge files.
always: true
---

# Memory

## Structure

- `SOUL.md` — Bot personality and communication style. **Managed by Dream.** Do NOT edit.
- `USER.md` — User profile and preferences. **Managed by Dream.** Do NOT edit.
- `memory/MEMORY.md` — Long-term facts (project context, important events). **Managed by Dream.** Do NOT edit.
- `memory/history.jsonl` — append-only JSONL, not loaded into context. Prefer the built-in `grep` tool to search it.

## Search Past Events

`memory/history.jsonl` is JSONL format — each line is a JSON object with `cursor`, `timestamp`, `content`.

- For broad searches, start with `grep(..., path="memory", glob="*.jsonl", output_mode="count")` or the default `files_with_matches` mode before expanding to full content
- Use `output_mode="content"` plus `context_before` / `context_after` when you need the exact matching lines
- Use `fixed_strings=true` for literal timestamps or JSON fragments
- Use `head_limit` / `offset` to page through long histories
- Use `exec` only as a last-resort fallback when the built-in search cannot express what you need

Examples (replace `keyword`):
- `grep(pattern="keyword", path="memory/history.jsonl", case_insensitive=true)`
- `grep(pattern="2026-04-02 10:00", path="memory/history.jsonl", fixed_strings=true)`
- `grep(pattern="keyword", path="memory", glob="*.jsonl", output_mode="count", case_insensitive=true)`
- `grep(pattern="oauth|token", path="memory", glob="*.jsonl", output_mode="content", case_insensitive=true)`

## Important

- **Do NOT edit SOUL.md, USER.md, or MEMORY.md.** They are automatically managed by Dream.
- If you notice outdated information, it will be corrected when Dream runs next.
- Users can view Dream's activity with the `/dream-log` command.

## Semantic Memory Integration

The semantic layer is optional and additive. It does not replace Dream-managed files or `memory/history.jsonl`; it augments them when enabled in config.

### What It Adds

- Native semantic search over user memories and indexed resources
- Persistent resource ingestion for user-provided files
- Optional conversation commit into semantic memory
- Automatic user-profile enrichment in the system prompt when available
- Automatic skill-memory injection after reading a `SKILL.md` file when matching skill memory exists

### Native Tools

When semantic memory is enabled, these tools may be available directly:

| Tool | Purpose |
|------|---------|
| `user_memory_search` | Semantic search over user memories |
| `openviking_search` | Semantic search across indexed resources |
| `openviking_read` | Read resource content at `abstract`, `overview`, or `read` level |
| `openviking_list` | List resources under a URI |
| `openviking_grep` | Regex search within indexed resources |
| `openviking_glob` | Glob-match indexed resources |
| `openviking_memory_commit` | Commit conversation messages into semantic memory |
| `openviking_add_resource` | Ingest a local file for semantic indexing |

### Runtime Behavior

- The core layer remains the default: use Dream-managed files plus `memory/history.jsonl` first for exact facts and keyword recall
- If semantic memory is enabled, the agent may load a user profile from semantic memory into the system prompt
- If a `SKILL.md` file is read, the runtime may append a `## Skill Memory` block from semantic memory for that skill
- During message compaction, session messages may be committed automatically into semantic memory

### When To Use The Semantic Layer

- The user asks what was discussed previously, but exact keyword search may miss related concepts
- The user provides documents or files that should remain searchable later
- You need concept-level recall instead of exact string matching
- You want to retrieve indexed resources without loading full file contents immediately

### Recommended Workflow

1. Start with `user_memory_search(...)` or `openviking_search(...)`
2. Triage candidates with `openviking_read(..., level="abstract")`
3. Read full content only for relevant results with `openviking_read(..., level="read")`
4. Use `openviking_add_resource(..., wait=true)` for new user documents when they should become searchable immediately
5. Use `openviking_memory_commit(...)` only when the conversation itself should become persistent semantic memory

Examples:
- `user_memory_search(query="authentication flow")`
- `openviking_search(query="authentication flow", target_uri="viking://resources/")`
- `openviking_read(uri="viking://resources/docs/auth.md", level="abstract")`
- `openviking_read(uri="viking://resources/docs/auth.md", level="read")`
- `openviking_add_resource(local_path="/path/to/file.pdf", description="API documentation", wait=true)`

### Fallback

- If semantic memory is unavailable, use the core layer only: Dream-managed files plus `memory/history.jsonl`
- For exact keyword lookup, prefer built-in `grep` on `memory/history.jsonl` even when semantic memory is enabled
