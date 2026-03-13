#!/bin/bash
# Setup script to install open-skills repository for nanobot

set -e

OPEN_SKILLS_DIR="$HOME/open-skills"

echo "🐈 nanobot: Setting up open-skills integration..."

# Check if open-skills already exists
if [ -d "$OPEN_SKILLS_DIR" ]; then
    echo "✓ open-skills already exists at $OPEN_SKILLS_DIR"
    echo "  Updating to latest version..."
    cd "$OPEN_SKILLS_DIR"
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || echo "  (Already up to date)"
else
    echo "  Cloning open-skills repository..."
    git clone https://github.com/besoeasy/open-skills.git "$OPEN_SKILLS_DIR"
    echo "✓ open-skills installed at $OPEN_SKILLS_DIR"
fi

echo ""
echo "✓ Setup complete!"
echo ""
echo "open-skills provides battle-tested code patterns that reduce token usage by ~98%."
echo "The repository is now available at: $OPEN_SKILLS_DIR"
echo ""
echo "To keep it updated, run: cd $OPEN_SKILLS_DIR && git pull"
echo ""
