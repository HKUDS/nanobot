---
name: dream
description: Daily memory consolidation - backup memory, extract important info to MEMORY.md, clean old history.
cron: "0 2 * * *"
metadata: {"nanobot":{"emoji":"🌙"}}
---

# Dream - Memory Consolidation Skill

## Purpose

Mimics human sleep dreaming to consolidate memories:
- Backup current memory files
- Extract important information from recent HISTORY to MEMORY.md
- Clean up old history entries (keep 7 days)
- Review and prune MEMORY.md to prevent bloat
- Push a brief summary to notification channel

## Schedule

Runs automatically at 2:00 AM daily via cron.

## How It Works

Agent executes the consolidation workflow:
1. Backup MEMORY.md and HISTORY.md to `memory/backups/`
2. Analyze last 7 days of HISTORY.md
3. Extract important info to MEMORY.md (see guidelines below)
4. **Review MEMORY.md and remove outdated/temporary info**
5. Clean up old HISTORY entries (keep 7 days)
6. Send brief summary to notification channel

## What Belongs in MEMORY.md (Long-term Memory)

- User identity (name, contact info, relationships)
- Stable preferences (communication style, language, timezone)
- API keys and credentials
- Server/infrastructure configuration
- Active skills and their cron job IDs
- Known bugs with workarounds
- Ongoing project references (repo URLs, not detailed notes)

## What Does NOT Belong in MEMORY.md

- Debugging session notes (temporary, will become stale)
- PR/code review details (track in GitHub, not memory)
- Research notes on libraries/tools (temporary exploration)
- Step-by-step procedures (belongs in SKILL.md)
- Repeated information (deduplicate first)
- Time-sensitive info (dates, versions that will expire)

## MEMORY.md Maintenance Rules

1. **One line per fact**: Avoid multi-paragraph explanations
2. **No duplication**: If info exists, don't add it again
3. **Prune outdated info**: Remove anything no longer relevant
4. **Reference, don't copy**: Link to SKILL.md for detailed procedures
5. **Review monthly**: Check if accumulated info is still needed
