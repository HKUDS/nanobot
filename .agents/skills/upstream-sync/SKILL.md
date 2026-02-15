---
name: upstream-sync
description: Use when the user asks to check for new features from the upstream HKUDS/nanobot repository, sync changes, or bring in upstream commits and PRs selectively.
---

# Upstream Sync

Selectively bring features from the upstream `HKUDS/nanobot` repository into this fork.

## Workflow

### 1. Determine the Last Sync Point

Read `UPSTREAM_SYNC.md` in the project root. The topmost entry records the latest upstream commit SHA that was reviewed. If the file does not exist, use the merge-base between `origin/main` and `upstream/main` as the starting point:

```bash
git merge-base origin/main upstream/main
```

### 2. Fetch Upstream and Gather Changes

```bash
git fetch upstream
git log --oneline --first-parent <last-sync-sha>..upstream/main
```

Also check merged PRs via GitHub CLI for richer context:

```bash
gh pr list --repo HKUDS/nanobot --state merged --search "merged:>YYYY-MM-DD" --limit 100 --json number,title,body,mergedAt,mergeCommit
```

Use the date of the last sync commit to filter. If `gh` is unavailable, rely on `git log` alone.

### 3. Build the Feature List

Group commits by logical feature or PR. For each item, present:

- **PR number and title** (or commit range if no PR)
- **One-line summary** of what it does
- **Risk assessment**: low (isolated change), medium (touches shared code), high (architectural, likely conflicts)

### 4. Present Choices to the User

Ask the user to select which features to bring in and which to skip. Use the question tool with `multiple: true` so the user can select several at once. Include a brief description for each option.

### 5. Apply Selected Features

For each selected feature, in order from oldest to newest:

1. Create a working branch if not already on one
2. Attempt `git cherry-pick` for single commits, or `git cherry-pick <range>` for multi-commit PRs
3. If conflicts arise:
   - Show the user what conflicted and why
   - Ask how to proceed (resolve, skip, or abort)
   - Resolve conflicts as directed
4. Run a quick sanity check after each feature (linting, tests if fast)
5. Mark the feature as done in the todo list

If cherry-pick is not clean (e.g., too many interleaved changes), fall back to manually applying the diff:

```bash
git diff <parent>..<commit> -- <relevant-files> | git apply --3way
```

### 6. Update the Sync Log

After all selected features are applied (or skipped), update `UPSTREAM_SYNC.md` in the project root.

Add a new entry **at the top** of the file with:

```markdown
## YYYY-MM-DD

**Upstream HEAD reviewed:** `<sha>` (on branch `main`)

### Brought in
- PR #NNN: Title - brief description
- PR #NNN: Title - brief description

### Skipped
- PR #NNN: Title - reason for skipping
```

The upstream HEAD reviewed should be the latest commit on `upstream/main` at the time of the sync, regardless of which features were selected. This ensures the next sync starts from the right point.

### 7. Commit the Sync

Commit `UPSTREAM_SYNC.md` along with all cherry-picked changes. Use a commit message like:

```
feat: sync upstream features (YYYY-MM-DD)

Brought in: PR #X, PR #Y, PR #Z
Skipped: PR #A, PR #B
```

## Important Notes

- **Never force-push** or rebase the main branch.
- **Overlapping changes**: Some local commits may implement the same feature as upstream. When this happens, note it in the sync log as "Already implemented locally" and skip.
- **Ask questions** when conflicts are complex or when architectural decisions are needed about how divergent code should merge.
- The upstream remote is already configured as `upstream` pointing to `git@github.com:HKUDS/nanobot.git`.
- The fork's origin is `git@github.com:kumekay/nanobot.git`.

## File Locations

- Sync log: `UPSTREAM_SYNC.md` (project root)
- This skill: `.agents/skills/upstream-sync/SKILL.md`
