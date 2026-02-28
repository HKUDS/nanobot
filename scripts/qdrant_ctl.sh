#!/usr/bin/env bash
set -euo pipefail

QDRANT_DIR="${QDRANT_DIR:-$HOME/.nanobot/qdrant}"
DATA_DIR="${DATA_DIR:-$QDRANT_DIR/data}"
LOG_FILE="${LOG_FILE:-$QDRANT_DIR/qdrant.log}"
PID_FILE="${PID_FILE:-$QDRANT_DIR/qdrant.pid}"
BIN="${BIN:-$QDRANT_DIR/qdrant}"
CFG="${CFG:-$QDRANT_DIR/simple_config.yaml}"
API_URL="${API_URL:-http://localhost:6333/collections}"

start() {
  echo "Starting Qdrant..."
  mkdir -p "$DATA_DIR"

  [[ -x "$BIN" ]] || { echo "Error: binary not executable: $BIN"; exit 1; }
  [[ -f "$CFG" ]] || { echo "Error: config not found: $CFG"; exit 1; }

  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Qdrant already running (PID: $pid)"
      status
      return 0
    fi
    echo "Removing stale PID file"
    rm -f "$PID_FILE"
  fi

  cd "$QDRANT_DIR"
  nohup "$BIN" --config-path "$CFG" > "$LOG_FILE" 2>&1 &
  local pid="$!"
  echo "$pid" > "$PID_FILE"

  sleep 2
  if curl -fsS --max-time 3 "$API_URL" >/dev/null; then
    echo "Qdrant ready (PID: $pid)"
  else
    echo "Qdrant started (PID: $pid), still warming up. Log: $LOG_FILE"
  fi
}

stop() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "PID file not found. Qdrant may not be running."
    return 0
  fi

  local pid
  pid="$(cat "$PID_FILE")"

  if ! kill -0 "$pid" 2>/dev/null; then
    echo "Process $pid not running. Removing stale PID file."
    rm -f "$PID_FILE"
    return 0
  fi

  echo "Stopping Qdrant (PID: $pid)..."
  kill "$pid"

  for _ in {1..15}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "Qdrant stopped."
      return 0
    fi
    sleep 0.2
  done

  echo "Graceful stop timeout. Forcing kill -9 $pid"
  kill -9 "$pid" || true
  rm -f "$PID_FILE"
  echo "Qdrant force-stopped."
}

status() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Qdrant running (PID: $pid)"
    else
      echo "Qdrant not running (stale PID file)"
    fi
  else
    echo "Qdrant not running (no PID file)"
  fi

  if curl -fsS --max-time 2 "$API_URL" >/dev/null; then
    echo "API reachable: $API_URL"
    echo "Dashboard: http://localhost:6333/dashboard"
  else
    echo "API not reachable"
  fi
}

restart() {
  stop
  start
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  restart) restart ;;
  *)
    echo "Usage: $0 {start|stop|status|restart}"
    exit 1
    ;;
esac
