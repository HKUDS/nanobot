# Nanobot Vault

An Obsidian vault for design sketches, decisions, and notes about the nanobot
project. Open this folder as a vault in Obsidian.

## Conventions

- **Flat layout.** All notes live at the vault root. Do not create
  subfolders to organize notes — organization is by tag, not folder.
- **Tag every note** with at least one of:
  - `#sketch` — proposals / architectural ideas not yet committed to.
  - `#decision` — settled choices (ADR-ish).
  - `#daily` — daily notes; filename is `YYYY-MM-DD.md` per Obsidian's
    daily-note convention. Pair with `#log` when it captures historical
    record (end-of-day snapshot, post-mortem).
  - `#note` — anything else (loose captures, observations, references).
- **Wikilinks freely.** A `[[name]]` that points at a non-existent note is a
  prompt to write that note later, not an error.
- **No frontmatter dogma.** Use it when it helps; skip it when it doesn't.
- **Filenames are unique vault-wide.** Required for clean wikilinks in a
  flat layout. Use kebab-case for non-daily notes.

## Excluded from git

The `.obsidian/` directory (workspace state, plugin config) is per-user and
should be gitignored. Anything in a top-level `private/` folder is also
gitignored — use that for drafts you don't want to publish yet.
