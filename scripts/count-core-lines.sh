#!/usr/bin/env bash
set -euo pipefail

# Count core agent lines (excluding channels/, cli/, providers/ adapters)
cd "$(dirname "$0")/.." || exit 1

echo "nanobot core agent line count"
echo "================================"
echo ""

for dir in agent agent/tools bus config cron heartbeat session utils; do
  count=$(find "nanobot/$dir" -maxdepth 1 -type f -name "*.py" -exec wc -l {} + | awk '{sum += $1} END {print sum + 0}')
  printf "  %-16s %5s lines\n" "$dir/" "$count"
done

root=$(wc -l nanobot/__init__.py nanobot/__main__.py | awk 'END {print $1}')
printf "  %-16s %5s lines\n" "(root)" "$root"

echo ""
total=$(find nanobot -type f -name "*.py" ! -path "*/channels/*" ! -path "*/cli/*" ! -path "*/providers/*" -exec wc -l {} + | awk '{sum += $1} END {print sum + 0}')
echo "  Core total:     $total lines"
echo ""
echo "  (excludes: channels/, cli/, providers/)"
