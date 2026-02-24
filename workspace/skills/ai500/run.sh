#!/usr/bin/env bash
# NOFX AI500 Skill - run.sh
# Usage:
#   bash run.sh <command> [args...]
# Commands:
#   ai500-list                        AI500 high-potential coins (score > 70)
#   ai500 <symbol>                    AI analytics for a specific pair
#   ai500-stats                       AI500 index statistics
#   ai300-list                        AI300 quantitative model ranking
#   ai300-stats                       AI300 model statistics
#   oi-top [duration]                 OI largest increase ranking
#   oi-low [duration]                 OI largest decrease ranking
#   netflow-top [type] [duration]     Net capital inflow ranking (type: Institutional|Personal)
#   netflow-low [type] [duration]     Net capital outflow ranking
#   price-ranking [duration] [order]  Price gainers/losers (order: desc|asc)
#   coin <symbol>                     Comprehensive data for a single coin
#   long-short-list                   Abnormal long-short ratio signals
#   long-short <symbol>               Long-short ratio history
#   funding-top                       Highest positive funding rates
#   funding-low                       Lowest negative funding rates
#   funding <symbol>                  Funding rate for a symbol
#   oi-cap                            OI market cap ranking
#   upbit-hot                         Upbit hot coins by volume
#   upbit-netflow-top                 Upbit net inflow ranking
#   upbit-netflow-low                 Upbit net outflow ranking
#   heatmap-future <symbol>           Futures order book heatmap
#   heatmap-spot <symbol>             Spot order book heatmap
#   heatmap-list                      Heatmap overview all coins
#   query-rank                        Most queried coins today

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$SKILL_DIR/memory"
mkdir -p "$MEMORY_DIR"

LOG="$MEMORY_DIR/run.log"
log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }

# Load secrets
source "$SKILL_DIR/secret.env"

# Load config
BASE_URL=$(grep '^base_url:' "$SKILL_DIR/config.yaml" | awk '{print $2}' | tr -d '[:space:]')
BASE_URL="${BASE_URL:-https://nofxos.ai}"

# Validate
if [[ -z "${NOFX_API_KEY:-}" || "$NOFX_API_KEY" == "YOUR_NOFX_API_KEY" ]]; then
  log "ERROR: Please fill in NOFX_API_KEY in secret.env"
  exit 1
fi

COMMAND="${1:-ai500-list}"
shift || true

get() {
  local path="$1"
  local sep="?"
  [[ "$path" == *"?"* ]] && sep="&"
  curl -s "${BASE_URL}${path}${sep}auth=${NOFX_API_KEY}"
}

save() {
  local name="$1" resp="$2"
  local out="$MEMORY_DIR/${name}.json"
  echo "$resp" | tee "$out"
  local ok
  ok=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print('true' if d.get('success') else 'false')" 2>/dev/null || echo "?")
  if [[ "$ok" == "true" ]]; then
    log "OK → memory/${name}.json"
  else
    log "FAILED → memory/${name}.json"
    echo "$resp" >> "$MEMORY_DIR/error.log"
  fi
}

