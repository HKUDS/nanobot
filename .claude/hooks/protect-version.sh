#!/usr/bin/env bash
# Warns when editing version strings in pyproject.toml or __init__.py.
# Silent if no version edit detected.

# Read the tool input from stdin
INPUT=$(cat)

# Extract file_path from JSON
FILE_PATH=$(echo "$INPUT" | jq -r '.file_path // empty' 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only check pyproject.toml and __init__.py files
case "$FILE_PATH" in
  *pyproject.toml|*__init__.py) ;;
  *) exit 0 ;;
esac

# Check if new_string contains version patterns
NEW_STRING=$(echo "$INPUT" | jq -r '.new_string // empty' 2>/dev/null)

if [ -z "$NEW_STRING" ]; then
  exit 0
fi

if echo "$NEW_STRING" | grep -qE '(__version__|^version[[:space:]]*=)'; then
  echo "{\"systemMessage\": \"WARNING: You are editing a version string. python-semantic-release manages versions automatically. Do not manually edit __version__ or pyproject.toml version fields.\"}"
fi

exit 0
