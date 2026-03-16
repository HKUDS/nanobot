#!/usr/bin/env bash
# deploy/migrate-from-systemd.sh — Migrate nanobot from systemd to Docker
#
# This script:
#   1. Stops the systemd user service
#   2. Deploys nanobot via Docker Compose (production)
#   3. Verifies health
#   4. Disables the systemd service (keeps unit file as fallback)
#
# Usage:
#   bash deploy/migrate-from-systemd.sh --image ghcr.io/cgajagon/nanobot:latest
#
# To revert:
#   docker compose -p nanobot-prod -f deploy/production/docker-compose.yml down
#   systemctl --user start nanobot-gateway

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

IMAGE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --image) IMAGE="$2"; shift 2 ;;
        *) echo "Usage: $0 --image <image:tag>"; exit 1 ;;
    esac
done

if [[ -z "$IMAGE" ]]; then
    echo "ERROR: --image is required"
    exit 1
fi

log() { echo "[$(date +%H:%M:%S)] $*"; }

# Step 1: Stop systemd service
log "Stopping nanobot-gateway systemd service..."
systemctl --user stop nanobot-gateway 2>/dev/null || true
sleep 2

# Verify port is free
if ss -tlnp | grep -q ":18790 "; then
    log "WARNING: Port 18790 still in use — waiting for it to free..."
    sleep 5
    if ss -tlnp | grep -q ":18790 "; then
        log "ERROR: Port 18790 still occupied. Check what's using it:"
        ss -tlnp | grep ":18790"
        exit 1
    fi
fi

# Step 2: Deploy via Docker
log "Deploying nanobot via Docker Compose..."
bash "$SCRIPT_DIR/deploy.sh" --env production --image "$IMAGE" --timeout 90

# Step 3: Verify (deploy.sh already checks health, but double-check)
log "Verifying Docker deployment..."
sleep 3
STATUS=$(curl -sf http://127.0.0.1:18790/health 2>/dev/null | grep -o '"ok"' || echo "")
if [[ -z "$STATUS" ]]; then
    log "ERROR: Docker deployment health check failed!"
    log "Reverting to systemd..."
    docker compose -p nanobot-prod -f "$SCRIPT_DIR/production/docker-compose.yml" down 2>/dev/null || true
    systemctl --user start nanobot-gateway
    log "Reverted to systemd service"
    exit 1
fi

# Step 4: Disable systemd service (don't remove — keep as fallback)
log "Disabling systemd service (unit file kept as fallback)..."
systemctl --user disable nanobot-gateway 2>/dev/null || true

log ""
log "Migration complete!"
log "  nanobot is now running via Docker (container: nanobot-prod)"
log "  systemd service disabled (unit file preserved at ~/.config/systemd/user/)"
log ""
log "To revert to systemd if needed:"
log "  docker compose -p nanobot-prod -f deploy/production/docker-compose.yml down"
log "  systemctl --user enable --now nanobot-gateway"
