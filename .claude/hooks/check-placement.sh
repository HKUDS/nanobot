#!/usr/bin/env bash
# Advisory on new file creation in nanobot/.
# Hard blocks banned filenames (exit 2 + stderr). Advisory for misplaced files.
# Silent for normal files.

# Read the tool input from stdin
INPUT=$(cat)

# Extract file_path from JSON
FILE_PATH=$(echo "$INPUT" | jq -r '.file_path // empty' 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only trigger for files under nanobot/
case "$FILE_PATH" in
  *nanobot/*) ;;
  *) exit 0 ;;
esac

# Check for banned filenames — hard block
BASENAME=$(basename "$FILE_PATH")
case "$BASENAME" in
  utils.py|helpers.py|common.py|misc.py)
    echo "BLOCKED: Catch-all filenames (utils.py, helpers.py, common.py, misc.py) are prohibited. Place logic in the package that owns the concept." >&2
    exit 2
    ;;
esac

# Check for memory flat files (not in a subdirectory)
if [[ "$FILE_PATH" =~ nanobot/memory/[^/]+\.py$ ]] && [[ ! "$FILE_PATH" =~ nanobot/memory/__init__\.py$ ]]; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "Advisory: nanobot/memory/ has internal subdirectories (write/, read/, ranking/, persistence/, graph/). Should this file be in one of those subdirectories instead?"}}'
  exit 0
fi

# Check for tool implementations at tools/ level instead of builtin/
if [[ "$FILE_PATH" =~ nanobot/tools/[^/]+\.py$ ]] && [[ ! "$FILE_PATH" =~ nanobot/tools/__init__\.py$ ]]; then
  BASENAME_NO_EXT="${BASENAME%.py}"
  case "$BASENAME_NO_EXT" in
    base|registry|executor|capability|setup|types)
      # These are infrastructure files — allowed at tools/ level
      exit 0
      ;;
    *)
      echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "Advisory: Tool implementations go in nanobot/tools/builtin/, not at the tools/ level. Infrastructure (base, registry, executor) stays at tools/ level."}}'
      exit 0
      ;;
  esac
fi

exit 0
