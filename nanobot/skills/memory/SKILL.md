---
name: memory
description: Search past conversations in the agent's history log.
---

# Memory

## Search Past Events

Search the exact `History log` path from the system prompt using an available text-search
tool. This path belongs to the agent workspace, which can differ from the current project.

The append-only JSONL log stores `cursor`, `timestamp`, and `content` per entry. Retrieve
entries on demand by topic or date, and inspect neighboring entries when context matters.
