#!/bin/bash
# ============================================================================
# nanobot Installer (PyPI Only) - Virtual Environment Only
# ============================================================================
# Installs nanobot in a dedicated virtual environment.
# Automatically installs Python 3.14 if Python 3.11+ is not found.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/HKUDS/nanobot/main/scripts/install.sh | bash
#   curl -fsSL ... | bash -s -- --tuna
#
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
NANOBOT_HOME="${NANOBOT_HOME:-$HOME/.nanobot}"
MIN_REQUIRED_VERSION="3.11"  # Minimum version to check for
INSTALL_VERSION="3.14"        # Version to install if missing
TUNA_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

# Options
USE_TUNA_MIRROR=false
FORCE_TUNA=false

# ============================================================================
# Helper functions
# ============================================================================

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    cat << 'EOF'
┌─────────────────────────────────────────────────────────┐
│        🐈 nanobot Virtual Environment Installer        │
├─────────────────────────────────────────────────────────┤
│   Installs in ~/.nanobot/venv                          │
│   Python 3.11+ required                               │
└─────────────────────────────────────────────────────────┘
EOF
    echo -e "${NC}"
}

log_info() { echo -e "${CYAN}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

# Check if version >= required
version_ge() {
    printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

# ============================================================================
# Python installation and management
# ============================================================================

install_python_314() {
    log_info "Installing Python $INSTALL_VERSION..."
    
    case "$(uname -s)" in
        Linux*)
            install_python_linux
            ;;
        Darwin*)
            install_python_macos
            ;;
        *)
            log_error "Automatic Python installation not supported on this OS"
            echo "Please install Python $INSTALL_VERSION manually from:"
            echo "  https://www.python.org/downloads/"
            exit 1
            ;;
    esac
    
    # Verify installation
    if command -v python3.14 &> /dev/null; then
        PYTHON_PATH="$(command -v python3.14)"
        version=$("$PYTHON_PATH" --version 2>/dev/null)
        log_success "Installed: $version"
    elif command -v python3 &> /dev/null && python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)" 2>/dev/null; then
        PYTHON_PATH="$(command -v python3)"
        version=$("$PYTHON_PATH" --version 2>/dev/null)
        log_success "Using: $version"
    else
        log_error "Python $INSTALL_VERSION installation may have failed"
        exit 1
    fi
}

install_python_linux() {
    case "$(grep -E '^ID=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"')" in
        ubuntu|debian)
            log_info "Installing Python $INSTALL_VERSION on Ubuntu/Debian..."
            
            # Add deadsnakes PPA for newer Python versions
            sudo apt-get update
            sudo apt-get install -y software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt-get update
            sudo apt-get install -y "python${INSTALL_VERSION}" "python${INSTALL_VERSION}-venv" "python${INSTALL_VERSION}-dev"
            
            # Create python3.14 symlink if needed
            if [ ! -f "/usr/bin/python3.14" ] && [ -f "/usr/bin/python${INSTALL_VERSION}" ]; then
                sudo ln -sf "/usr/bin/python${INSTALL_VERSION}" "/usr/bin/python3.14"
            fi
            ;;
        
        fedora|rhel|centos)
            log_info "Installing Python $INSTALL_VERSION on Fedora/RHEL..."
            
            if command -v dnf &> /dev/null; then
                sudo dnf install -y "python${INSTALL_VERSION}" "python${INSTALL_VERSION}-devel"
            elif command -v yum &> /dev/null; then
                sudo yum install -y "python${INSTALL_VERSION}" "python${INSTALL_VERSION}-devel"
            fi
            ;;
        
        arch|manjaro)
            log_info "Installing Python on Arch Linux..."
            sudo pacman -S --noconfirm python python-pip
            ;;
        
        *)
            log_error "Unsupported Linux distribution for automatic Python installation"
            show_python_install_help
            exit 1
            ;;
    esac
}

install_python_macos() {
    log_info "Installing Python $INSTALL_VERSION on macOS..."
    
    if command -v brew &> /dev/null; then
        brew install "python@${INSTALL_VERSION}"
        
        # Add Python 3.14 to PATH
        if [ -f "/opt/homebrew/bin/python${INSTALL_VERSION}" ]; then
            ln -sf "/opt/homebrew/bin/python${INSTALL_VERSION}" "/usr/local/bin/python3.14" 2>/dev/null || true
        elif [ -f "/usr/local/bin/python${INSTALL_VERSION}" ]; then
            ln -sf "/usr/local/bin/python${INSTALL_VERSION}" "/usr/local/bin/python3.14" 2>/dev/null || true
        fi
    else
        log_error "Homebrew not found. Please install Homebrew first:"
        echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "Then run: brew install python@${INSTALL_VERSION}"
        exit 1
    fi
}

