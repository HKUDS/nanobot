#!/usr/bin/env bash
# deploy/deploy.sh — Deploy nanobot to staging or production
#
# Usage:
#   deploy/deploy.sh --env staging  --image ghcr.io/cgajagon/nanobot:sha-abc1234
#   deploy/deploy.sh --env production --image ghcr.io/cgajagon/nanobot:latest
#   deploy/deploy.sh --env production --rollback
#
# Prerequisites:
#   - Docker + Docker Compose v2
#   - Authenticated to GHCR: echo $GHCR_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Defaults ──────────────────────────────────────────────────────────
ENV=""
IMAGE=""
ROLLBACK=false
DRY_RUN=false
HEALTH_TIMEOUT=60
HEALTH_INTERVAL=5

# ── Parse args ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)       ENV="$2"; shift 2 ;;
        --image)     IMAGE="$2"; shift 2 ;;
        --rollback)  ROLLBACK=true; shift ;;
        --dry-run)   DRY_RUN=true; shift ;;
        --timeout)   HEALTH_TIMEOUT="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --env <staging|production> --image <image:tag> [--rollback] [--dry-run] [--timeout <seconds>]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$ENV" ]]; then
    echo "ERROR: --env is required (staging or production)"
    exit 1
fi

if [[ "$ENV" != "staging" && "$ENV" != "production" ]]; then
    echo "ERROR: --env must be 'staging' or 'production'"
    exit 1
fi

# ── Environment config ────────────────────────────────────────────────
COMPOSE_DIR="$SCRIPT_DIR/$ENV"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
PROJECT_NAME="nanobot-${ENV/production/prod}"
STATE_DIR="$COMPOSE_DIR/.deploy-state"
PREV_IMAGE_FILE="$STATE_DIR/previous-image"

if [[ "$ENV" == "staging" ]]; then
    HEALTH_PORT=18791
    CONTAINER_NAME="nanobot-staging"
else
    HEALTH_PORT=18790
    CONTAINER_NAME="nanobot-prod"
fi

mkdir -p "$STATE_DIR"

# ── Helper functions ──────────────────────────────────────────────────
log()  { echo "[$(date +%H:%M:%S)] $*"; }
fail() { log "ERROR: $*"; exit 1; }

get_current_image() {
    docker inspect --format='{{.Config.Image}}' "$CONTAINER_NAME" 2>/dev/null || echo ""
}

health_check() {
    local port=$1 timeout=$2
    local elapsed=0
    log "Waiting for health check on port $port (timeout: ${timeout}s)..."
    while [[ $elapsed -lt $timeout ]]; do
        if curl -sf "http://127.0.0.1:$port/health" > /dev/null 2>&1; then
            log "Health check passed!"
            return 0
        fi
        sleep "$HEALTH_INTERVAL"
        elapsed=$((elapsed + HEALTH_INTERVAL))
    done
    log "Health check FAILED after ${timeout}s"
    return 1
}

# ── Rollback ──────────────────────────────────────────────────────────
if [[ "$ROLLBACK" == "true" ]]; then
    if [[ ! -f "$PREV_IMAGE_FILE" ]]; then
        fail "No previous image found at $PREV_IMAGE_FILE — cannot rollback"
    fi
    IMAGE=$(cat "$PREV_IMAGE_FILE")
    log "Rolling back $ENV to previous image: $IMAGE"
fi

if [[ -z "$IMAGE" && "$ROLLBACK" != "true" ]]; then
    fail "--image is required (or use --rollback)"
fi

# ── Deploy ────────────────────────────────────────────────────────────
log "Deploying $ENV with image: $IMAGE"

if [[ "$DRY_RUN" == "true" ]]; then
    log "[DRY RUN] Would execute:"
    log "  docker compose -p $PROJECT_NAME -f $COMPOSE_FILE pull"
    log "  NANOBOT_IMAGE=$IMAGE docker compose -p $PROJECT_NAME -f $COMPOSE_FILE up -d --remove-orphans"
    log "  health_check $HEALTH_PORT $HEALTH_TIMEOUT"
    exit 0
fi

# Save current image for rollback before deploying
CURRENT_IMAGE=$(get_current_image)
if [[ -n "$CURRENT_IMAGE" && "$ROLLBACK" != "true" ]]; then
    echo "$CURRENT_IMAGE" > "$PREV_IMAGE_FILE"
    log "Saved previous image for rollback: $CURRENT_IMAGE"
fi

# Pull and deploy
log "Pulling image..."
docker pull "$IMAGE"

log "Starting services..."
cd "$COMPOSE_DIR"
NANOBOT_IMAGE="$IMAGE" docker compose -p "$PROJECT_NAME" -f docker-compose.yml up -d --remove-orphans

# Health check
if ! health_check "$HEALTH_PORT" "$HEALTH_TIMEOUT"; then
    log "Deployment FAILED — health check did not pass"

    if [[ -n "$CURRENT_IMAGE" && "$ROLLBACK" != "true" ]]; then
        log "Auto-rolling back to: $CURRENT_IMAGE"
        NANOBOT_IMAGE="$CURRENT_IMAGE" docker compose -p "$PROJECT_NAME" -f docker-compose.yml up -d --remove-orphans

        if health_check "$HEALTH_PORT" "$HEALTH_TIMEOUT"; then
            log "Rollback successful"
        else
            log "WARNING: Rollback also failed — manual intervention required"
        fi
    fi
    exit 1
fi

log "Deployment of $ENV complete — image: $IMAGE"
log "Container: $CONTAINER_NAME | Port: $HEALTH_PORT"
