#!/usr/bin/env bash
# Validates Conventional Commits format on git commit commands.
# Silent on success (zero tokens). Advisory systemMessage on invalid format.

# Extract commit message from the command arguments
COMMAND="$@"
if [ -z "$COMMAND" ]; then
  # Read from stdin (hook input)
  read -r COMMAND
fi

# Extract the message after -m flag
MSG=""
if [[ "$COMMAND" =~ -m[[:space:]]+\"([^\"]+)\" ]]; then
  MSG="${BASH_REMATCH[1]}"
elif [[ "$COMMAND" =~ -m[[:space:]]+\'([^\']+)\' ]]; then
  MSG="${BASH_REMATCH[1]}"
elif [[ "$COMMAND" =~ -m[[:space:]]+\$\(cat ]]; then
  # HEREDOC pattern — extract content between HEREDOC markers
  # This is best-effort; complex heredocs may not parse perfectly
  MSG=$(echo "$COMMAND" | sed -n "s/.*<<'EOF'//p" | sed -n '/EOF/q;p' | head -1)
fi

# If we couldn't extract a message, allow it (could be --amend, etc.)
if [ -z "$MSG" ]; then
  exit 0
fi

# Get first line of the message
FIRST_LINE=$(echo "$MSG" | head -1)

# Allow merge commits and release commits
if [[ "$FIRST_LINE" =~ ^Merge ]]; then
  exit 0
fi
if [[ "$FIRST_LINE" =~ ^chore\(release\) ]]; then
  exit 0
fi

# Validate conventional commit format
if [[ "$FIRST_LINE" =~ ^(feat|fix|perf|refactor|docs|test|chore|ci)(\([a-zA-Z0-9_-]+\))?!?:[[:space:]] ]]; then
  exit 0
fi

# Invalid format — advisory message
echo "{\"systemMessage\": \"Commit message does not follow Conventional Commits format. Expected: <type>(<scope>): <description> where type is one of: feat, fix, perf, refactor, docs, test, chore, ci. Example: feat(memory): add hybrid retrieval\"}"
exit 0
