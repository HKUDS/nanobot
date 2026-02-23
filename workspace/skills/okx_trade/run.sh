#!/usr/bin/env bash
# OKX Trade Skill - run.sh
# Usage:
#   bash run.sh <command> [args...]
#   ACTION=positions bash run.sh
# Commands: balance, positions [inst_type], ticker <inst_id>,
#           order <inst_id> <side> <type> <size> [price],
#           cancel <inst_id> <order_id>, history [inst_type] [limit]

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$SKILL_DIR/memory"
mkdir -p "$MEMORY_DIR"

LOG="$MEMORY_DIR/run.log"
log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }

# Load secrets
source "$SKILL_DIR/secret.env"

# Load config
CONFIG_FILE="$SKILL_DIR/config.yaml"
IS_DEMO=$(grep '^is_demo:' "$CONFIG_FILE" | awk '{print $2}' | tr -d '[:space:]')
BASE_URL=$(grep '^base_url:' "$CONFIG_FILE" | awk '{print $2}' | tr -d '[:space:]')
IS_DEMO="${IS_DEMO:-true}"
BASE_URL="${BASE_URL:-https://www.okx.com}"

# Validate credentials
if [[ -z "${OKX_API_KEY:-}" || "$OKX_API_KEY" == "YOUR_OKX_API_KEY" ]]; then
  log "ERROR: Please fill in your API credentials in secret.env"
  exit 1
fi

# Support ACTION env var or positional $1
COMMAND="${ACTION:-${1:-balance}}"
[[ $# -gt 0 ]] && shift || true

# Generate ISO 8601 timestamp (OKX requirement)
mk_ts() {
  python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+'Z')"
}

# Sign: HMAC-SHA256(secret, timestamp+METHOD+path+body) → base64
# Uses openssl — no Python file dependency
sign() {
  local ts="$1" method="$2" path="$3" body="${4:-}"
  printf '%s' "${ts}${method}${path}${body}" \
    | openssl dgst -sha256 -hmac "$OKX_SECRET_KEY" -binary \
    | base64
}

do_get() {
  local path="$1"
  local ts sig
  ts=$(mk_ts)
  sig=$(sign "$ts" "GET" "$path")
  local demo_flag=()
  [[ "$IS_DEMO" == "true" ]] && demo_flag=(-H "x-simulated-trading: 1")
  curl -s \
    -H "Content-Type: application/json" \
    -H "OK-ACCESS-KEY: $OKX_API_KEY" \
    -H "OK-ACCESS-SIGN: $sig" \
    -H "OK-ACCESS-TIMESTAMP: $ts" \
    -H "OK-ACCESS-PASSPHRASE: $OKX_PASSPHRASE" \
    "${demo_flag[@]}" \
    "$BASE_URL$path"
}

do_post() {
  local path="$1" body="$2"
  local ts sig
  ts=$(mk_ts)
  sig=$(sign "$ts" "POST" "$path" "$body")
  local demo_flag=()
  [[ "$IS_DEMO" == "true" ]] && demo_flag=(-H "x-simulated-trading: 1")
  curl -s -X POST \
    -H "Content-Type: application/json" \
    -H "OK-ACCESS-KEY: $OKX_API_KEY" \
    -H "OK-ACCESS-SIGN: $sig" \
    -H "OK-ACCESS-TIMESTAMP: $ts" \
    -H "OK-ACCESS-PASSPHRASE: $OKX_PASSPHRASE" \
    "${demo_flag[@]}" \
    -d "$body" \
    "$BASE_URL$path"
}

save() {
  local name="$1" resp="$2"
  echo "$resp" | tee "$MEMORY_DIR/${name}.json"
  local code
  code=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code','?'))" 2>/dev/null || echo "?")
  if [[ "$code" == "0" ]]; then
    log "OK → memory/${name}.json"
  else
    log "FAILED (code=$code) → memory/${name}.json"
    echo "$resp" >> "$MEMORY_DIR/trade_error.log"
  fi
}

case "$COMMAND" in
  balance)
    log "Getting account balance..."
    save "balance_result" "$(do_get "/api/v5/account/balance")"
    ;;

  positions)
    INST_TYPE="${1:-SWAP}"
    log "Getting positions (instType=$INST_TYPE)..."
    save "positions_result" "$(do_get "/api/v5/account/positions?instType=$INST_TYPE")"
    ;;

  ticker)
    INST_ID="${1:?Usage: run.sh ticker <inst_id>}"
    log "Getting ticker for $INST_ID..."
    save "ticker_result" "$(do_get "/api/v5/market/ticker?instId=$INST_ID")"
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
    save "order_result" "$(do_post "/api/v5/trade/order" "$BODY")"
    ;;

  cancel)
    INST_ID="${1:?Usage: run.sh cancel <inst_id> <order_id>}"
    ORDER_ID="${2:?missing order_id}"
    BODY="{\"instId\":\"$INST_ID\",\"ordId\":\"$ORDER_ID\"}"
    log "Cancelling order $ORDER_ID on $INST_ID..."
    save "cancel_result" "$(do_post "/api/v5/trade/cancel-order" "$BODY")"
    ;;

  history)
    INST_TYPE="${1:-SWAP}"
    LIMIT="${2:-100}"
    log "Getting order history (instType=$INST_TYPE, limit=$LIMIT)..."
    save "history_result" "$(do_get "/api/v5/trade/orders-history?instType=$INST_TYPE&limit=$LIMIT")"
    ;;

  *)
    echo "Unknown command: $COMMAND"
    echo "Commands: balance, positions [inst_type], ticker <inst_id>,"
    echo "          order <inst_id> <side> <type> <size> [price],"
    echo "          cancel <inst_id> <order_id>, history [inst_type] [limit]"
    exit 1
    ;;
esac
