#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# nanobot VPN skill — manage OpenVPN connections via tmux
# ============================================================================

PROFILE_DIR="${NANOBOT_VPN_DIR:-$HOME/.openvpn}"
SOCKET="/tmp/nanobot-vpn.sock"
OPENVPN="${OPENVPN_BIN:-openvpn}"

usage() {
  cat <<'EOF'
Usage: vpn.sh <command> [args]

Commands:
  list                       List available VPN profiles
  connect <profile>          Start VPN connection (prompts OTP)
  otp <profile> <code>       Send OTP code to waiting connection
  status [profile]           Check connection status
  disconnect <profile>       Disconnect VPN
EOF
  exit 1
}

# ---- helpers ---------------------------------------------------------------

session_name() { echo "vpn-$1"; }

profile_path() {
  local name="$1"
  local ovpn="$PROFILE_DIR/${name}.ovpn"
  if [[ ! -f "$ovpn" ]]; then
    echo "Error: profile '$name' not found at $ovpn" >&2
    exit 1
  fi
  echo "$ovpn"
}

auth_path() {
  local auth="$PROFILE_DIR/${1}.auth"
  [[ -f "$auth" ]] && echo "$auth" || echo ""
}

session_exists() {
  tmux -S "$SOCKET" has-session -t "$(session_name "$1")" 2>/dev/null
}

capture_output() {
  tmux -S "$SOCKET" capture-pane -p -J -t "$(session_name "$1"):0.0" -S -100 2>/dev/null || echo ""
}

has_static_challenge() {
  grep -qi "static-challenge" "$1" 2>/dev/null
}

# ---- commands --------------------------------------------------------------

