#!/bin/bash
# When architecture.md or cognitive-architecture.md changes, advise reviewing
# whether an existing ADR should be superseded or a new ADR is needed.
# Fires on PostToolUse Edit|Write for these specific files.
INPUT=$(cat)
FILE=$(echo "$INPUT" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

# Only trigger for architecture docs
case "$FILE" in
  *architecture.md|*cognitive-architecture.md) ;;
  *) exit 0 ;;
esac

echo '{"systemMessage": "You modified an architecture document. Review docs/adr/ — does this change supersede an existing ADR or require a new one?"}'
exit 0
