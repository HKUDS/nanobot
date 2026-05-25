# Nanobot Vault

An Obsidian vault for design sketches, decisions, and notes about the nanobot
project. Open this folder as a vault in Obsidian.

## Conventions

- **Tag every note.** At minimum one of: `#sketch`, `#decision`, `#note`, `#log`.
- **Wikilinks freely.** A `[[name]]` that points at a non-existent note is a
  prompt to write that note later, not an error.
- **No frontmatter dogma.** Use it when it helps; skip it when it doesn't.

## Layout

- `sketches/` — proposals and architectural ideas, not yet committed to.
- `decisions/` — settled choices (ADR-ish). Empty until we need it.
- `notes/` — looser captures, post-mortems, observations.

## Excluded from git

The `.obsidian/` directory (workspace state, plugin config) is per-user and
should be gitignored. Anything in `vault/private/` is also gitignored — use
that for drafts you don't want to publish yet.
