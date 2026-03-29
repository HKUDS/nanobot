#!/usr/bin/env bash
# Validates Conventional Commits format on git commit commands.
# Silent on valid format (zero tokens). Advisory on invalid format.

INPUT=$(cat)
CMD=$(echo "$INPUT" | python -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null || echo "")

# Must contain git commit with -m
if ! echo "$CMD" | grep -q "git commit"; then
  exit 0
fi
if ! echo "$CMD" | grep -q -- "-m"; then
  exit 0
fi

# Allow merge commits and release commits
if echo "$CMD" | grep -qE '(Merge|chore\(release\))'; then
  exit 0
fi

# Check if command contains a valid conventional commit type
if echo "$CMD" | grep -qE '(feat|fix|perf|refactor|docs|test|chore|ci)(\([a-zA-Z0-9_-]+\))?!?: '; then
  exit 0
fi

# No valid type found — advisory
echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "Commit message does not follow Conventional Commits format. Expected: <type>(<scope>): <description> where type is one of: feat, fix, perf, refactor, docs, test, chore, ci. Example: feat(memory): add hybrid retrieval"}}'
exit 0
