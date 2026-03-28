# Git Worktree Protocol

Use worktrees to isolate experimental or parallel work from the main checkout.

## Lifecycle

1. **Create** a worktree for a branch:

   ```bash
   git worktree add ../nanobot-<branch-name> -b <branch-name>
   ```

2. **Work** inside the worktree directory — it has its own working tree but shares
   `.git` history, so all branches and commits are visible.

3. **Finish** — merge/PR from within the worktree or push the branch, then remove it:

   ```bash
   git worktree remove ../nanobot-<branch-name>
   # or, if the worktree has untracked files:
   git worktree remove --force ../nanobot-<branch-name>
   ```

4. **Prune** — clean up stale worktree metadata (e.g. after manually deleting the dir):

   ```bash
   make worktree-clean   # runs `git worktree prune` + lists remaining worktrees
   ```

## Rules

- Never leave abandoned worktrees — they block branch deletion and confuse `git status`.
- Run `make worktree-clean` periodically (or before releasing a branch) to prune stale entries.
- Do **not** run `make install` inside a worktree — dependencies are shared from the
  main checkout's virtual environment.
- Pre-commit hooks run normally inside worktrees; no special setup needed.
