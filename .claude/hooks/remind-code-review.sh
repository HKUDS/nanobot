#!/bin/bash
# Reminds to dispatch a code-reviewer subagent before committing implementation work.
# Only fires for feat/fix/refactor/perf commits (not docs/chore/test/ci).
# Silent for non-implementation commits (zero tokens).

INPUT=$(cat)
CMD=$(echo "$INPUT" | python -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null || echo "")

# Check if command contains an implementation commit type anywhere
if echo "$CMD" | grep -qE '(feat|fix|refactor|perf)(\([a-zA-Z0-9_-]+\))?!?: '; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "REMINDER: Have you dispatched a code-reviewer subagent for this implementation work? CLAUDE.md requires code quality review before committing. If not done, cancel this commit, run the review, then commit."}}'
fi
exit 0
