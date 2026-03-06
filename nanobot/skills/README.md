# nanobot Skills

This directory contains built-in skills that extend nanobot's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, optional cron schedule, metadata)
- Markdown instructions for the agent

### Scheduled Skills

Add a `cron` field to frontmatter to auto-register the skill as a scheduled task:

```yaml
---
name: daily-report
description: Generate daily report
cron: "0 9 * * *"
---
```

The job will be registered at startup using the skill name (prevents duplicates).

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.

## Available Skills

| Skill | Description |
|-------|-------------|
| `clawhub` | Search and install skills from ClawHub registry |
| `cron` | Schedule reminders and recurring tasks |
| `dream` | Daily memory consolidation - backup, extract info, clean history |
| `github` | Interact with GitHub using the `gh` CLI |
| `memory` | Two-layer memory system with grep-based recall |
| `skill-creator` | Create new skills |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `weather` | Get weather info using wttr.in and Open-Meteo |