#!/bin/sh

echo "Writing Nanobot config..."

mkdir -p /root/.nanobot

cat > /root/.nanobot/config.json <<EOF
{
  "providers": {
    "openai": {
      "apiKey": "${OPENROUTER_API_KEY}",
      "baseURL": "https://openrouter.ai/api/v1"
    }
  },
  "agents": {
    "defaults": {
      "provider": "openai",
      "model": "${NANOBOT_MODEL}"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "${TELEGRAM_BOT_TOKEN}",
      "allowFrom": ["${TELEGRAM_ALLOW_FROM}"]
    }
  }
}
EOF

echo "Launching Nanobot..."
exec nanobot gateway
