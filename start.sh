#!/bin/sh

# Create config from secret
mkdir -p /root/.nanobot
echo "$NANOBOT_CONFIG" > /root/.nanobot/config.json

# Link data dirs to persistent volume (workspace is mounted)
mkdir -p /root/.nanobot/workspace/data/cron
mkdir -p /root/.nanobot/workspace/data/sessions
ln -sfn /root/.nanobot/workspace/data/cron /root/.nanobot/cron
ln -sfn /root/.nanobot/workspace/data/sessions /root/.nanobot/sessions

# Run onboard if workspace files missing
if [ ! -f /root/.nanobot/workspace/AGENTS.md ]; then
    nanobot onboard
fi

exec nanobot gateway
