#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

RUN_ID="$$-${RANDOM}"
IMAGE_NAME="nanobot-test-${RUN_ID}"
CONTAINER_NAME="nanobot-test-run-${RUN_ID}"
ONBOARDED_IMAGE="nanobot-test-onboarded-${RUN_ID}"

cleanup() {
    result=$?
    trap - EXIT
    echo ""
    echo "=== Cleanup ==="
    docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1 || true
    docker rmi -f "$ONBOARDED_IMAGE" "$IMAGE_NAME" > /dev/null 2>&1 || true
    exit "$result"
}
trap cleanup EXIT

echo "=== Building Docker image ==="
docker build -t "$IMAGE_NAME" .

echo ""
echo "=== Running 'nanobot onboard' ==="
docker run --name "$CONTAINER_NAME" "$IMAGE_NAME" onboard

echo ""
echo "=== Running 'nanobot status' ==="
docker commit "$CONTAINER_NAME" "$ONBOARDED_IMAGE" > /dev/null
if STATUS_OUTPUT=$(docker run --rm "$ONBOARDED_IMAGE" status 2>&1); then
    echo "$STATUS_OUTPUT"
else
    result=$?
    echo "$STATUS_OUTPUT"
    exit "$result"
fi

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
check "OpenRouter API:"
check "Anthropic API:"
check "OpenAI API:"

echo ""
if $PASS; then
    echo "=== All checks passed ==="
else
    echo "=== Some checks FAILED ==="
    exit 1
fi

echo "Done."
