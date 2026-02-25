#!/bin/sh
set -e

# Start the WhatsApp bridge in the background if WhatsApp is enabled
if [ "$NANOBOT_BRIDGE" = "1" ]; then
    # When /app is bind-mounted from host, bridge build artifacts may be absent.
    if [ ! -f /app/bridge/dist/index.js ]; then
        echo "Bridge build not found, building bridge..."
        cd /app/bridge
        npm install
        npm run build
        cd /app
    fi

    echo "Starting WhatsApp bridge on port ${BRIDGE_PORT:-3001}..."
    node /app/bridge/dist/index.js &
    BRIDGE_PID=$!

    # Wait briefly for bridge to start listening
    sleep 2

    trap "kill $BRIDGE_PID 2>/dev/null; wait $BRIDGE_PID 2>/dev/null" EXIT INT TERM
fi

# Run the nanobot command (gateway, status, agent, etc.)
exec nanobot "$@"
