#!/bin/bash

# nanobot Multi-Instance Diagnostic Tool
# Usage: ./diagnose.sh [config_path]
# Example: ./diagnose.sh ~/.nanobot-instance2/config.json

CONFIG_PATH="${1:-$HOME/.nanobot/config.json}"
DATA_DIR=$(dirname "$CONFIG_PATH")

echo "🔍 nanobot Multi-Instance Diagnostic"
echo "================================"
echo "Config: $CONFIG_PATH"
echo "Data Dir: $DATA_DIR"
echo ""

# Check if config exists
if [ ! -f "$CONFIG_PATH" ]; then
    echo "❌ Config file not found: $CONFIG_PATH"
    exit 1
fi

# Check process
echo "1. Process Status:"
if ps aux | grep -E "nanobot gateway.*--config.*$(basename $CONFIG_PATH)" | grep -v grep > /dev/null; then
    echo "   ✅ nanobot gateway is running"
    ps aux | grep -E "nanobot gateway.*--config.*$(basename $CONFIG_PATH)" | grep -v grep | awk '{print "   PID:", $2, "Runtime:", $10}'
else
    echo "   ❌ nanobot gateway is not running"
fi
echo ""

# Check configuration
echo "2. Feishu Configuration:"
if grep -q '"enabled": true' "$CONFIG_PATH" | grep -A 5 feishu; then
    echo "   ✅ Feishu channel enabled"
else
    echo "   ❌ Feishu channel disabled"
fi

APP_ID=$(grep -A 5 '"feishu"' "$CONFIG_PATH" | grep appId | cut -d'"' -f4)
if [ ! -z "$APP_ID" ]; then
    echo "   ✅ App ID: $APP_ID"
else
    echo "   ❌ App ID not configured"
fi
echo ""

# Check port
echo "3. Gateway Port:"
PORT=$(grep -A 2 '"gateway"' "$CONFIG_PATH" | grep port | grep -o '[0-9]*')
if [ ! -z "$PORT" ]; then
    if lsof -i :$PORT > /dev/null 2>&1; then
        echo "   ✅ Port $PORT is listening"
    else
        echo "   ⚠️  Port $PORT is not listening (normal for WebSocket mode)"
    fi
else
    echo "   ⚠️  Port not configured"
fi
echo ""

# Check network connections
echo "4. Feishu WebSocket Connection:"
if lsof -i -n | grep -i python | grep -i established | grep -q feishu; then
    echo "   ✅ Connected to Feishu servers"
else
    echo "   ⚠️  No active Feishu connection detected"
fi
echo ""

# Check logs
echo "5. Log Files:"
if [ -d "$DATA_DIR/logs" ]; then
    echo "   ✅ Log directory: $DATA_DIR/logs"
    ls -lh "$DATA_DIR/logs" | tail -5
else
    echo "   ⚠️  No log directory found"
fi
echo ""

echo "================================"
echo "💡 Troubleshooting Tips:"
echo ""
echo "1. Start the instance:"
echo "   nanobot gateway --config $CONFIG_PATH"
echo ""
echo "2. Test in Feishu:"
echo "   - Search for your bot name"
echo "   - Send a message"
echo "   - Check terminal output for logs"
echo ""
echo "3. Verify Feishu app configuration:"
echo "   - App is published"
echo "   - Permissions: im:message, im:message.p2p_msg:readonly"
echo "   - Event subscription: im.message.receive_v1 (WebSocket mode)"
echo ""
echo "4. View real-time logs:"
echo "   Run 'nanobot gateway --config $CONFIG_PATH' in a terminal"
