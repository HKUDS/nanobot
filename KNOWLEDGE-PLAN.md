# Implementation Plan: Personal Knowledge Base for Nanobot

## Overview

This plan builds a structured, filesystem-based personal knowledge base that the nanobot agent can populate, query, and maintain over time. It also introduces the ability to use a local model (Ollama) for background processing, and a pipeline to extract knowledge from both ongoing conversations and historical exports.

The work is broken into four phases, each delivering standalone value.

---

## Phase 1: Knowledge Base Structure and Skill

**Goal:** Establish the knowledge directory, index, and a skill that teaches the agent how to use it. No code changes required.

### 1.1 Create the knowledge directory structure

```
workspace/knowledge/
    INDEX.md
    topics/
    people/
    decisions/
    facts/
    preferences/
    projects/
    references/
```

Create empty subdirectories and a seed `INDEX.md`:

```markdown
# Knowledge Index

Last updated: YYYY-MM-DD

## Topics

## People

## Decisions

## Facts

## Preferences

## Projects

## References
```

### 1.2 Define the entity file template

Create `workspace/knowledge/TEMPLATE.md` as a reference:

```markdown
---
type: topic|person|decision|fact|preference|project|reference
created: YYYY-MM-DD
updated: YYYY-MM-DD
related: []
tags: []
---
# Title

## Summary
Brief description.

## Details
Full content.

## Evolution
- YYYY-MM-DD: Initial creation
```

### 1.3 Create a knowledge management skill

Create `workspace/skills/knowledge/SKILL.md`:

```markdown
---
name: knowledge
description: Manage the personal knowledge base
emoji: "brain"
always: false
---
# Knowledge Management

## Knowledge Base Location
The knowledge base is at `workspace/knowledge/`.

## Structure
- `INDEX.md` — master index, always loaded in context. Keep entries to one line each.
- Subdirectories by type: topics/, people/, decisions/, facts/, preferences/, projects/, references/
- Each entity is a markdown file with YAML frontmatter (type, created, updated, related, tags)

## When to Create Knowledge Entries
After meaningful conversations, create or update entries for:
- **Topics**: Subjects discussed in depth (technical, personal, professional)
- **People**: Individuals mentioned with context about who they are and their relevance
- **Decisions**: Choices made with rationale and alternatives considered
- **Facts**: Concrete information worth remembering (server IPs, configurations, account details)
- **Preferences**: User preferences for tools, styles, approaches, communication
- **Concepts**: Ideas, frameworks, or mental models explored
- **References**: Useful links, documentation, APIs
- **Insights**: Observations, patterns, or lessons learned

## How to Create an Entry
1. Choose the appropriate subdirectory based on type
2. Use a descriptive filename (kebab-case): `docker-compose-setup.md`
3. Include YAML frontmatter with type, created date, and related entries
4. Write concise but complete content
5. Update `INDEX.md` with a one-line summary

## How to Update an Entry
1. Read the existing file
2. Update the content and the `updated` field in frontmatter
3. Add a dated line to the Evolution section if the change is significant
4. Update `INDEX.md` if the summary changed

## Cross-References
Use the `related` field in frontmatter to link to other entries:
```yaml
related: [topics/docker, people/alice, decisions/2024-03-use-litellm]
```
When exploring a topic, follow related links to build fuller context.

## INDEX.md Rules
- One line per entry: `- filename: Brief summary`
- Grouped by type
- Keep it under 100 lines — this is loaded every turn
- If it grows too large, consider consolidating related entries
```

### 1.4 Update context builder to load INDEX.md

**File:** `nanobot/agent/context.py`

Modify `build_system_prompt()` to load `workspace/knowledge/INDEX.md` alongside memory context. This is a small code change — add the index content as a new section in the system prompt, similar to how memory is loaded.

```python
# In build_system_prompt(), after memory section:
index_path = self.workspace / "knowledge" / "INDEX.md"
if index_path.exists():
    index_content = index_path.read_text(encoding="utf-8")
    parts.append(f"# Knowledge Base\n\n{index_content}")
```

### 1.5 Update AGENTS.md

Add instructions telling the agent about the knowledge base and when to consult/update it.

### Deliverable
The agent can create, read, update, and cross-reference knowledge entries using existing `read_file` and `write_file` tools. The index is always visible. No new tools needed.

---

## Phase 2: Session Reader Tool

