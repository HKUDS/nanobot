# Nanobot Knowledge Architecture: Current State and Vision

## 1. How Nanobot Manages Knowledge Today

### 1.1 Conversation Storage (JSONL Sessions)

Each conversation channel gets a single, ever-growing JSONL file stored in `~/.nanobot/sessions/`. Every message (user and assistant) is appended with a timestamp. The file is never pruned, rotated, or summarized.

However, the agent only ever sees the **last 50 messages** via a sliding window (`Session.get_history(max_messages=50)`). Messages beyond this window remain on disk but are never loaded, searched, or referenced by any process. The JSONL file is effectively an unbounded audit log with no practical use beyond the active window.

### 1.2 Memory System

Memory is the only persistence mechanism the agent actively uses. It consists of:

| Layer | File | Loaded | Retention |
|-------|------|--------|-----------|
| Long-term memory | `workspace/memory/MEMORY.md` | Every turn (system prompt) | Indefinite |
| Daily notes | `workspace/memory/YYYY-MM-DD.md` | Automatically for last 7 days | On disk forever, loaded for 7 days |

**Key characteristics:**
- Memory is written by the agent itself, using the `write_file` tool during conversation
- There is no automated summarization or extraction — the agent decides what to save based on what it currently sees (the 50-message window)
- The `MemoryStore` class has `append_today()` and `write_long_term()` methods, but these are **never called programmatically** — all memory writing goes through the generic `write_file` tool
- Daily notes older than 7 days still exist on disk and can be retrieved via `read_file` if the agent knows the date, but they are not automatically loaded

### 1.3 Context Assembly

The `ContextBuilder` assembles the full LLM prompt each turn:

1. **Core identity** — agent name, current time, OS, workspace path
2. **Bootstrap files** — `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md`
3. **Memory** — `MEMORY.md` + today's daily notes (always loaded)
4. **Recent memories** — last 7 days of daily notes
5. **Skills** — always-loaded skills get full content; others get a one-line summary
6. **Conversation history** — last 50 messages from JSONL session
7. **Current user message** — including any media attachments

### 1.4 What Gets Lost

The knowledge loss pattern is predictable:

- **After 50 messages**: Full conversational context (nuance, reasoning, back-and-forth) disappears from the LLM's view
- **After 7 days**: Daily notes stop being automatically loaded
- **Forever lost** (unless explicitly saved): Anything the agent didn't choose to write to memory while it was within the 50-message window

The JSONL file retains everything but offers no retrieval mechanism. It is, for all practical purposes, write-only storage.

### 1.5 Tools and Agents

- **Tools** are single-action Python classes (read file, execute command, search web). They have no reasoning capability — they execute exactly what they're told.
- **Subagents** are autonomous mini-agents spawned for background tasks. They have their own reasoning loop (up to 15 iterations), a limited tool set (no messaging, no spawning), and report results back to the main agent.
- **Skills** are markdown documents that teach the agent how to approach specific domains. They are knowledge, not executable code.

All tools are hardcoded as Python classes in `nanobot/agent/tools/`. There is no plugin system or way to add tools from the workspace without modifying the codebase. The skills system is the only modular, folder-based extension mechanism.

### 1.6 Provider Architecture

A single `LiteLLMProvider` instance is created at startup based on the configured model. Multiple providers can be configured (Anthropic, OpenRouter, DeepSeek, Ollama/vLLM, etc.), but there is no dynamic switching — the model is fixed for the session. Subagents share the same provider instance, though the code accepts a `model` parameter that could theoretically point to a different model.

---

## 2. Gaps and Limitations

1. **The JSONL file grows unbounded** with no practical use beyond 50 messages
2. **Memory is best-effort** — dependent on the agent deciding to save something while it's still in the window
3. **No topic organization** — memory is either a flat file (MEMORY.md) or date-indexed (daily notes), with no way to find things by subject
4. **No relationships** — no connections between concepts, people, decisions, or topics
5. **No retrieval** — no search, no semantic lookup, no way to find relevant knowledge on demand
6. **MEMORY.md doesn't scale** — it's loaded every turn, so it must stay concise
7. **Daily notes are date-anchored** — finding "what did we decide about authentication" requires knowing *when* it was discussed
8. **No automated extraction** — nothing processes old conversations to capture what the agent missed
9. **No model flexibility** — subagents can't use a cheaper/local model for background processing tasks

---

## 3. Vision: A Personal Knowledge Base

### 3.1 Filesystem-Based Knowledge Structure

Replace the flat memory system with a structured knowledge directory that the agent can navigate and maintain:

```
workspace/knowledge/
    INDEX.md              <- always loaded in system prompt, lightweight lookup table

    topics/
        docker.md
        authentication.md
        nanobot-architecture.md

    people/
        alice.md
        bob.md

    decisions/
        2024-03-use-litellm.md
        2025-01-switch-to-ollama.md

    facts/
        server-setup.md
        api-keys-location.md

    preferences/
        coding-style.md
        communication.md

    projects/
        nanobot-knowledge-base.md
        dashboard-redesign.md

    references/
        godel-escher-bach.md
        clean-architecture.md
```

