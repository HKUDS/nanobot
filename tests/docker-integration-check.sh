#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required but was not found in PATH" >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "docker daemon is not reachable" >&2
    exit 1
fi

RUN_ID="$(date +%s)-$$"
IMAGE_NAME="nanobot-test-${RUN_ID}"
ONBOARDED_IMAGE_NAME="nanobot-test-onboarded-${RUN_ID}"
RUN_CONTAINER_NAME="nanobot-test-run-${RUN_ID}"

cleanup() {
    echo ""
    echo "=== Cleanup ==="
    docker rm -f "${RUN_CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rmi -f "${ONBOARDED_IMAGE_NAME}" >/dev/null 2>&1 || true
    docker rmi -f "${IMAGE_NAME}" >/dev/null 2>&1 || true
    echo "Done."
}

trap cleanup EXIT

echo "=== Building Docker image ==="
docker build -t "${IMAGE_NAME}" .

echo ""
echo "=== Running 'nanobot onboard' ==="
docker run --name "${RUN_CONTAINER_NAME}" "${IMAGE_NAME}" onboard

echo ""
echo "=== Running 'nanobot status' ==="
STATUS_OUTPUT=""
if ! STATUS_OUTPUT=$(docker commit "${RUN_CONTAINER_NAME}" "${ONBOARDED_IMAGE_NAME}" >/dev/null \
    && docker run --rm "${ONBOARDED_IMAGE_NAME}" status 2>&1); then
    echo "status command failed" >&2
fi

echo "$STATUS_OUTPUT"

echo ""
echo "=== Validating output ==="
PASS=true

check() {
    if echo "$STATUS_OUTPUT" | grep -q "$1"; then
        echo "  PASS: found '$1'"
    else
        echo "  FAIL: missing '$1'"
        PASS=false
    fi
}

check "nanobot Status"
check "Config:"
check "Workspace:"
check "Model:"
check "OpenRouter:"
check "Anthropic:"
check "OpenAI:"

echo ""
if [[ "$PASS" == "true" ]]; then
    echo "=== All checks passed ==="
else
    echo "=== Some checks FAILED ==="
    exit 1
fi
