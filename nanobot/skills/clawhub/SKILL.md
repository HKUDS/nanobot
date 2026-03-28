---
name: clawhub
description: Search and install agent skills from ClawHub, the public skill registry.
homepage: https://clawhub.ai
metadata: {"nanobot":{"emoji":"🦞"}}
---

# ClawHub

Public skill registry for AI agents. Search by natural language (vector search).

## When to use

Use this skill when the user asks any of:
- "find a skill for …"
- "search for skills"
- "install a skill"
- "what skills are available?"
- "update my skills"

## Find workspace path

Before install/update, you MUST determine the correct workspace path. Check the config file:

```bash
cat ~/.nanobot/config.json | grep -A2 '"workspace"'
```

Or use the configured workspace path (default: `~/.nanobot/workspace`). Store it in a variable for reuse.

## Search

```bash
npx --yes clawhub@latest search "<query>" --limit 5
```

## Install

```bash
WORKSPACE=$(cat ~/.nanobot/config.json | grep -oP '"workspace"\s*:\s*"\K[^"]+' || echo "$HOME/.nanobot/workspace")
npx --yes clawhub@latest install <slug> --workdir "$WORKSPACE"
```

Replace `<slug>` with the skill name from search results. This places the skill into `<workspace>/skills/`, where nanobot loads workspace skills from.

## Update

```bash
WORKSPACE=$(cat ~/.nanobot/config.json | grep -oP '"workspace"\s*:\s*"\K[^"]+' || echo "$HOME/.nanobot/workspace")
npx --yes clawhub@latest update --all --workdir "$WORKSPACE"
```

## List installed

```bash
WORKSPACE=$(cat ~/.nanobot/config.json | grep -oP '"workspace"\s*:\s*"\K[^"]+' || echo "$HOME/.nanobot/workspace")
npx --yes clawhub@latest list --workdir "$WORKSPACE"
```

## Notes

- Requires Node.js (`npx` comes with it).
- No API key needed for search and install.
- Login (`npx --yes clawhub@latest login`) is only required for publishing.
- **Always use `--workdir` pointing to your configured workspace** — without it, skills install to the current directory instead of the nanobot workspace.
- After install, remind the user to start a new session to load the skill.
