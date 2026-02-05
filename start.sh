#!/usr/bin/env bash
set -euo pipefail

# Install python dependencies (Railway will cache virtualenv typically).
# Use pip install -e . so the installed package exposes the `nanobot` CLI.
pip install --upgrade pip
pip install -e .

# Prepare config directory
CONFIG_DIR="${HOME}/.nanobot"
mkdir -p "$CONFIG_DIR"

# Create config.json from environment variables (basic example).
# Set these env vars in Railway: OPENROUTER_API_KEY, TELEGRAM_TOKEN, TELEGRAM_ALLOW_FROM (comma-separated), MODEL
cat > "${CONFIG_DIR}/config.json" <<EOF
{
  "providers": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY:-}"
    }
  },
  "agents": {
    "defaults": {
      "model": "${MODEL:-anthropic/claude-opus-4-5}"
    }
  },
  "channels": {
    "telegram": {
      "enabled": ${TELEGRAM_ENABLED:-true},
      "token": "${TELEGRAM_TOKEN:-}",
      "allowFrom": [$(printf '%s' "${TELEGRAM_ALLOW_FROM:-}" | awk -F',' '{for(i=1;i<=NF;i++){printf "\"%s\"%s",$i,(i<NF?",":"")}}')]
    },
    "whatsapp": {
      "enabled": ${WHATSAPP_ENABLED:-false}
    }
  },
  "tools": {
    "web": {
      "search": {
        "apiKey": "${WEBSEARCH_API_KEY:-}"
      }
    }
  }
}
EOF

echo "wrote config to ${CONFIG_DIR}/config.json"
ls -l "${CONFIG_DIR}/config.json"
cat "${CONFIG_DIR}/config.json"

# Run the CLI entrypoint you want. Options:
# - For persistent gateway (connects to chat channels): nanobot gateway
# - For interactive/testing agent single run: nanobot agent -m "Hello"
# Start as gateway by default for background bot:
exec nanobot gateway
