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
- `--orghi` - Run CI (pytest) on main, merge into orghi-main, run orghi tests, then push. Aborts if main or orghi tests fail.
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
# If conflicts: resolve, run orghi tests, commit, push (see Conflict Resolution below)
uv run pytest tests/orghi -v  # Orghi tests - must pass before push
git push origin orghi-main
```

## Conflict Resolution

When merging main into orghi-main, conflicts often occur in:
- `README.md` (branding, emoji)
- `nanobot/__init__.py` (version string, logo)
- `pyproject.toml` (version field)
- `workspace/` (personal config)

**File rules:**
- **Always accept upstream** for `nanobot/__init__.py` `__version__` only. Keep orghi-main `__logo__`. This keeps the fork aligned with upstream and makes it clear which upstream version you are on.
- Prefer keeping orghi-main customizations in `README.md`, `pyproject.toml`, and `workspace/`.
- Accept upstream changes for all other files.

**Orghi tests:** Custom orghi features are tested in `tests/orghi/` (separate from upstream `tests/`). Run: `uv run pytest tests/orghi -v`. Must pass before push. They validate these custom features: (last updated: 2026-02-24)
- Telegram send_only mode.

**Agent workflow** when merge produces conflicts or orghi tests fail:

1. **Resolve conflicts** in the conflicted files using the file rules above.
2. **Run orghi tests**: `uv run pytest tests/orghi -v`
3. **If tests fail** (retry up to 3 times):
   - **Never** change or relax tests to make them pass. Tests encode intended orghi behavior.
   - **Understand** the failing test and the orghi feature intent (e.g. send_only for cron jobs).
   - **Fix** the feature code (e.g. `nanobot/channels/manager.py`, `nanobot/channels/telegram.py`) so it correctly integrates with upstream. Resolutions must be robust.
   - Re-run orghi tests. If pass, commit and push.
4. **After 3 failed attempts**: Stop. Report to user: which tests fail, what was tried, that manual review is needed. Do not modify tests.

**Intent preservation**: The agent must never weaken tests to pass. The goal is to ensure the orghi custom feature is correctly merged with upstream changes. If upstream refactored or removed code that orghi depends on, the agent must adapt the orghi feature to the new upstream structure while preserving intent.