case "$COMMAND" in
  ai500-list)
    log "Getting AI500 list..."
    save "ai500_list" "$(get "/api/ai500/list")"
    ;;

  ai500)
    SYMBOL="${1:?Usage: run.sh ai500 <symbol>}"
    log "Getting AI500 data for $SYMBOL..."
    save "ai500_${SYMBOL}" "$(get "/api/ai500/${SYMBOL}")"
    ;;

  ai500-stats)
    log "Getting AI500 stats..."
    save "ai500_stats" "$(get "/api/ai500/stats")"
    ;;

  ai300-list)
    log "Getting AI300 list..."
    save "ai300_list" "$(get "/api/ai300/list")"
    ;;

  ai300-stats)
    log "Getting AI300 stats..."
    save "ai300_stats" "$(get "/api/ai300/stats")"
    ;;

  oi-top)
    DURATION="${1:-1h}"
    log "Getting OI top ranking (duration=$DURATION)..."
    save "oi_top" "$(get "/api/oi/top-ranking?duration=${DURATION}")"
    ;;

  oi-low)
    DURATION="${1:-1h}"
    log "Getting OI low ranking (duration=$DURATION)..."
    save "oi_low" "$(get "/api/oi/low-ranking?duration=${DURATION}")"
    ;;

  netflow-top)
    TYPE="${1:-Institutional}"
    DURATION="${2:-1h}"
    log "Getting netflow top ranking (type=$TYPE, duration=$DURATION)..."
    save "netflow_top" "$(get "/api/netflow/top-ranking?type=${TYPE}&duration=${DURATION}")"
    ;;

  netflow-low)
    TYPE="${1:-Institutional}"
    DURATION="${2:-1h}"
    log "Getting netflow low ranking (type=$TYPE, duration=$DURATION)..."
    save "netflow_low" "$(get "/api/netflow/low-ranking?type=${TYPE}&duration=${DURATION}")"
    ;;

  price-ranking)
    DURATION="${1:-1h}"
    ORDER="${2:-desc}"
    log "Getting price ranking (duration=$DURATION, order=$ORDER)..."
    save "price_ranking" "$(get "/api/price/ranking?duration=${DURATION}&order=${ORDER}")"
    ;;

  coin)
    SYMBOL="${1:?Usage: run.sh coin <symbol>}"
    log "Getting comprehensive data for $SYMBOL..."
    save "coin_${SYMBOL}" "$(get "/api/coin/${SYMBOL}")"
    ;;

  long-short-list)
    log "Getting long-short ratio signals..."
    save "long_short_list" "$(get "/api/long-short/list")"
    ;;

  long-short)
    SYMBOL="${1:?Usage: run.sh long-short <symbol>}"
    log "Getting long-short history for $SYMBOL..."
    save "long_short_${SYMBOL}" "$(get "/api/long-short/${SYMBOL}")"
    ;;

  funding-top)
    log "Getting highest funding rates..."
    save "funding_top" "$(get "/api/funding-rate/top")"
    ;;

  funding-low)
    log "Getting lowest funding rates..."
    save "funding_low" "$(get "/api/funding-rate/low")"
    ;;

  funding)
    SYMBOL="${1:?Usage: run.sh funding <symbol>}"
    log "Getting funding rate for $SYMBOL..."
    save "funding_${SYMBOL}" "$(get "/api/funding-rate/${SYMBOL}")"
    ;;

  oi-cap)
    log "Getting OI market cap ranking..."
    save "oi_cap" "$(get "/api/oi-cap/ranking")"
    ;;

  upbit-hot)
    log "Getting Upbit hot coins..."
    save "upbit_hot" "$(get "/api/upbit/hot")"
    ;;

  upbit-netflow-top)
    log "Getting Upbit netflow top ranking..."
    save "upbit_netflow_top" "$(get "/api/upbit/netflow/top-ranking")"
    ;;

  upbit-netflow-low)
    log "Getting Upbit netflow low ranking..."
    save "upbit_netflow_low" "$(get "/api/upbit/netflow/low-ranking")"
    ;;

  heatmap-future)
    SYMBOL="${1:?Usage: run.sh heatmap-future <symbol>}"
    log "Getting futures heatmap for $SYMBOL..."
    save "heatmap_future_${SYMBOL}" "$(get "/api/heatmap/future/${SYMBOL}")"
    ;;

  heatmap-spot)
    SYMBOL="${1:?Usage: run.sh heatmap-spot <symbol>}"
    log "Getting spot heatmap for $SYMBOL..."
    save "heatmap_spot_${SYMBOL}" "$(get "/api/heatmap/spot/${SYMBOL}")"
    ;;

  heatmap-list)
    log "Getting heatmap overview..."
    save "heatmap_list" "$(get "/api/heatmap/list")"
    ;;

  query-rank)
    log "Getting query rank list..."
    save "query_rank" "$(get "/api/query-rank/list")"
    ;;

  *)
    echo "Unknown command: $COMMAND"
    echo "Run 'bash run.sh' without args to see usage."
    exit 1
    ;;
esac
