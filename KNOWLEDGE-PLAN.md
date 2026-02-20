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

## Phase 2: Knowledge Extraction During Consolidation

**Goal:** Extend the memory consolidation process to also extract structured knowledge entries.

### 2.1 Extend `_consolidate_memory()` in loop.py

**File:** `nanobot/agent/loop.py`

The existing consolidation prompt already processes old messages to produce a history entry and memory update. We extend it with a third output: `knowledge_entries` — a list of structured items to write to the knowledge base.

Each entry includes: category, filename, title, summary, content, and tags. The LLM decides what's worth extracting based on the conversation content and the current knowledge index (passed as context).

### 2.2 Add `_write_knowledge_entries()` helper

**File:** `nanobot/agent/loop.py`

A new method that takes the extracted entries and:
1. Creates or updates files in `workspace/knowledge/<category>/`
2. Adds YAML frontmatter (type, dates, tags)
3. Updates `INDEX.md` with new entries
4. Handles updates to existing entries (appends to Evolution section)

### Deliverable
Knowledge extraction runs automatically during memory consolidation. No separate tools or pipeline needed — it piggybacks on the existing process that already sees old messages before they're trimmed.

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

## Phase 4: Knowledge Extractor Skill

**Goal:** Document the automated knowledge extraction process for the agent and users.

### 4.1 Update the knowledge-extractor skill

**File:** `workspace/skills/knowledge-extractor/SKILL.md`

The skill now describes how knowledge extraction works during consolidation rather than as a separate pipeline. It explains:
- When extraction is triggered (session exceeds memory_window)
- What gets extracted (topics, people, decisions, facts, preferences, projects, references)
- How entries are formatted (following the knowledge skill conventions)
- Guidelines for what's worth extracting
- How to manually create entries outside of consolidation

### 4.2 No separate trigger needed

Knowledge extraction is automatic — it runs every time memory consolidation fires. No cron jobs, heartbeat tasks, or manual triggers required. The agent can also create entries manually during conversations.

### Deliverable
A documented, automated knowledge extraction process that runs alongside memory consolidation with zero manual intervention.

---

## Phase 5 (Future): Bootstrap from Claude.ai Export

**Goal:** Import historical Claude.ai conversations to populate the knowledge base from day one.

### 5.1 Parse the export format

Write a Python script (not a tool — this is a one-time operation) that:
1. Reads the Claude.ai JSON export file
2. Groups messages by conversation/date
3. Chunks conversations by date or topic
4. Feeds them to the LLM (or a local Ollama model) for extraction

### 5.2 Process through the same pipeline

Use the same extraction logic from Phase 4, but pointed at the imported data instead of live sessions. This ensures consistency — all knowledge follows the same format and conventions regardless of source.

### 5.3 Review and curate

After automated import, manually review `INDEX.md` and spot-check knowledge files. The initial import will likely need human curation to merge duplicates and correct misclassifications.

### Deliverable
Historical conversations become structured knowledge, giving the agent a rich starting context from day one.

---

## Implementation Order and Dependencies

```
Phase 1 (Knowledge structure + skill)     <- Small context.py tweak + workspace files
    |
Phase 2 (Extraction during consolidation) <- Extends _consolidate_memory() in loop.py
    |
Phase 3 (Local model for subagents)       <- Independent, requires spawn tool + subagent changes
    |
Phase 4 (Extractor skill docs)            <- Documents Phase 2, no code changes
    |
Phase 5 (Historical import)               <- One-time script
```

**Phases 1 and 2 are the core feature** — together they provide a structured knowledge base that populates automatically.

**Phase 3 is independent** and optional — useful for cost optimization but not required for knowledge extraction.

**Phase 4 is documentation only.**

**Phase 5 is a one-time operation** that can happen whenever desired.

---

## Estimated Effort

| Phase | Scope | Code Changes |
|-------|-------|-------------|
| 1 | Knowledge structure + skill | Minimal: one addition to `context.py`, new workspace files |
| 2 | Extraction during consolidation | Extend `_consolidate_memory()` prompt + new `_write_knowledge_entries()` (~80 lines) |
| 3 | Local model support | Modify `spawn.py` params, `subagent.py` provider logic (~100 lines) |
| 4 | Extractor skill docs | Workspace skill file only, no code changes |
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
