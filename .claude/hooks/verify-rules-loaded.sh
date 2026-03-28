#!/bin/bash
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python -c "import json,sys; print(json.load(sys.stdin).get('file_path','unknown'))" 2>/dev/null || echo "unknown")
LOAD_REASON=$(echo "$INPUT" | python -c "import json,sys; print(json.load(sys.stdin).get('load_reason','unknown'))" 2>/dev/null || echo "unknown")

echo "[$(date)] Loaded: $FILE_PATH (reason: $LOAD_REASON)" >> .claude/rules-audit.log
exit 0