**Why filesystem:**
- Transparent and debuggable — you can inspect everything with a text editor
- Version-controllable with git — full history of how knowledge evolves
- The agent already knows how to read and write files — no new tools required
- Each file is independently loadable — no monolithic database to manage
- Natural organization by category and topic

### 3.2 Entity File Format

Each knowledge file follows a consistent template with YAML frontmatter for metadata and relationships:

```markdown
---
type: decision
created: 2024-03-15
updated: 2024-06-01
related: [topics/nanobot-architecture, topics/agent-architecture]
tags: [architecture, providers, llm]
---
# Use LiteLLM as Provider Abstraction

## Context
Needed to support multiple LLM providers without per-provider code...

## Decision
Adopted LiteLLM because...

## Alternatives Considered
- Direct API calls: too much maintenance
- LangChain: too heavy

## Evolution
- 2024-06-01: Added gateway detection for OpenRouter
```

The `related` field creates a **lightweight relationship graph** — no database needed, just cross-references the agent can follow by reading linked files.

### 3.3 The Index

`INDEX.md` stays lean — one line per entry — and is loaded every turn so the agent always knows what knowledge is available:

```markdown
# Knowledge Index

## Topics
- docker: Container setup, compose configs, deployment patterns
- authentication: OAuth2 flow, token management

## People
- alice: Frontend lead, dashboard project

## Decisions
- 2024-03-use-litellm: Chose LiteLLM for multi-provider support
- 2025-01-switch-to-ollama: Local model for background tasks

## Preferences
- coding-style: Python, type hints, minimal dependencies
```

The agent scans this index, identifies relevant entries, and reads the full files on demand via `read_file`. This keeps token usage low while making the full knowledge base accessible.

### 3.4 Conversation Processing Pipeline

Address the JSONL dead-data problem by processing conversations before they fall off the window:

1. **Trigger** — cron job, message count threshold, or end-of-day schedule
2. **Subagent** (running on a local model like Ollama) reads the JSONL session file in chunks via a dedicated `session_reader` tool
3. **Extracts** topics, decisions, facts, preferences, people, projects, references
4. **Creates or updates** knowledge files in the appropriate categories
5. **Updates** `INDEX.md` with new entries
6. **Optionally truncates** the processed portion of the JSONL file

This requires two codebase changes:
- A `session_reader` tool that reads and chunks the JSONL without consuming LLM tokens on raw parsing
- Model routing so the subagent can use a local model (Ollama) instead of the main provider

### 3.5 Bootstrapping from Historical Conversations

Exported conversation history (e.g., from Claude.ai) can be processed through the same pipeline to populate the knowledge base from day one. This is a one-time operation — a script or subagent that:

1. Parses the exported JSON file
2. Chunks conversations by date or topic
3. Feeds them to a local model for extraction
4. Writes the resulting knowledge files

### 3.6 Temporal Evolution

Knowledge files can capture how understanding evolves over time:
- `updated` timestamp in frontmatter tracks when knowledge last changed
- Dated sections within files record how decisions or understanding shifted
- Git history provides full versioning if the workspace is a repository
- HISTORY.md serves as a grep-searchable chronological log alongside the topic-based knowledge

### 3.7 Upstream Memory Redesign (February 2025)

After this document was originally written, the upstream nanobot project redesigned its memory system:

- **Daily notes removed** — replaced by `HISTORY.md`, an append-only grep-searchable event log
- **Auto-consolidation** — when sessions exceed `memory_window` (default 50), old messages are automatically summarized by the LLM, appended to HISTORY.md, and extracted to MEMORY.md
- **Session trimming** — sessions are trimmed after consolidation, solving the unbounded JSONL growth problem

This change is complementary to the knowledge base. The upstream system handles the flat memory layer (MEMORY.md + HISTORY.md) while the knowledge base adds the structured, topic-organized layer on top.

### 3.8 Integration with Current Systems

The knowledge base works alongside, not replacing, existing mechanisms:

| Component | Role | Changes |
|-----------|------|---------|
| MEMORY.md | Quick-access critical facts | Stays, but can be leaner since knowledge/ handles depth |
| HISTORY.md | Grep-searchable event log | Auto-populated by consolidation; extractor can also append |
| JSONL sessions | Conversation history | Auto-trimmed by consolidation after memory_window |
| INDEX.md (new) | Knowledge directory loaded each turn | Replaces some of MEMORY.md's burden |
| Knowledge files (new) | Deep, structured, cross-referenced knowledge | Loaded on demand via read_file |
| Skills | Domain-specific instructions | A skill teaches the agent how to manage the knowledge base |
