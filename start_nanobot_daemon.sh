#!/bin/bash

# nanobot Multi-Instance Daemon Startup Script
# Usage: ./start_nanobot_daemon.sh [config_path] [pid_file]
# Example: ./start_nanobot_daemon.sh ~/.nanobot-instance2/config.json ~/.nanobot-instance2/nanobot.pid

CONFIG_PATH="${1:-$HOME/.nanobot/config.json}"
PID_FILE="${2:-$HOME/.nanobot/nanobot.pid}"
LOG_FILE="${3:-/tmp/nanobot_$(basename $(dirname $CONFIG_PATH)).log}"

cd "$(dirname "$0")"

echo "🐈 Starting nanobot (daemon mode)..."
echo "Config: $CONFIG_PATH"
echo "PID file: $PID_FILE"
echo "Log file: $LOG_FILE"
echo ""

# Check if config exists
if [ ! -f "$CONFIG_PATH" ]; then
    echo "❌ Config file not found: $CONFIG_PATH"
    exit 1
fi

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo "⚠️  nanobot is already running (PID: $OLD_PID)"
        exit 1
    else
        echo "⚠️  Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Start gateway with nohup
nohup nanobot gateway --config "$CONFIG_PATH" > "$LOG_FILE" 2>&1 &

# Save PID
NANOBOT_PID=$!
echo $NANOBOT_PID > "$PID_FILE"

echo "✓ Nanobot started (PID: $NANOBOT_PID)"
echo "✓ Log file: $LOG_FILE"
echo ""
echo "View logs: tail -f $LOG_FILE"
echo "Stop service: kill \$(cat $PID_FILE)"
