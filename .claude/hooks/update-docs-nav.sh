#!/bin/bash
# Hook: regenerate docs/README.md navigation tree after editing docs/

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only process docs/ files
echo "$FILE_PATH" | grep -q 'docs/' || exit 0

# Skip README.md itself to avoid infinite loop
echo "$FILE_PATH" | grep -q 'docs/README\.md' && exit 0

cd D:/nanobot && python scripts/update_docs_nav.py
exit 0