check_and_install_python() {
    log_info "Checking Python version (requires 3.11+)..."
    
    local python_cmd=""
    local found_version=""
    
    # Try to find suitable Python in order: 3.14, 3.13, 3.12, 3.11, generic
    for cmd in python3.14 python3.13 python3.12 python3.11 python3 python; do
        if command -v "$cmd" &> /dev/null; then
            python_cmd="$cmd"
            found_version=$("$python_cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
            
            if version_ge "$found_version" "$MIN_REQUIRED_VERSION"; then
                PYTHON_PATH="$(command -v "$python_cmd")"
                log_success "Found Python $found_version ($python_cmd)"
                return 0
            fi
        fi
    done
    
    # No suitable Python found
    if [ -n "$found_version" ]; then
        log_error "Python $found_version is too old (requires $MIN_REQUIRED_VERSION+)"
    else
        log_error "No Python installation found"
    fi
    
    # Always install Python 3.14 automatically
    echo ""
    log_info "Python $MIN_REQUIRED_VERSION+ is required for nanobot"
    log_info "Installing Python $INSTALL_VERSION..."
    
    install_python_314
}

show_python_install_help() {
    echo ""
    echo "Please install Python $MIN_REQUIRED_VERSION or higher manually:"
    echo ""
    case "$(uname -s)" in
        Linux*)
            echo "  Ubuntu/Debian:"
            echo "    sudo apt update"
            echo "    sudo apt install python3.14 python3.14-venv python3.14-dev"
            echo ""
            echo "  Or use deadsnakes PPA:"
            echo "    sudo add-apt-repository ppa:deadsnakes/ppa"
            echo "    sudo apt update"
            echo "    sudo apt install python3.14"
            echo ""
            echo "  Fedora/RHEL:"
            echo "    sudo dnf install python3.14 python3.14-devel"
            ;;
        Darwin*)
            echo "  Using Homebrew:"
            echo "    brew install python@3.14"
            echo ""
            echo "  Or download installer:"
            echo "    https://www.python.org/downloads/"
            ;;
        *)
            echo "  Download from: https://www.python.org/downloads/"
            ;;
    esac
    echo ""
    echo "After installation, re-run this script."
    echo ""
}

# ============================================================================
# Detection functions
# ============================================================================

detect_china_region() {
    # Simple detection for China region
    local detected=false
    
    # Method 1: Check timezone
    if command -v timedatectl &> /dev/null; then
        if timedatectl show | grep -qi "Asia/Shanghai\|Asia/Chongqing\|Asia/Harbin"; then
            detected=true
        fi
    fi
    
    echo "$detected"
}

# ============================================================================
# Mirror configuration (called AFTER Python is installed)
# ============================================================================

configure_mirror() {
    if [ "$USE_TUNA_MIRROR" = true ] || [ "$FORCE_TUNA" = true ]; then
        export PIP_INDEX_URL="$TUNA_MIRROR"
        export PIP_EXTRA_INDEX_URL="https://pypi.org/simple"
        log_info "Using TUNA mirror: $TUNA_MIRROR"
    fi
    
    # Respect user's environment variable
    if [ -n "$PIP_INDEX_URL" ]; then
        log_info "Using custom mirror: $PIP_INDEX_URL"
    fi
}

# ============================================================================
# Virtual environment installation
# ============================================================================

create_virtual_environment() {
    log_info "Creating virtual environment at ~/.nanobot/venv..."
    
    # Remove existing venv if it exists
    if [ -d "$NANOBOT_HOME/venv" ]; then
        log_info "Removing existing virtual environment..."
        rm -rf "$NANOBOT_HOME/venv"
    fi
    
    # Create virtual environment
    "$PYTHON_PATH" -m venv "$NANOBOT_HOME/venv" 2>/dev/null || {
        log_error "Failed to create virtual environment"
        echo "Try: $PYTHON_PATH -m ensurepip --upgrade"
        exit 1
    }
    
    log_success "Virtual environment created"
}

