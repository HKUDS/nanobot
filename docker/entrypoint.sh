#!/bin/bash
set -e

echo "🤖 Starting Nanobot with Browser Support"

# Start Xvfb (virtual display) for headed mode support
echo "📺 Starting virtual display (Xvfb)..."
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
echo "Xvfb PID: $XVFB_PID"

# Wait for Xvfb to be ready
sleep 2

# Start VNC server if VNC_ENABLED is set
if [ "$VNC_ENABLED" = "true" ]; then
    echo "🖥️  Starting VNC server..."
    x11vnc -display :99 -nopw -forever -shared -rfbport 5900 &
    echo "VNC server started on port 5900"
    
    # Start noVNC (web-based VNC client)
    echo "🌐 Starting noVNC (web VNC)..."
    websockify --web=/usr/share/novnc --cert=none 6080 localhost:5900 &
    echo "noVNC started on port 6080"
    echo "   Access VNC via: http://localhost:6080/vnc.html"
fi

# Ensure workspace directories exist
mkdir -p /app/workspace/screenshots /app/workspace/downloads

# Check if running in Docker (should be true in this container)
export NANOBOT__TOOLS__BROWSER__DOCKER_MODE=true

echo "✅ Setup complete"
echo ""
echo "Configuration:"
echo "  - Browser Headless: $NANOBOT__TOOLS__BROWSER__HEADLESS"
echo "  - Docker Mode: $NANOBOT__TOOLS__BROWSER__DOCKER_MODE"
echo "  - Display: $DISPLAY"
echo ""

# Handle shutdown gracefully
shutdown() {
    echo ""
    echo "🛑 Shutting down..."
    if [ -n "$XVFB_PID" ]; then
        kill $XVFB_PID 2>/dev/null || true
    fi
    exit 0
}

trap shutdown SIGTERM SIGINT

# Execute the main command
exec "$@"
