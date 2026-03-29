#!/usr/bin/env bash
# Blocks implementation commits (feat, fix, refactor, test) to main branch.
# Allows docs: and chore: commits on main. Silent on non-main branches.

BRANCH=$(git branch --show-current 2>/dev/null)

# Not on main — allow everything
if [ "$BRANCH" != "main" ]; then
  exit 0
fi

# On main — check the commit type from the command
COMMAND="$@"
if [ -z "$COMMAND" ]; then
  read -r COMMAND
fi

# Extract commit message
MSG=""
if [[ "$COMMAND" =~ -m[[:space:]]+\"([^\"]+)\" ]]; then
  MSG="${BASH_REMATCH[1]}"
elif [[ "$COMMAND" =~ -m[[:space:]]+\'([^\']+)\' ]]; then
  MSG="${BASH_REMATCH[1]}"
fi

if [ -z "$MSG" ]; then
  exit 0
fi

FIRST_LINE=$(echo "$MSG" | head -1)

# Allow merge, release, docs, chore, ci commits on main
if [[ "$FIRST_LINE" =~ ^(Merge|chore|docs|ci) ]]; then
  exit 0
fi

# Block feat, fix, refactor, test, perf on main
if [[ "$FIRST_LINE" =~ ^(feat|fix|refactor|test|perf) ]]; then
  echo "BLOCKED: Implementation commits (feat/fix/refactor/test/perf) should not go directly to main. Create a feature branch: git worktree add ../nanobot-<branch> -b <branch>" >&2
  exit 2
fi

exit 0