install_nanobot_in_venv() {
    log_info "Installing nanobot in virtual environment..."
    
    export VIRTUAL_ENV="$NANOBOT_HOME/venv"
    VENV_PYTHON="$VIRTUAL_ENV/bin/python"
    VENV_PIP="$VIRTUAL_ENV/bin/pip"
    
    # Upgrade pip
    log_info "Upgrading pip..."
    "$VENV_PIP" install --upgrade pip setuptools wheel >/dev/null 2>&1
    
    # Install nanobot
    if [ -n "$PIP_INDEX_URL" ]; then
        log_info "Installing with mirror..."
        "$VENV_PIP" install nanobot --index-url "$PIP_INDEX_URL" >/dev/null 2>&1
    else
        log_info "Installing from official PyPI..."
        "$VENV_PIP" install nanobot >/dev/null 2>&1
    fi
    
    NANOBOT_BIN="$VIRTUAL_ENV/bin/nanobot"
    
    # Verify installation
    if [ -x "$NANOBOT_BIN" ]; then
        local version
        version=$("$NANOBOT_BIN" --version 2>/dev/null || echo "unknown")
        log_success "nanobot $version installed"
    else
        log_error "nanobot installation failed"
        exit 1
    fi
}

create_command_symlink() {
    log_info "Creating command symlink..."
    
    local link_dir="$HOME/.local/bin"
    mkdir -p "$link_dir"
    
    if [ -x "$NANOBOT_BIN" ]; then
        ln -sf "$NANOBOT_BIN" "$link_dir/nanobot" 2>/dev/null || true
        log_success "Command linked: $link_dir/nanobot"
        
        # Check if in PATH
        if [[ ":$PATH:" != *":$link_dir:"* ]]; then
            echo ""
            log_warn "Add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
    fi
}

# ============================================================================
# Main function
# ============================================================================

main() {
    print_banner
    
    # Parse arguments
    for arg in "$@"; do
        case "$arg" in
            --tuna)
                USE_TUNA_MIRROR=true
                FORCE_TUNA=true
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
        esac
    done
    
    # Step 1: Check and install Python first
    check_and_install_python
    
    # Step 2: Detect China region AFTER Python is installed
    if [ "$FORCE_TUNA" = false ]; then
        if detect_china_region; then
            USE_TUNA_MIRROR=true
            log_info "China region detected, using TUNA mirror"
        fi
    fi
    
    # Step 3: Configure PyPI mirror
    configure_mirror
    
    # Step 4: Install nanobot in virtual environment
    create_virtual_environment
    install_nanobot_in_venv
    create_command_symlink
    
    show_success_message
}

show_help() {
    cat << 'EOF'
nanobot Virtual Environment Installer

Usage:
  ./install.sh [OPTIONS]

Options:
  --tuna        Use TUNA mirror (pypi.tuna.tsinghua.edu.cn)
  -h, --help    Show this help message

Environment Variables:
  PIP_INDEX_URL Custom PyPI mirror URL
  NANOBOT_HOME  Data directory (default: ~/.nanobot)

Examples:
  ./install.sh --tuna
  PIP_INDEX_URL=https://mirror.example.com/simple ./install.sh
EOF
}

show_success_message() {
    echo ""
    echo -e "${GREEN}${BOLD}"
    cat << 'EOF'
┌─────────────────────────────────────────────────────────┐
│    ✓ nanobot Installation Complete!                     │
└─────────────────────────────────────────────────────────┘
EOF
    echo -e "${NC}"
    echo ""
    echo -e "${CYAN}📁 Installation Summary:${NC}"
    echo "  Virtual Environment: ~/.nanobot/venv/"
    echo "  nanobot Command:     ~/.local/bin/nanobot"
    echo ""
    
    echo -e "${CYAN}🚀 Next Steps:${NC}"
    echo "  1. Configure nanobot:"
    echo "     nanobot onboard"
    echo ""
    echo "  2. Start using nanobot:"
    echo "     nanobot                 # Start CLI chat"
    echo "     nanobot gateway         # Start message gateway"
    echo ""
    
    echo -e "${CYAN}🔧 Virtual Environment Management:${NC}"
    echo "  Activate: source ~/.nanobot/venv/bin/activate"
    echo "  Deactivate: deactivate"
    echo ""
    
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        echo -e "${YELLOW}⚠  PATH Setup:${NC}"
        echo "  Add to your shell configuration:"
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
    fi
    
    echo -e "${CYAN}💡 Quick Test:${NC}"
    echo "  ~/.nanobot/venv/bin/nanobot --version"
    echo ""
}

# Execute
main "$@"