**Goal:** Build a tool that reads and chunks JSONL session files efficiently, so a subagent can process conversation history without wasting tokens on raw parsing.

### 2.1 Create the session_reader tool

**File:** `nanobot/agent/tools/session_reader.py`

```python
class SessionReaderTool(Tool):
    """Read and filter conversation history from session files."""

    name = "session_reader"
    description = "Read conversation messages from session files with filtering and chunking"
    parameters = {
        "type": "object",
        "properties": {
            "session_key": {
                "type": "string",
                "description": "Session key (channel:chat_id) or 'current' for active session"
            },
            "offset": {
                "type": "integer",
                "description": "Start reading from this message number (0-indexed)",
                "default": 0
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of messages to return",
                "default": 50
            },
            "roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter by role: ['user', 'assistant', 'tool']. Default: ['user', 'assistant']"
            },
            "date_from": {
                "type": "string",
                "description": "ISO date to start from (e.g. '2025-01-15')"
            },
            "date_to": {
                "type": "string",
                "description": "ISO date to end at (e.g. '2025-01-20')"
            },
            "stats_only": {
                "type": "boolean",
                "description": "Return only message count and date range, not content",
                "default": false
            }
        },
        "required": ["session_key"]
    }
```

**Capabilities:**
- Read messages by offset/limit (chunked pagination)
- Filter by role (skip tool call noise)
- Filter by date range
- Stats-only mode: return message count, date range, and size without content
- Strip tool call metadata, return clean user/assistant dialogue
- Return messages as formatted text, not raw JSON

### 2.2 Register the tool

**File:** `nanobot/agent/loop.py` — add to `_register_default_tools()`
**File:** `nanobot/agent/subagent.py` — add to subagent tool registry

### 2.3 Update TOOLS.md

Document the new tool with usage examples.

### Deliverable
The agent and subagents can read conversation history in manageable chunks, filter out noise, and get statistics about sessions — all without consuming tokens on JSONL parsing.

---

## Phase 3: Local Model Support for Subagents

**Goal:** Allow subagents to use a different LLM provider/model than the main agent, enabling Ollama or other local models for background processing.

### 3.1 Add model parameter to spawn tool

**File:** `nanobot/agent/tools/spawn.py`

Add an optional `model` parameter to the spawn tool's parameter schema:

```json
"model": {
    "type": "string",
    "description": "LLM model to use for this subagent (e.g. 'ollama/llama3'). Defaults to main agent model."
}
```

### 3.2 Multi-provider resolution in SubagentManager

**File:** `nanobot/agent/subagent.py`

Currently subagents share the main agent's `LLMProvider` instance. To support a different model/provider:

- Accept a `model` override in `spawn()`
- If the model belongs to a different provider (detected via keywords in `_match_provider()`), create a secondary `LiteLLMProvider` instance for that subagent
- If same provider, just pass the model override to `provider.chat(model=...)`

This requires access to the config to resolve provider credentials:

```python
async def spawn(self, task, label=None, model=None, ...):
    provider = self.provider
    effective_model = model or self.model

    if model and self._needs_different_provider(model):
        provider = self._create_provider_for_model(model)

    # Pass provider and model to _run_subagent
```

### 3.3 Configure Ollama in config.json

Add vLLM/Ollama provider configuration:

```json
{
    "providers": {
        "vllm": {
            "apiKey": "dummy",
            "apiBase": "http://localhost:11434/v1"
        }
    }
}
```

Ollama exposes an OpenAI-compatible API, so it works through the existing LiteLLM integration with the vLLM provider type.

### 3.4 Test with a simple subagent task

Verify: main agent (Claude) spawns subagent with `model="ollama/llama3"`, subagent reads a file, summarizes it, writes output.

### Deliverable
The main agent can spawn subagents that run on a local Ollama model, enabling cost-free background processing.

---

## Phase 4: Conversation Processing Pipeline

**Goal:** Automatically extract knowledge from conversations and populate the knowledge base.

### 4.1 Processing subagent task

Create a skill or template prompt that the main agent uses when spawning a conversation-processing subagent:

```
Read the session file for [session_key] using session_reader.
Start from message [offset], process in chunks of 50 messages.

For each chunk, extract:
- Topics discussed in depth
- Decisions made (with reasoning)
- Facts stated or discovered
- People mentioned (with context)
- Preferences expressed
- Insights or observations

For each extracted item:
1. Check if a knowledge entry already exists (read INDEX.md, then the relevant file)
2. If yes, update it with new information and set the updated date
3. If no, create a new file in the appropriate subdirectory with frontmatter
4. Update INDEX.md with any new entries

After processing, record the last processed message offset in
workspace/knowledge/.processing-state.json so the next run continues from there.
```

