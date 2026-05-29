#!/bin/sh
set -eu

telegram_state="${NANOBOT_TELEGRAM_HEALTH_PATH:-/tmp/nanobot-telegram-health.json}"
runtime_state="${NANOBOT_RUNTIME_HEALTH_PATH:-/tmp/nanobot-runtime-health.json}"
telegram_max_age="${NANOBOT_TELEGRAM_HEALTH_MAX_AGE_S:-120}"
agent_tick_max_age="${NANOBOT_RUNTIME_HEALTH_AGENT_MAX_AGE_S:-180}"
dispatch_max_age="${NANOBOT_RUNTIME_HEALTH_DISPATCH_MAX_AGE_S:-900}"
send_max_age="${NANOBOT_RUNTIME_HEALTH_SEND_MAX_AGE_S:-180}"

cmdline="${NANOBOT_HEALTHCHECK_CMDLINE:-}"
if [ -z "$cmdline" ]; then
  cmdline="$(tr '\000' ' ' < /proc/1/cmdline 2>/dev/null || true)"
fi
case " $cmdline " in
  *" gateway "*|*" /gateway "*) ;;
  *)
    echo "healthy: nanobot is not running in gateway mode"
    exit 0
    ;;
esac

config_path="${NANOBOT_HEALTHCHECK_CONFIG_PATH:-}"
if [ -z "$config_path" ]; then
  set -- $cmdline
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --config|-c)
        shift
        config_path="${1:-}"
        break
        ;;
      --config=*)
        config_path="${1#--config=}"
        break
        ;;
    esac
    shift || break
  done
fi
config_path="${config_path:-$HOME/.nanobot/config.json}"

telegram_enabled=0
if [ -r "$config_path" ]; then
  compact_config="$(tr -d '[:space:]' < "$config_path")"
  if printf '%s' "$compact_config" | grep -q '"telegram":{[^}]*"enabled":true'; then
    telegram_enabled=1
  fi
fi

json_number() {
  key="$1"
  file="$2"
  sed -n 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*\([0-9][0-9.]*\).*/\1/p' "$file" 2>/dev/null | tail -n 1
}

json_string() {
  key="$1"
  file="$2"
  sed -n 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$file" 2>/dev/null | tail -n 1
}

age_gt() {
  timestamp="$1"
  max_age="$2"
  [ -n "$timestamp" ] || return 0
  now="$(date +%s)"
  awk -v now="$now" -v ts="$timestamp" -v max="$max_age" 'BEGIN { exit !((now - ts) > max) }'
}

if [ "$telegram_enabled" -eq 1 ]; then
  if [ ! -r "$telegram_state" ]; then
    echo "unhealthy: telegram polling state file is missing or unreadable: $telegram_state"
    exit 1
  fi
  last_ok="$(json_number last_ok "$telegram_state")"
  if [ -z "$last_ok" ]; then
    echo "unhealthy: telegram polling has not reported a successful cycle yet: $telegram_state"
    exit 1
  fi
  if age_gt "$last_ok" "$telegram_max_age"; then
    detail="$(json_string last_error "$telegram_state")"
    [ -n "$detail" ] || detail="$(json_string detail "$telegram_state")"
    [ -n "$detail" ] || detail="stale"
    echo "unhealthy: telegram polling is stale ($detail)"
    exit 1
  fi
fi

if [ ! -r "$runtime_state" ]; then
  echo "unhealthy: runtime health state file is missing or unreadable: $runtime_state"
  exit 1
fi

last_tick="$(json_number last_agent_tick "$runtime_state")"
if [ -z "$last_tick" ]; then
  echo "unhealthy: agent loop has not reported a tick yet: $runtime_state"
  exit 1
fi
if age_gt "$last_tick" "$agent_tick_max_age"; then
  echo "unhealthy: agent loop tick is stale"
  exit 1
fi

active_dispatches="$(json_number active_dispatches "$runtime_state")"
oldest_dispatch="$(json_number oldest_dispatch_started_at "$runtime_state")"
if [ "${active_dispatches:-0}" -gt 0 ] && age_gt "$oldest_dispatch" "$dispatch_max_age"; then
  echo "unhealthy: message dispatch has been active too long"
  exit 1
fi

outbound_active="$(json_number outbound_active "$runtime_state")"
send_started="$(json_number outbound_send_started_at "$runtime_state")"
if [ "${outbound_active:-0}" -gt 0 ] && age_gt "$send_started" "$send_max_age"; then
  echo "unhealthy: outbound send has been active too long"
  exit 1
fi

echo "healthy: telegram polling and gateway pipeline are fresh"
exit 0
