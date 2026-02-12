---
name: knowledge-extractor
description: Extract knowledge from conversation history and populate the knowledge base, memory, and history log.
metadata: {"nanobot":{"emoji":"🔍"}}
---

# Knowledge Extractor

Process conversation history and extract structured information into three outputs:
- **Knowledge base** (`workspace/knowledge/`) — structured, topic-organized entries
- **Long-term memory** (`workspace/memory/MEMORY.md`) — critical quick-access facts
- **History log** (`workspace/memory/HISTORY.md`) — append-only, grep-searchable event log

This skill is typically run as a subagent task spawned by the main agent.

## Prerequisites

Before extracting knowledge, read the knowledge management skill for conventions on file format, categories, and cross-references:
```
read_file(path="workspace/skills/knowledge/SKILL.md")
```

All knowledge entries must follow the conventions defined there.

## Processing Workflow

### Step 1: Read prerequisites

Read the knowledge skill to understand entry format and categories:
```
read_file(path="workspace/skills/knowledge/SKILL.md")
```

### Step 2: Check processing state

Read the processing state file to know where to resume:
```
read_file(path="workspace/knowledge/.processing-state.json")
```

If the file doesn't exist or the session is not listed, start from offset 0.

### Step 3: Get session stats

```
session_reader(action="stats", session_key="<key>")
```

This tells you total message count so you know how much to process.

### Step 4: Read a chunk of messages

```
session_reader(action="read", session_key="<key>", offset=<last_offset>, limit=50)
```

Process in chunks of 50 messages. Only user and assistant messages are included by default.

### Step 5: Extract and write

For each chunk, extract information and write to the appropriate outputs:

**Knowledge base entries** — for topics, people, decisions, facts, preferences, projects, and references that deserve structured, standalone entries. Follow the conventions in the knowledge skill.

Before creating a new entry:
1. Read `workspace/knowledge/INDEX.md` to check if an entry already exists
2. If it does, read the full file and update it rather than creating a duplicate
3. After creating or updating, update `INDEX.md`

**Long-term memory** — for critical facts the agent should always have quick access to:
- User identity and context (name, role, location, timezone)
- Key configuration details (server IPs, account names, API endpoints)
- Standing instructions or preferences that apply broadly
- Append to or update `workspace/memory/MEMORY.md`
- Keep this file concise — it's loaded every turn

**History log** — for timestamped event summaries (grep-searchable):
- Key conversations and their outcomes
- Tasks completed or started
- Decisions made with context
- Append to `workspace/memory/HISTORY.md`
- Each entry starts with a timestamp: `[YYYY-MM-DD HH:MM]`
- Include enough detail to be useful when found by grep later

### Step 6: Update processing state

After processing each chunk, update the state file:
```
write_file(path="workspace/knowledge/.processing-state.json", content=<updated_state>)
```

State format:
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

### Step 7: Continue or stop

If there are more messages to process (remaining > 0), continue with the next chunk.
If done, provide a summary of what was extracted.

## Guidelines

- Be selective: not every message contains knowledge worth extracting
- Merge related information into single, comprehensive entries
- Prefer updating existing entries over creating near-duplicates
- Don't duplicate information across outputs — use the right one:
  - Knowledge base for structured, topic-organized, long-lived information
  - MEMORY.md for facts the agent needs every turn (keep it small)
  - HISTORY.md for chronological, grep-searchable event log
- When in doubt about knowledge category, prefer `topics/` as the default

## Spawning This Task

The main agent can trigger processing by spawning a subagent:

```
spawn(task="Process conversation history for session <session_key>. Read the knowledge-extractor skill at workspace/skills/knowledge-extractor/SKILL.md and follow the workflow.", label="knowledge extraction")
```
