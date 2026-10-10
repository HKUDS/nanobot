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

## Learned Workflows

Dream may save generalized workflows from successful multi-step tasks to
`memory/SKILLS.jsonl`. Relevant entries appear in the system prompt as "Learned Skills";
adapt their steps to the current request. Dream uses `save_learned_skill` to validate and
deduplicate these records. Full `skills/<name>/SKILL.md` files remain separate.
