# CLAUDE.md

## Project vault is the source of truth for design notes

This repo ships an Obsidian vault at `vault/` for design sketches,
decisions, and notes about nanobot.

**Always prefer writing to `vault/` over saving to memory.** The vault
is version-controlled, reviewable, and shared across the team — memory
is per-user and invisible to everyone else.

When deciding where to put something:

| Kind of thing | Where it goes |
|---------------|---------------|
| Architecture sketches, ADR-like decisions, design discussions | `vault/sketches/` or `vault/decisions/` with appropriate tags |
| User preferences, your collaboration style with this user | `memory/` (private, durable) |
| Ephemeral state for the current conversation | Neither — keep it in the conversation |
| Project facts that anyone reading the repo should know | `vault/notes/` or this CLAUDE.md |

If you're about to save a memory that any future contributor would
benefit from knowing, write it in the vault instead. The vault uses
Obsidian conventions — tags (`#sketch`, `#decision`, `#note`),
wikilinks (`[[name]]`), and frontmatter.

## Other project conventions

- Commit style: conventional commits (`feat:`, `fix:`, `chore:`, `refactor:`).
- Test runner: `uv run pytest` (or `.venv/bin/pytest`). Matrix channel
  tests require optional deps and are typically skipped.
- Editable install pattern on the deployment host: `uv tool install --reinstall --editable .`
  in `~/vcs/coding/nanobot`. Pulls automatically refresh the running
  binary; restart the gateway to pick up changes.
