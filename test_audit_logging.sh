#!/bin/bash
#
# Complete test script for API audit logging feature
#

set -e

# Configuration
VENV_DIR="/tmp/nanobot-venv"
HOME_DIR="/tmp/nanobot-test-config"
NANOBOT_DIR="/data/liuxiang/workspace/nanobot"

echo "=========================================="
echo "  API Audit Logging - Full Test Script"
echo "=========================================="
echo
echo "Configuration:"
echo "  VENV: $VENV_DIR"
echo "  HOME: $HOME_DIR"
echo "  Project: $NANOBOT_DIR"
echo

# 1. Activate virtual environment
echo "[1/7] Activating virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    echo "  ERROR: Virtual environment not found at $VENV_DIR"
    exit 1
fi
source "$VENV_DIR/bin/activate"
echo "  ✓ Virtual environment activated"
echo

# 2. Set HOME and verify config
echo "[2/7] Setting HOME to $HOME_DIR..."
export HOME="$HOME_DIR"

CONFIG_PATH="$HOME/.nanobot/config.json"
if [ ! -f "$CONFIG_PATH" ]; then
    echo "  ERROR: Config not found at $CONFIG_PATH"
    exit 1
fi
echo "  ✓ Config exists at $CONFIG_PATH"
echo

# 3. Show current stats
echo "[3/7] Current API statistics before test:"
echo
cd "$NANOBOT_DIR"
nanobot stats show
echo

# 4. Run a few test chats
echo "[4/7] Running test API calls..."
echo
for i in 1 2 3; do
    MESSAGE="Hello, this is test message $i"
    echo "  Test $i: nanobot agent -m \"$MESSAGE\""
    nanobot agent -m "$MESSAGE"
    echo
    sleep 1
done
echo

# 5. Show stats and logs
echo "[5/7] Final results:"
echo
echo "--- Statistics ---"
nanobot stats show
echo

echo "[6/7] Cache Hit Rate Analysis (Global):"
echo
nanobot stats cache
echo

echo "[7/7] Cache Hit Rate Analysis (By Session - Accurate):"
echo
nanobot stats cache --session --accurate
echo

echo "--- Recent Logs ---"
nanobot stats logs --limit 10
echo

echo "--- Log Path ---"
nanobot stats path
echo

echo "=========================================="
echo "  Test complete!"
echo "=========================================="
echo
echo "To use manually:"
echo "  source $VENV_DIR/bin/activate"
echo "  export HOME=$HOME_DIR"
echo "  nanobot agent -m \"Hello\""
echo "  nanobot stats show"
echo "  nanobot stats cache"
echo "  nanobot stats cache --session --accurate"
echo
