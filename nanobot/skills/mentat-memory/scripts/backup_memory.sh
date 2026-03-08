#!/bin/bash
# Backup memory system files

BACKUP_DIR="memory/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup memory bank if it exists
if [ -f "memory/diary/2026/memories.jsonl" ]; then
    cp memory/diary/2026/memories.jsonl "$BACKUP_DIR/memories_$TIMESTAMP.jsonl"
    echo "✅ Backed up memories.jsonl"
fi

# Backup state file if it exists
if [ -f "memory/diary/2026/.state.json" ]; then
    cp memory/diary/2026/.state.json "$BACKUP_DIR/state_$TIMESTAMP.json"
    echo "✅ Backed up .state.json"
fi

echo "Backup created: $BACKUP_DIR/*_$TIMESTAMP.*"

# Keep only last 10 backups
if ls "$BACKUP_DIR"/memories_*.jsonl 1> /dev/null 2>&1; then
    ls -t "$BACKUP_DIR"/memories_*.jsonl | tail -n +11 | xargs rm -f 2>/dev/null
fi

if ls "$BACKUP_DIR"/state_*.json 1> /dev/null 2>&1; then
    ls -t "$BACKUP_DIR"/state_*.json | tail -n +11 | xargs rm -f 2>/dev/null
fi

echo "✅ Cleanup complete (kept last 10 backups)"
