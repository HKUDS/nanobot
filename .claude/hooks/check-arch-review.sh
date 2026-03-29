#!/bin/bash
# Check if nanobot/ code changed but architecture docs were not updated.
# Silent on success (zero tokens). Advisory when architecture review needed.

# Determine what changed between current branch and origin/main
NANOBOT_CHANGED=$(git diff origin/main...HEAD --name-only 2>/dev/null | grep "^nanobot/" | head -1)
ARCH_CHANGED=$(git diff origin/main...HEAD --name-only 2>/dev/null | grep "^\.claude/rules/architecture\.md")
COG_CHANGED=$(git diff origin/main...HEAD --name-only 2>/dev/null | grep "^\.claude/rules/cognitive-architecture\.md")

MESSAGES=""
if [ -n "$NANOBOT_CHANGED" ] && [ -z "$ARCH_CHANGED" ]; then
  MESSAGES="nanobot/ code changed but .claude/rules/architecture.md was not updated. Verify it is still accurate before pushing."
fi
if [ -n "$NANOBOT_CHANGED" ] && [ -z "$COG_CHANGED" ]; then
  if [ -n "$MESSAGES" ]; then
    MESSAGES="$MESSAGES Also: "
  fi
  MESSAGES="${MESSAGES}nanobot/ code changed but .claude/rules/cognitive-architecture.md was not updated. Verify it is still accurate before pushing."
fi

if [ -n "$MESSAGES" ]; then
  echo "{\"hookSpecificOutput\": {\"hookEventName\": \"PreToolUse\", \"additionalContext\": \"$MESSAGES\"}}"
fi
exit 0
