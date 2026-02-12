---
name: knowledge-extractor
description: Extract knowledge from conversation history and populate the knowledge base.
metadata: {"nanobot":{"emoji":"🔍"}}
---

# Knowledge Extractor

This skill is used to process conversation history and extract structured knowledge into the knowledge base.
It is typically run as a subagent task spawned by the main agent.

## Overview

The knowledge base at `workspace/knowledge/` stores structured information extracted from conversations.
This skill describes how to process conversation history (via the `session_reader` tool) and create or update knowledge entries.

## Processing Workflow

### Step 1: Check processing state

Read the processing state file to know where to resume:
```
read_file(path="workspace/knowledge/.processing-state.json")
```

If the file doesn't exist, start from offset 0.

### Step 2: Get session stats

```
session_reader(action="stats", session_key="<key>")
```

This tells you total message count so you know how much work there is.

### Step 3: Read a chunk of messages

```
session_reader(action="read", session_key="<key>", offset=<last_offset>, limit=50)
```

Process in chunks of 50 messages. Only user and assistant messages are included by default (tool calls are filtered out).

### Step 4: Extract knowledge

For each chunk, identify:

- **Topics**: Subjects discussed in depth (includes concepts, ideas, frameworks)
- **People**: Individuals mentioned with meaningful context
- **Decisions**: Choices made with reasoning, insights, or lessons learned
- **Facts**: Concrete, stable information (configurations, setups, accounts)
- **Preferences**: User preferences for tools, styles, approaches
- **Projects**: Ongoing work spanning multiple entities
- **References**: Books, articles, laws, theorems, films, music, art, websites

### Step 5: Check existing entries

Read `workspace/knowledge/INDEX.md` to see what already exists.
If an entry already exists for a topic, read the full file and update it rather than creating a duplicate.

### Step 6: Create or update entries

For new entries:
1. Create the file in the appropriate subdirectory with YAML frontmatter
2. Use kebab-case filenames: `docker-compose-setup.md`
3. Include `type`, `created`, `updated`, `related`, and `tags` in frontmatter
4. Add a one-line summary to `INDEX.md`

For existing entries:
1. Read the current file
2. Merge new information
3. Update the `updated` date
4. Add a dated line to the Evolution section
5. Update cross-references in `related` field
6. Update `INDEX.md` summary if changed

### Step 7: Update processing state

After processing each chunk, update the state file:
```
write_file(path="workspace/knowledge/.processing-state.json", content=<updated_state>)
```

### Step 8: Continue or stop

If there are more messages to process (remaining > 0), continue with the next chunk.
If done, provide a summary of what was extracted.

## Processing State Format

```json
{
  "sessions": {
    "telegram:12345": {
      "last_offset": 150,
      "last_processed": "2025-02-12T10:30:00",
      "total_at_last_run": 300
    }
  }
}
```

## Entry File Format

```markdown
---
type: topic
created: 2025-01-15
updated: 2025-02-10
related: [people/alice, decisions/2024-03-use-litellm]
tags: [architecture, backend]
---
# Authentication System

## Summary
OAuth2-based auth with JWT tokens...

## Details
Full content here.

## Evolution
- 2025-01-15: Initial design discussion
- 2025-02-10: Switched from session cookies to JWT
```

## Guidelines

- Be selective: not every message contains knowledge worth extracting
- Merge related information into single, comprehensive entries
- Prefer updating existing entries over creating near-duplicates
- Keep INDEX.md entries to one line each
- Cross-reference related entries using the `related` field
- Include timestamps in the Evolution section for significant changes
- When in doubt about categorization, prefer `topics/` as the default
- Facts should be concrete and verifiable (server IPs, versions, configs)
- Preferences capture how the user likes things done, not what they discussed

## Spawning This Task

The main agent can trigger processing by spawning a subagent:

```
spawn(task="Process conversation history for session telegram:12345. Read the knowledge-extractor skill at workspace/skills/knowledge-extractor/SKILL.md and follow the workflow to extract knowledge from unprocessed messages.", label="knowledge extraction")
```
