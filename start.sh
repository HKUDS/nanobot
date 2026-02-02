#!/usr/bin/env bash
set -euo pipefail

# Optional install (useful on platforms that mount source but skip image builds).
if [[ "${NANOBOT_SKIP_INSTALL:-}" != "1" ]]; then
  install_needed=0
  if [[ "${NANOBOT_FORCE_INSTALL:-}" == "1" ]]; then
    install_needed=1
  elif ! command -v nanobot >/dev/null 2>&1; then
    install_needed=1
  fi

  if [[ "$install_needed" == "1" ]]; then
    python -m pip install --upgrade pip
    python -m pip install -e .
  fi
fi

# Prepare config directory
CONFIG_DIR="${HOME}/.nanobot"
CONFIG_FILE="${CONFIG_DIR}/config.json"
mkdir -p "$CONFIG_DIR"

# Create config.json from environment variables (basic example).
# Set these env vars in Railway: OPENROUTER_API_KEY, TELEGRAM_TOKEN, TELEGRAM_ALLOW_FROM (comma-separated), MODEL
WRITE_CONFIG="${NANOBOT_WRITE_CONFIG:-auto}"
should_write=0
if [[ "$WRITE_CONFIG" == "1" || "$WRITE_CONFIG" == "true" || "$WRITE_CONFIG" == "yes" ]]; then
  should_write=1
elif [[ "$WRITE_CONFIG" == "auto" && ! -f "$CONFIG_FILE" ]]; then
  should_write=1
fi

if [[ "$should_write" == "1" ]]; then
  ALLOW_FROM_JSON=$(python - <<'PY'
import json
import os

raw = os.getenv("TELEGRAM_ALLOW_FROM", "")
items = [item.strip() for item in raw.split(",") if item.strip()]
print(json.dumps(items))
PY
)
  cat > "$CONFIG_FILE" <<EOF
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
      "allowFrom": ${ALLOW_FROM_JSON}
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
  echo "wrote config to $CONFIG_FILE"
elif [[ -f "$CONFIG_FILE" ]]; then
  echo "using existing config at $CONFIG_FILE"
else
  echo "no config found at $CONFIG_FILE"
fi

if [[ "${NANOBOT_PRINT_CONFIG:-}" == "1" && -f "$CONFIG_FILE" ]]; then
  ls -l "$CONFIG_FILE"
  cat "$CONFIG_FILE"
fi

# Run the CLI entrypoint you want. Options:
# - For persistent gateway (connects to chat channels): nanobot gateway
# - For interactive/testing agent single run: nanobot agent -m "Hello"
# Start as gateway by default for background bot:
GATEWAY_ARGS=()
if [[ -n "${NANOBOT_PORT:-}" ]]; then
  GATEWAY_ARGS+=(--port "${NANOBOT_PORT}")
elif [[ -n "${PORT:-}" ]]; then
  GATEWAY_ARGS+=(--port "${PORT}")
fi
if [[ "${NANOBOT_VERBOSE:-}" == "1" ]]; then
  GATEWAY_ARGS+=(--verbose)
fi

exec nanobot gateway "${GATEWAY_ARGS[@]}"
