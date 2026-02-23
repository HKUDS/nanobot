#!/usr/bin/env bash
# OKX Trade Skill - run.sh
# Usage: bash run.sh <command> [args...]
# Commands: balance, positions, ticker <inst_id>, order <inst_id> <side> <type> <size> [price], cancel <inst_id> <order_id>, history

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$SKILL_DIR/memory"
mkdir -p "$MEMORY_DIR"

LOG="$MEMORY_DIR/run.log"
RESULT="$MEMORY_DIR/last_result.json"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }

# Load secrets
SECRET_FILE="$SKILL_DIR/secret.env"
if [[ ! -f "$SECRET_FILE" ]]; then
  log "ERROR: secret.env not found at $SECRET_FILE"
  exit 1
fi
# shellcheck disable=SC1090
source "$SECRET_FILE"

# Load config
CONFIG_FILE="$SKILL_DIR/config.yaml"
IS_DEMO=$(grep '^is_demo:' "$CONFIG_FILE" | awk '{print $2}' | tr -d '[:space:]')
BASE_URL=$(grep '^base_url:' "$CONFIG_FILE" | awk '{print $2}' | tr -d '[:space:]')
IS_DEMO="${IS_DEMO:-true}"
BASE_URL="${BASE_URL:-https://www.okx.com}"

# Validate credentials
if [[ "$OKX_API_KEY" == "YOUR_OKX_API_KEY" || -z "$OKX_API_KEY" ]]; then
  log "ERROR: Please fill in your API credentials in secret.env"
  exit 1
fi

COMMAND="${1:-balance}"
shift || true

# Generate OKX signature via Python one-liner (avoids dependency on extra files)
sign_request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  python3 - "$OKX_SECRET_KEY" "$method" "$path" "$body" <<'PYEOF'
import sys, hmac, hashlib, base64
from datetime import datetime, timezone
secret, method, path, body = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
now = datetime.now(timezone.utc)
ts = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
prehash = ts + method + path + body
sig = base64.b64encode(hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
print(ts)
print(sig)
PYEOF
}

# Build curl headers for authenticated requests
auth_headers() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local out
  out=$(sign_request "$method" "$path" "$body")
  TS=$(echo "$out" | sed -n '1p')
  SIG=$(echo "$out" | sed -n '2p')
  DEMO_HEADER=""
  [[ "$IS_DEMO" == "true" ]] && DEMO_HEADER='-H "x-simulated-trading: 1"'
}

do_get() {
  local path="$1"
  auth_headers "GET" "$path"
  eval curl -s \
    -H '"Content-Type: application/json"' \
    -H '"OK-ACCESS-KEY: '"$OKX_API_KEY"'"' \
    -H '"OK-ACCESS-SIGN: '"$SIG"'"' \
    -H '"OK-ACCESS-TIMESTAMP: '"$TS"'"' \
    -H '"OK-ACCESS-PASSPHRASE: '"$OKX_PASSPHRASE"'"' \
    $DEMO_HEADER \
    '"'"$BASE_URL$path"'"'
}

do_post() {
  local path="$1"
  local body="$2"
  auth_headers "POST" "$path" "$body"
  eval curl -s -X POST \
    -H '"Content-Type: application/json"' \
    -H '"OK-ACCESS-KEY: '"$OKX_API_KEY"'"' \
    -H '"OK-ACCESS-SIGN: '"$SIG"'"' \
    -H '"OK-ACCESS-TIMESTAMP: '"$TS"'"' \
    -H '"OK-ACCESS-PASSPHRASE: '"$OKX_PASSPHRASE"'"' \
    $DEMO_HEADER \
    -d "'$body'" \
    '"'"$BASE_URL$path"'"'
}

case "$COMMAND" in
  balance)
    log "Getting account balance..."
    RESP=$(do_get "/api/v5/account/balance")
    echo "$RESP" | tee "$RESULT"
    log "Done."
    ;;

  positions)
    INST_TYPE="${1:-SWAP}"
    log "Getting positions (instType=$INST_TYPE)..."
    RESP=$(do_get "/api/v5/account/positions?instType=$INST_TYPE")
    echo "$RESP" | tee "$RESULT"
    log "Done."
    ;;

  ticker)
    INST_ID="${1:?Usage: run.sh ticker <inst_id>}"
    log "Getting ticker for $INST_ID..."
    RESP=$(do_get "/api/v5/market/ticker?instId=$INST_ID")
    echo "$RESP" | tee "$RESULT"
    log "Done."
    ;;

  order)
    INST_ID="${1:?Usage: run.sh order <inst_id> <side> <type> <size> [price]}"
    SIDE="${2:?missing side (buy/sell)}"
    ORD_TYPE="${3:?missing order type (market/limit)}"
    SIZE="${4:?missing size}"
    PRICE="${5:-}"
    BODY="{\"instId\":\"$INST_ID\",\"tdMode\":\"cross\",\"side\":\"$SIDE\",\"ordType\":\"$ORD_TYPE\",\"sz\":\"$SIZE\""
    [[ -n "$PRICE" ]] && BODY="$BODY,\"px\":\"$PRICE\""
    BODY="$BODY}"
    log "Placing order: $BODY"
    RESP=$(do_post "/api/v5/trade/order" "$BODY")
    echo "$RESP" | tee "$RESULT"
    log "Done."
    ;;

  cancel)
    INST_ID="${1:?Usage: run.sh cancel <inst_id> <order_id>}"
    ORDER_ID="${2:?missing order_id}"
    BODY="{\"instId\":\"$INST_ID\",\"ordId\":\"$ORDER_ID\"}"
    log "Cancelling order $ORDER_ID on $INST_ID..."
    RESP=$(do_post "/api/v5/trade/cancel-order" "$BODY")
    echo "$RESP" | tee "$RESULT"
    log "Done."
    ;;

  history)
    INST_TYPE="${1:-SWAP}"
    LIMIT="${2:-100}"
    log "Getting order history (instType=$INST_TYPE, limit=$LIMIT)..."
    RESP=$(do_get "/api/v5/trade/orders-history?instType=$INST_TYPE&limit=$LIMIT")
    echo "$RESP" | tee "$RESULT"
    log "Done."
    ;;

  *)
    echo "Unknown command: $COMMAND"
    echo "Commands: balance, positions [inst_type], ticker <inst_id>, order <inst_id> <side> <type> <size> [price], cancel <inst_id> <order_id>, history [inst_type] [limit]"
    exit 1
    ;;
esac
