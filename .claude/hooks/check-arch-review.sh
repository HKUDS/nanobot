#!/bin/bash
# Check if nanobot/ code changed but .claude/rules/architecture.md was not updated.
# Silent on success (zero tokens). Advisory when architecture review needed.

# Determine what changed between current branch and origin/main
NANOBOT_CHANGED=$(git diff origin/main...HEAD --name-only 2>/dev/null | grep "^nanobot/" | head -1)
ARCH_CHANGED=$(git diff origin/main...HEAD --name-only 2>/dev/null | grep "^\.claude/rules/architecture.md")

if [ -n "$NANOBOT_CHANGED" ] && [ -z "$ARCH_CHANGED" ]; then
  echo '{"systemMessage": "nanobot/ code changed but .claude/rules/architecture.md was not updated. Verify it is still accurate before pushing."}'
fi
exit 0
