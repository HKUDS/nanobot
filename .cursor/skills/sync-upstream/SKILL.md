---
name: sync-upstream
description: Pulls upstream/main into origin/main and optionally into orghi-main. Use when syncing with upstream, bringing in new releases, or when the user asks to sync, pull upstream, or update from the original project.
---

# Sync Upstream Workflow

## Branch Descriptions

| Branch | Description |
|--------|-------------|
| **upstream/main** | The canonical source of the upstream project; mirrors official releases. |
| **origin/main** | A clean mirror of upstream/main for the fork; used to base PRs and track upstream changes. Do not commit directly. |
| **origin/orghi-main** | The personalized deployment branch with customizations and optional unmerged features; used to deploy and trigger updates. |

## PR Workflow

origin/main is a mirror; do not commit directly. To submit PRs upstream, create `feat/` branches from main:

```bash
git checkout main
git pull origin main
git checkout -b feat/my-feature
# implement, commit
git push origin feat/my-feature
# Open PR from origin/feat/my-feature to upstream/main
```

## Script

Run from repo root:

```bash
# Sync main only (rebase, tag)
.cursor/skills/sync-upstream/scripts/sync-upstream.sh

# Sync main and orghi-main (runs pytest first, merges if pass)
.cursor/skills/sync-upstream/scripts/sync-upstream.sh --orghi

# Preview without executing
.cursor/skills/sync-upstream/scripts/sync-upstream.sh --dry-run
.cursor/skills/sync-upstream/scripts/sync-upstream.sh --orghi --dry-run
```

**Flags:**
- `--orghi` - Run CI (pytest) on main, then merge into orghi-main and push. Aborts if tests fail.
- `--dry-run` - Print planned steps without executing.

**Behavior:**
- Uses rebase (not merge) to keep main identical to upstream
- Tags main as `orghi-sync-YYYYMMDD-HHMM` after each sync
- Pre-flight: aborts if uncommitted changes or missing upstream remote

## Branch Protection

Consider protecting origin/main on GitHub (Settings > Branches): require PRs, disallow force-push. Keeps main as a read-only mirror updated only via the sync workflow.

## Workflow: Manual Steps

### Step 1: Sync origin/main from upstream

```bash
git fetch upstream
git checkout main
git rebase upstream/main
git push --force-with-lease origin main
git tag orghi-sync-$(date +%Y%m%d-%H%M)
git push origin --tags
```

### Step 2 (Optional): Bring changes into orghi-main

```bash
uv run pytest  # CI gate - abort if fail
git checkout orghi-main
git merge main
# Resolve conflicts (typically in customized files)
git push origin orghi-main
```

## Conflict Resolution

When merging main into orghi-main, conflicts often occur in:
- `README.md` (branding, emoji)
- `nanobot/__init__.py` (version string, logo)
- `pyproject.toml` (version field)
- `workspace/` (personal config)

**Rules:**
- **Always accept upstream** for `nanobot/__init__.py` `__version__` only. Keep orghi-main `__logo__`. This keeps the fork aligned with upstream and makes it clear which upstream version you are on.
- Prefer keeping orghi-main customizations in `README.md`, `pyproject.toml`, and `workspace/`.
- Accept upstream changes for all other files.
