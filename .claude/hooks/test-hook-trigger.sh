#!/bin/bash
INPUT=$(cat)
CMD=$(echo "$INPUT" | python -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command','UNKNOWN'))" 2>/dev/null || echo "PARSE_FAILED")
echo "[$(date)] HOOK FIRED | cmd=$CMD" >> .claude/hook-test.log
exit 0
