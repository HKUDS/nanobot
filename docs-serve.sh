#!/bin/bash
# Nanobot Documentation Helper Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv-docs"

# Setup virtual environment if needed
setup() {
  if [ ! -d "$VENV_DIR" ]; then
    echo "Creating docs virtual environment..."
    uv venv "$VENV_DIR" --python 3.11
    echo "Installing dependencies..."
    source "$VENV_DIR/bin/activate"
    uv pip install -r "$SCRIPT_DIR/docs-requirements.txt" -q
    echo "Setup complete!"
  fi
}

case "${1:-serve}" in
serve | s)
  setup
  echo "Starting docs server at http://127.0.0.1:8000"
  cd "$SCRIPT_DIR" && "$VENV_DIR/bin/mkdocs" serve
  ;;
build | b)
  setup
  echo "Building documentation..."
  cd "$SCRIPT_DIR" && "$VENV_DIR/bin/mkdocs" build
  echo "Documentation built in ./site/"
  ;;
install | i)
  setup
  ;;
clean | c)
  rm -rf "$SCRIPT_DIR/site"
  echo "Cleaned build output"
  ;;
*)
  echo "Usage: $0 [serve|build|install|clean]"
  echo "  serve   - Start development server (default)"
  echo "  build   - Build static site to ./site/"
  echo "  install - Install dependencies only"
  echo "  clean   - Remove build output"
  ;;
esac