cmd_list() {
  if [[ ! -d "$PROFILE_DIR" ]]; then
    echo "No profile directory found at $PROFILE_DIR"
    echo "Create it with: mkdir -p $PROFILE_DIR"
    exit 0
  fi

  local found=0
  echo "Available VPN profiles ($PROFILE_DIR):"
  echo ""
  for f in "$PROFILE_DIR"/*.ovpn; do
    [[ -f "$f" ]] || continue
    found=1
    local name
    name=$(basename "$f" .ovpn)
    local auth=""
    [[ -f "$PROFILE_DIR/${name}.auth" ]] && auth=" [has credentials]"
    local server
    server=$(grep -m1 "^remote " "$f" | awk '{print $2 ":" $3}' || echo "?")
    local challenge=""
    has_static_challenge "$f" && challenge=" [OTP: separate]" || challenge=" [OTP: concat]"

    # Check if currently connected
    local status_icon="○"
    if session_exists "$name"; then
      local output
      output=$(capture_output "$name")
      if echo "$output" | grep -q "Initialization Sequence Completed"; then
        status_icon="●"
      else
        status_icon="◐"
      fi
    fi

    echo "  $status_icon $name — $server$auth$challenge"
  done

  if [[ $found -eq 0 ]]; then
    echo "  (none)"
    echo ""
    echo "Copy .ovpn files to $PROFILE_DIR:"
    echo "  cp your-profile.ovpn $PROFILE_DIR/work.ovpn"
  fi

  echo ""
  echo "Legend: ● connected  ◐ connecting  ○ disconnected"
}

cmd_connect() {
  local name="$1"
  local ovpn
  ovpn=$(profile_path "$name")
  local sess
  sess=$(session_name "$name")

  # Kill existing session if any
  if session_exists "$name"; then
    echo "Disconnecting existing $name session..."
    tmux -S "$SOCKET" kill-session -t "$sess" 2>/dev/null || true
    sleep 1
  fi

  # Build openvpn command
  local cmd="sudo $OPENVPN --config '$ovpn'"
  local auth
  auth=$(auth_path "$name")
  if [[ -n "$auth" ]]; then
    cmd="$cmd --auth-user-pass '$auth'"
  fi

  # Start in tmux
  tmux -S "$SOCKET" new-session -d -s "$sess" -n vpn
  tmux -S "$SOCKET" send-keys -t "$sess:0.0" "$cmd" Enter

  echo "VPN '$name' starting in tmux session '$sess'"
  echo ""

  # Wait a moment for prompts to appear
  sleep 2

  local output
  output=$(capture_output "$name")

  # Check what the connection is waiting for
  if echo "$output" | grep -qi "CHALLENGE"; then
    echo "Status: Waiting for OTP code"
    echo "→ Please provide your OTP code, then run:"
    echo "  vpn.sh otp $name <code>"
  elif echo "$output" | grep -qi "Enter Auth Username"; then
    echo "Status: Waiting for username"
    echo "→ No .auth file found. Enter credentials manually:"
    echo "  tmux -S $SOCKET attach -t $sess"
  elif echo "$output" | grep -q "Initialization Sequence Completed"; then
    echo "Status: Connected!"
  else
    echo "Status: Starting... (may need OTP shortly)"
    echo "→ Check status with: vpn.sh status $name"
  fi

  echo ""
  echo "Monitor: tmux -S $SOCKET attach -t $sess"
}

cmd_otp() {
  local name="$1"
  local code="$2"
  local sess
  sess=$(session_name "$name")

  if ! session_exists "$name"; then
    echo "Error: no active session for '$name'. Run 'vpn.sh connect $name' first."
    exit 1
  fi

  # Send the OTP code
  tmux -S "$SOCKET" send-keys -t "$sess:0.0" -l "$code"
  tmux -S "$SOCKET" send-keys -t "$sess:0.0" Enter

  echo "OTP sent to '$name'. Checking connection..."
  sleep 3

  cmd_status "$name"
}

cmd_status() {
  local name="${1:-}"

  # If no name, show all active sessions
  if [[ -z "$name" ]]; then
    if ! tmux -S "$SOCKET" list-sessions 2>/dev/null; then
      echo "No active VPN sessions"
    fi
    return
  fi

  local sess
  sess=$(session_name "$name")

  if ! session_exists "$name"; then
    echo "$name: disconnected (no session)"
    return
  fi

  local output
  output=$(capture_output "$name")

  if echo "$output" | grep -q "Initialization Sequence Completed"; then
    # Extract assigned IP
    local ip
    ip=$(echo "$output" | grep -oE "ifconfig [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | tail -1 | awk '{print $2}')
    echo "$name: ● connected${ip:+ (IP: $ip)}"
  elif echo "$output" | grep -qi "CHALLENGE\|Enter.*Code\|Authenticator"; then
    echo "$name: ◐ waiting for OTP"
  elif echo "$output" | grep -qi "AUTH_FAILED\|auth-failure"; then
    echo "$name: ✗ authentication failed"
  elif echo "$output" | grep -qi "error\|fatal\|SIGTERM"; then
    echo "$name: ✗ error (check logs)"
    echo ""
    echo "Recent output:"
    echo "$output" | tail -10
  else
    echo "$name: ◐ connecting..."
  fi
}

cmd_disconnect() {
  local name="$1"
  local sess
  sess=$(session_name "$name")

  if ! session_exists "$name"; then
    echo "$name: already disconnected"
    return
  fi

  # Send Ctrl+C to gracefully stop openvpn, then kill session
  tmux -S "$SOCKET" send-keys -t "$sess:0.0" C-c
  sleep 2
  tmux -S "$SOCKET" kill-session -t "$sess" 2>/dev/null || true
  echo "$name: disconnected"
}

# ---- main ------------------------------------------------------------------

[[ $# -lt 1 ]] && usage

case "$1" in
  list)       cmd_list ;;
  connect)    [[ $# -lt 2 ]] && usage; cmd_connect "$2" ;;
  otp)        [[ $# -lt 3 ]] && usage; cmd_otp "$2" "$3" ;;
  status)     cmd_status "${2:-}" ;;
  disconnect) [[ $# -lt 2 ]] && usage; cmd_disconnect "$2" ;;
  *)          usage ;;
esac
