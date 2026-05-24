# Nanobot CLI Apps

This directory contains nanobot-owned CLI App catalog entries and optional
workspace skills.

The runtime treats it as a repo-level plugin catalog, not as Python package
code:

- Source checkouts read `plugins/cli-apps/catalog/*.json` directly.
- Packaged installs fetch the latest catalog from GitHub and cache it under
  nanobot's runtime data directory.
- CLI-Anything registries remain the upstream source for general community CLI
  entries; this directory is only for curated nanobot additions.

To add an official CLI App, add one JSON file under `catalog/` and, when useful,
one `SKILL.md` under `skills/<name>/`. No Python edit is needed unless the app
requires a new install strategy.

Do not vendor third-party packages, binaries, or logo files here. Catalog rows
may reference public package names and public logo URLs for identification.
