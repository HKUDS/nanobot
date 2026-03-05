#!/bin/bash

# nanobot Multi-Instance Startup Script
# Usage: ./start_nanobot.sh [config_path]
# Example: ./start_nanobot.sh ~/.nanobot-instance2/config.json

CONFIG_PATH="${1:-$HOME/.nanobot/config.json}"

cd "$(dirname "$0")"

echo "🐈 Starting nanobot..."
echo "Config: $CONFIG_PATH"
echo ""

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Start gateway with specified config
if [ -f "$CONFIG_PATH" ]; then
    nanobot gateway --config "$CONFIG_PATH"
else
    echo "❌ Config file not found: $CONFIG_PATH"
    echo "Usage: $0 [config_path]"
    exit 1
fi
