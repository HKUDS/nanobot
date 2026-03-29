#!/bin/bash
# Reminds to dispatch a code-reviewer subagent before committing implementation work.
# Only fires for feat/fix/refactor/perf commits (not docs/chore/test/ci).
# Silent for non-implementation commits (zero tokens).

INPUT=$(cat)
CMD=$(echo "$INPUT" | python -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null || echo "")

# Extract commit message
MSG=""
if echo "$CMD" | grep -q -- "-m"; then
  MSG=$(echo "$CMD" | sed -n "s/.*-m[[:space:]]*[\"']\([^\"']*\).*/\1/p")
  if [ -z "$MSG" ]; then
    MSG=$(echo "$CMD" | sed -n "s/.*<<'EOF'//p" | head -1)
  fi
fi

if [ -z "$MSG" ]; then
  exit 0
fi

FIRST_LINE=$(echo "$MSG" | head -1)

# Only remind for implementation commits
if [[ "$FIRST_LINE" =~ ^(feat|fix|refactor|perf) ]]; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "REMINDER: Have you dispatched a code-reviewer subagent for this implementation work? CLAUDE.md requires code quality review before committing. If not done, cancel this commit, run the review, then commit."}}'
fi
exit 0
