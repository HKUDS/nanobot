# How AI Agent Memory Works in nanobot

This guide explains how to use nanobot's long-term AI agent memory: session history, compressed archives, durable memory files, Dream consolidation, and Git-backed memory changes.

## What you will build

- a workspace with persistent session history
- compressed history archives for older turns
- durable memory files such as `USER.md` and `MEMORY.md`
- a Dream workflow for curating long-term memory

## When to use this

Use memory when an agent should remember stable preferences, project facts, decisions, and recurring context across sessions. Do not use memory as a dumping ground for every raw transcript; nanobot separates short-term messages from curated durable knowledge.

## Before you start

Use an installation with a configured model that has already returned a reply. If this is your first setup, follow [Quick Start](../quick-start.md), then return here. Existing WebUI users can continue in the current instance.

## Minimal working example

In your existing chat, send a specific preference, such as “For Acme release notes, use concise bullet points.” Then send these commands one at a time, waiting for each to finish:

```text
/compact
/dream
/dream-log
```

Compaction puts recent conversation into the archive Dream reads. Dream then decides what to save; inspect its changes to confirm the preference reached `USER.md` or `memory/MEMORY.md`. Ask the agent to read the saved preference, then check it in a new chat. For corrections and restoration, follow [Save and Check a Preference](../memory.md#save-and-check-a-preference).

The files live in the configured agent workspace, normally `~/.nanobot/workspace/`. Selecting a project or starting a new topic does not move or isolate this memory.

## Production notes

- Use separate configured instances when projects or clients need separate memory.
- Keep durable facts concise; old session details belong in `history.jsonl`.
- Use `/dream-prompt init` when a workspace needs custom memory guidance.
- Review Git-backed memory changes when memory affects important workflows.

## Security notes

- Memory files may contain sensitive user or project facts.
- Avoid sharing workspaces without reviewing `SOUL.md`, `USER.md`, and `memory/MEMORY.md`.
- Use separate workspaces for personal and team contexts.

## Troubleshooting

- If a recent preference is missing, run `/compact`, wait for completion, then run `/dream` and inspect `/dream-log`.
- If memory changed incorrectly, use `/dream-restore` to inspect and restore previous versions.
- If a new session lacks context, confirm the fact was saved and it uses the same configured agent workspace.

## Related nanobot docs

- [AI Agent Memory in nanobot](../memory.md)
- [Concepts](../concepts.md)
- [Configuration](../configuration.md#auto-compact)
- [Chat Commands](../chat-commands.md)
