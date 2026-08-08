#!/usr/bin/env bash
#
# Build nanobot desktop app (PyInstaller sidecar + Tauri bundle)
#
# Usage:
#   ./scripts/build-desktop.sh          # Build for current platform
#   ./scripts/build-desktop.sh --dev    # Tauri dev mode (skip PyInstaller)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$SCRIPT_DIR/.."
DESKTOP_DIR="$ROOT/apps/desktop"
BINARIES_DIR="$DESKTOP_DIR/src-tauri/binaries"

# Detect platform triple
PLATFORM=$(rustc -vV 2>/dev/null | grep '^host:' | awk '{print $2}')
if [ -z "$PLATFORM" ]; then
    echo "Error: rustc not found. Install Rust from https://rustup.rs"
    exit 1
fi

echo "=========================================="
echo "  nanobot Desktop Build"
echo "  Platform: $PLATFORM"
echo "=========================================="

# ── Step 1: Build PyInstaller binary ──
if [ "${1:-}" != "--dev" ]; then
    echo ""
    echo "[1/3] Building nanobot gateway binary with PyInstaller..."

    cd "$ROOT"

    # Ensure PyInstaller is installed
    if ! command -v pyinstaller &>/dev/null; then
        echo "  Installing PyInstaller..."
        pip install pyinstaller
    fi

    # Ensure nanobot is installed
    if ! python -c "import nanobot" &>/dev/null 2>&1; then
        echo "  Installing nanobot..."
        pip install -e .
    fi

    # Build
    pyinstaller scripts/nanobot-gateway.spec \
        --distpath "$BINARIES_DIR" \
        --workpath "$ROOT/build/pyinstaller" \
        --noconfirm

    # Rename with platform triple (Tauri sidecar naming convention)
    BINARY_NAME="nanobot-gateway"
    if [[ "$PLATFORM" == *"windows"* ]]; then
        mv "$BINARIES_DIR/$BINARY_NAME.exe" "$BINARIES_DIR/$BINARY_NAME-$PLATFORM.exe"
        echo "  Built: $BINARIES_DIR/$BINARY_NAME-$PLATFORM.exe"
    else
        mv "$BINARIES_DIR/$BINARY_NAME" "$BINARIES_DIR/$BINARY_NAME-$PLATFORM"
        chmod +x "$BINARIES_DIR/$BINARY_NAME-$PLATFORM"
        echo "  Built: $BINARIES_DIR/$BINARY_NAME-$PLATFORM"
    fi
else
    echo ""
    echo "[1/3] Skipping PyInstaller (dev mode)"
fi

# ── Step 2: Install Tauri dependencies ──
echo ""
echo "[2/3] Installing Tauri dependencies..."

cd "$DESKTOP_DIR"

if command -v pnpm &>/dev/null; then
    pnpm install
elif command -v npm &>/dev/null; then
    npm install
else
    echo "Error: pnpm or npm not found."
    exit 1
fi

# ── Step 3: Build Tauri app ──
echo ""
if [ "${1:-}" = "--dev" ]; then
    echo "[3/3] Starting Tauri dev mode..."
    npx tauri dev
else
    echo "[3/3] Building Tauri app..."
    npx tauri build

    echo ""
    echo "=========================================="
    echo "  Build Complete!"
    echo "=========================================="
    echo ""
    echo "Output location:"
    if [[ "$PLATFORM" == *"darwin"* ]]; then
        echo "  DMG: $DESKTOP_DIR/src-tauri/target/release/bundle/dmg/"
        echo "  App: $DESKTOP_DIR/src-tauri/target/release/bundle/macos/"
    elif [[ "$PLATFORM" == *"windows"* ]]; then
        echo "  NSIS: $DESKTOP_DIR/src-tauri/target/release/bundle/nsis/"
    fi
fi
