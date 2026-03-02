#!/bin/bash
# scorpion - Start the Rational Coding Agent
# Always uses the scorpion-env virtual environment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/scorpion-env"

echo "🐈 scorpion - Rational Coding Agent"
echo "===================================="

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Virtual environment not found at: $VENV_DIR"
    echo "Run: cd $SCRIPT_DIR && uv venv scorpion-env"
    exit 1
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Reinstall package (ensures latest code is used)
echo "📦 Installing scorpion..."
pip install -e "$SCRIPT_DIR" --quiet 2>/dev/null || true

# Run the agent
echo "🚀 Starting scorpion..."
echo ""
python "$SCRIPT_DIR/scorpion/agent/run.py"
