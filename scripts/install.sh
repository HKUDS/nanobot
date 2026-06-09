#!/bin/sh
set -eu

package="nanobot-ai"
main_source="https://github.com/HKUDS/nanobot/archive/refs/heads/main.zip"
install_target="$package"
install_source="PyPI"
dry_run="0"

info() {
  printf '%s\n' "$*"
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

install_failure_hint() {
  printf '%s\n' "Error: pip could not install nanobot from $install_source." >&2
  printf '%s\n' "If pip mentioned externally-managed-environment, install in a virtual environment or use uv/pipx." >&2
  printf '%s\n' "You can also run manually:" >&2
  printf '  %s\n' "$python_bin -m pip install --upgrade $install_target" >&2
  printf '%s\n' "Then start setup with:" >&2
  printf '  %s\n' "$python_bin -m nanobot onboard --wizard" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: install.sh [--dev] [--dry-run]

By default this installs or upgrades nanobot-ai from PyPI.
Use --dev to install from the current main branch on GitHub.
Use --dry-run to print what would happen without installing or starting the wizard.
EOF
}

find_python() {
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
      then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dev)
      install_target="$main_source"
      install_source="GitHub main"
      ;;
    --dry-run)
      dry_run="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
  shift
done

python_bin="${PYTHON:-}"

if [ -n "$python_bin" ]; then
  command -v "$python_bin" >/dev/null 2>&1 || fail "PYTHON=$python_bin was not found"
  "$python_bin" - <<'PY' >/dev/null 2>&1 || fail "nanobot requires Python 3.11 or newer"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
else
  python_bin="$(find_python)" || fail "Python 3.11 or newer was not found. Install Python first, then rerun this command."
fi

info "Using Python: $("$python_bin" --version 2>&1)"

if ! "$python_bin" -m pip --version >/dev/null 2>&1; then
  if [ "$dry_run" = "1" ]; then
    info "Dry run: pip was not found. Install would try: $python_bin -m ensurepip --upgrade"
  else
    info "pip was not found for this Python. Trying ensurepip..."
    "$python_bin" -m ensurepip --upgrade >/dev/null 2>&1 || fail "pip is not available. Install pip for $python_bin, then rerun this command."
  fi
fi

if [ "$dry_run" = "1" ]; then
  info "Dry run: would install or upgrade nanobot from $install_source."
  info "Dry run: would run: $python_bin -m pip install --upgrade $install_target"
  info "Dry run: if that fails because system site-packages are not writable, would retry: $python_bin -m pip install --user --upgrade $install_target"
  if [ "${NANOBOT_SKIP_WIZARD:-}" = "1" ]; then
    info "Dry run: would skip setup wizard because NANOBOT_SKIP_WIZARD=1."
  else
    info "Dry run: would run: $python_bin -m nanobot onboard --wizard"
  fi
  info "Dry run: no changes made."
  exit 0
fi

info "Installing or upgrading nanobot from $install_source..."
if ! "$python_bin" -m pip install --upgrade "$install_target"; then
  info "Install failed. Retrying as a user install..."
  "$python_bin" -m pip install --user --upgrade "$install_target" || install_failure_hint
fi

info "Installed nanobot:"
"$python_bin" -m nanobot --version

if [ "${NANOBOT_SKIP_WIZARD:-}" = "1" ]; then
  info "Skipping setup wizard because NANOBOT_SKIP_WIZARD=1."
  info "Run this later: $python_bin -m nanobot onboard --wizard"
  exit 0
fi

info "Starting setup wizard..."
"$python_bin" -m nanobot onboard --wizard

info "Done. Try: $python_bin -m nanobot agent -m \"Hello!\""
