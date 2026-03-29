#!/bin/bash
INPUT=$(cat)
FILE=$(echo "$INPUT" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

# Only check nanobot Python files
case "$FILE" in
  nanobot/*.py|*/nanobot/*.py) ;;
  *) exit 0 ;;
esac

# Extract the base filename without extension
BASENAME=$(basename "$FILE" .py)

# Skip common/generic names that would match too broadly
case "$BASENAME" in
  __init__|__main__|conftest|setup) exit 0 ;;
esac

# Check living docs for references to this file/module
MATCHES=""
for doc in CLAUDE.md .claude/rules/architecture.md .claude/rules/cognitive-architecture.md docs/memory-system-reference.md docs/deployment.md; do
  if [ -f "$doc" ] && grep -qi "$BASENAME" "$doc" 2>/dev/null; then
    MATCHES="$MATCHES $doc"
  fi
done

# Silent on no matches (zero tokens)
if [ -z "$MATCHES" ]; then
  exit 0
fi

# Advisory when matches found
echo "{\"systemMessage\": \"You modified $BASENAME. These docs reference it:$MATCHES — verify they are still accurate.\"}"
exit 0