### 4.2 Processing state tracking

**File:** `workspace/knowledge/.processing-state.json`

```json
{
    "sessions": {
        "telegram:12345": {
            "last_offset": 250,
            "last_processed": "2025-02-12T10:30:00",
            "total_messages": 300
        }
    }
}
```

This allows incremental processing — each run picks up where the last one left off.

### 4.3 Trigger mechanisms

Three options, all using existing infrastructure:

**A. Cron-based (recommended to start):**
Add a heartbeat task or cron job that triggers processing daily or every N hours.

**B. Threshold-based:**
Modify `SessionManager.save()` to check message count and auto-trigger when messages exceed a threshold (e.g., every 100 new messages).

**C. Manual:**
The user asks the agent to process conversations. Simplest, no automation needed.

### 4.4 JSONL management after processing

**Note:** Upstream now handles session trimming automatically via auto-consolidation (when session exceeds `memory_window`, old messages are summarized into HISTORY.md and the session is trimmed). The knowledge extractor is complementary — it extracts *structured* knowledge that auto-consolidation doesn't capture.

The session_reader tool remains useful for initial bootstrapping (processing existing history before auto-consolidation was active) and for deeper re-processing when needed.

### Deliverable
A pipeline that processes conversation history into structured knowledge entries, runs on a local model, and can be triggered automatically or manually.

---

## Phase 5 (Future): Bootstrap from Claude.ai Export

**Goal:** Import historical Claude.ai conversations to populate the knowledge base from day one.

### 5.1 Parse the export format

Write a Python script (not a tool — this is a one-time operation) that:
1. Reads the Claude.ai JSON export file
2. Groups messages by conversation/date
3. Writes them as temporary files in a format the session_reader tool can process
4. Or directly chunks and feeds them to Ollama via the LiteLLM provider

### 5.2 Process through the same pipeline

Use the same extraction logic from Phase 4, but pointed at the imported data instead of live sessions. This ensures consistency — all knowledge follows the same format and conventions regardless of source.

### 5.3 Review and curate

After automated import, manually review `INDEX.md` and spot-check knowledge files. The initial import will likely need human curation to merge duplicates and correct misclassifications.

### Deliverable
Historical conversations become structured knowledge, giving the agent a rich starting context from day one.

---

## Implementation Order and Dependencies

```
Phase 1 (Knowledge structure + skill)     <- No code changes needed (except small context.py tweak)
    |
Phase 2 (Session reader tool)             <- Requires Python tool class + registration
    |
Phase 3 (Local model for subagents)       <- Requires spawn tool + subagent changes
    |
Phase 4 (Processing pipeline)             <- Uses Phase 2 tool + Phase 3 local model
    |
Phase 5 (Historical import)               <- Uses Phase 4 pipeline
```

**Phase 1 can be done immediately** and provides value on its own — the agent can start building knowledge manually.

**Phases 2 and 3 are independent** of each other and can be done in parallel.

**Phase 4 combines them** into the automated pipeline.

**Phase 5 is a one-time operation** that can happen whenever the pipeline is ready.

---

## Estimated Effort

| Phase | Scope | Code Changes |
|-------|-------|-------------|
| 1 | Knowledge structure + skill | Minimal: one addition to `context.py`, new workspace files |
| 2 | Session reader tool | New tool class (~150 lines), registration in 2 files |
| 3 | Local model support | Modify `spawn.py` params, `subagent.py` provider logic (~100 lines) |
| 4 | Processing pipeline | Skill/prompt template, state tracking, trigger setup |
| 5 | Historical import | One-time script (~200 lines) |

---

## Risk and Mitigation

| Risk | Mitigation |
|------|-----------|
| INDEX.md grows too large for system prompt | Monitor line count; split by category if over 100 lines |
| Knowledge extraction quality varies by model | Start with manual review; refine prompts iteratively |
| Ollama model too weak for good extraction | Test with different models; use larger local models if available |
| Duplicate/conflicting knowledge entries | Cross-reference check before creating; merge skill in instructions |
| Processing pipeline corrupts existing knowledge | Keep JSONL as backup; git-track the workspace for rollback |
