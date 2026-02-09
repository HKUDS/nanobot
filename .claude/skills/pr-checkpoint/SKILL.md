---
name: pr-checkpoint
description: Create a PR checkpoint for supervisor review. Use at phase boundaries, after ~15 tasks, or when you've made significant progress that should be reviewed before continuing.
disable-model-invocation: false
allowed-tools: Bash(git *), Bash(gh *)
---

# PR Checkpoint

When you reach a checkpoint (phase boundary, ~15 tasks complete, or significant milestone), create a PR for supervisor review instead of continuing.

## When to Create a PR

**Mandatory checkpoints:**
- End of any phase in fix_plan.md
- After completing ~15 tasks without a PR
- Before any major architectural change
- When tests are failing and you're unsure of the fix

**Optional checkpoints:**
- Completing a logical unit of work
- When you want feedback on an approach
- After fixing a tricky bug

## PR Creation Steps

1. **Ensure clean state:**
   ```bash
   git status
   pnpm build
   pnpm test
   ```

2. **Create a feature branch (if not already on one):**
   ```bash
   git checkout -b feature/<descriptive-name>
   ```

3. **Commit all work:**
   ```bash
   git add -A
   git commit -m "<type>: <description>"
   ```

4. **Push and create PR:**
   ```bash
   git push -u origin HEAD
   gh pr create --title "<PR title>" --body "$(cat <<'EOF'
   ## Summary
   <What this PR accomplishes>

   ## Changes
   - <Change 1>
   - <Change 2>

   ## Testing
   - [ ] Build passes: `pnpm build`
   - [ ] Tests pass: `pnpm test`
   - [ ] Coverage maintained: `pnpm test -- --coverage`

   ## fix_plan.md Progress
   - Completed tasks: <X-Y>
   - Phase: <current phase>

   ## Notes for Reviewer
   <Any concerns, questions, or areas needing attention>
   EOF
   )"
   ```

5. **Update status and EXIT:**
   - Update `.ralph/status.json` with `"awaiting_review": true`
   - **STOP WORKING** — do not continue until PR is reviewed
   - Your next action should be to report that you've created a PR and are awaiting review

## After PR is Merged

When the supervisor approves and merges your PR:
1. Pull latest: `git checkout main && git pull`
2. Continue from where you left off in fix_plan.md
3. Create a new feature branch for the next chunk of work

## After PR Changes Requested

When the supervisor requests changes:
1. Read the PR comments carefully
2. Address each comment
3. Push new commits to the same branch
4. Comment on the PR that changes are ready for re-review
5. **STOP WORKING** — wait for approval

## Critical Rules

- **Never continue past a checkpoint without PR approval**
- **Never auto-approve your own work**
- **Always include test status in PR description**
- **Always reference fix_plan.md progress**
