#!/bin/bash
set -euo pipefail

# ==============================================================================
# nanobot Setup Script for Raspberry Pi 4 (4GB RAM)
#
# This script automates the deployment of nanobot on a Raspberry Pi 4.
# It handles:
#   1. System optimization (Swap check for 4GB RAM)
#   2. Dependency installation (Docker)
#   3. Building the application
#   4. Configuration setup
#   5. Container lifecycle management
#
# RPi Specific Notes:
#   - Base image: python3.12-bookworm-slim (supports arm64)
#   - Node.js: Nodesource repo (supports arm64)
#   - Swap: Recommended 2GB for 4GB RAM to be safe during builds
# ==============================================================================

# Colors for user-friendly output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}   nanobot Setup (Raspberry Pi 4)       ${NC}"
echo -e "${GREEN}=========================================${NC}"

# ------------------------------------------------------------------------------
# STEP 0: Swap Check
# ------------------------------------------------------------------------------
# Why: 4GB RAM is minimal for modern AI applications. Docker builds and package
#      installs can spike memory usage. A 2GB swap file ensures stability.
# ------------------------------------------------------------------------------

# Check if dphys-swapfile exists (default on RPi OS)
if command -v dphys-swapfile &> /dev/null; then
    echo -e "${YELLOW}Checking swap configuration...${NC}"
    
    # Get current swap size (grep from config or check free)
    # Note: dphys-swapfile usually reads /etc/dphys-swapfile. We'll check actual free swap.
    SWAP_SIZE=$(free -m | grep Swap | awk '{print $2}')
    
    # Recommended swap for 4GB RAM is 2GB (2048MB)
    RECOMMENDED_SWAP=1900  # Slight buffer
    
    if [ "$SWAP_SIZE" -lt "$RECOMMENDED_SWAP" ]; then
        echo -e "${YELLOW}Swap size is ${SWAP_SIZE}MB. Recommended 2GB for smooth Docker builds.${NC}"
        echo -e "${YELLOW}We can update /etc/dphys-swapfile for you.${NC}"
        
        # Ask user
        read -p "Update swap to 2GB? (y/N) " response
        if [[ "$response" =~ ^([yY][eE][sS]|[yY])+$ ]]; then
            echo -e "${YELLOW}Updating /etc/dphys-swapfile...${NC}"
            # Backup
            sudo cp /etc/dphys-swapfile /etc/dphys-swapfile.bak
            # Replace CONF_SWAPSIZE line or append it
            if grep -q "^CONF_SWAPSIZE" /etc/dphys-swapfile; then
                sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
            else
                echo "CONF_SWAPSIZE=2048" | sudo tee -a /etc/dphys-swapfile
            fi
            
            # Apply
            echo -e "${YELLOW}Applying swap changes (this may take a moment)...${NC}"
            sudo /etc/init.d/dphys-swapfile restart
            echo -e "${GREEN}Swap updated.${NC}"
        else
            echo -e "${YELLOW}Skipping swap update. Builds might fail if RAM runs out.${NC}"
        fi
    else
        echo -e "${GREEN}Swap size is ${SWAP_SIZE}MB (good)${NC}"
    fi
else
    echo -e "${YELLOW}dphys-swapfile not found. Skipping swap check.${NC}"
    echo -e "${YELLOW}If you experience OOM errors, manually add a swap file:${NC}"
    echo -e "  sudo fallocate -l 2G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
fi

# Fix ownership: the container runs as uid 1000 (nanobot), so all files
# in the config dir must be writable by that uid. On Raspberry Pi OS the
# default "pi" user is also uid 1000, but files created by earlier runs
# (or the onboard container running as root) may be owned by root.
echo -e "${YELLOW}Ensuring correct file ownership in $CONFIG_DIR...${NC}"
sudo chown -R $(id -u):$(id -g) "$CONFIG_DIR"

# ------------------------------------------------------------------------------
# STEP 1: Docker Installation
# ------------------------------------------------------------------------------
# Why: Docker ensures the app runs in a consistent environment, regardless of your
#      OS version. It isolates dependencies.
# ------------------------------------------------------------------------------
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker not found. Installing Docker...${NC}"

    # Download official Docker installation script
    curl -fsSL https://get.docker.com -o get-docker.sh
    # Execute script
    sh get-docker.sh
    rm get-docker.sh
    echo -e "${GREEN}Docker installed successfully.${NC}"

    # Add current user to 'docker' group to avoid needing 'sudo' for every command
    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}Adding current user to docker group...${NC}"
        sudo usermod -aG docker $USER
        echo -e "${RED}Please log out and log back in for group changes to take effect.${NC}"
        echo -e "${RED}Then run this script again.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}Docker is already installed.${NC}"
fi

# Fix ownership: the container runs as uid 1000 (nanobot), so all files
# in the config dir must be writable by that uid. On Raspberry Pi OS the
# default "pi" user is also uid 1000, but files created by earlier runs
# (or the onboard container running as root) may be owned by root.
echo -e "${YELLOW}Ensuring correct file ownership in $CONFIG_DIR...${NC}"
sudo chown -R $(id -u):$(id -g) "$CONFIG_DIR"

# ------------------------------------------------------------------------------
# STEP 2: Build Docker Image
# ------------------------------------------------------------------------------
# Why: Creates a self-contained image named 'nanobot' from the source code.
# This compiles Python dependencies defined in pyproject.toml.
# ------------------------------------------------------------------------------
echo -e "${YELLOW}Building nanobot Docker image...${NC}"
docker build --no-cache -t nanobot .

# ------------------------------------------------------------------------------
# STEP 3: Configuration Setup
# ------------------------------------------------------------------------------
# Why: We need a persistent place to store API keys and conversation history
# that survives container restarts. We use ~/.nanobot on the host.
# ------------------------------------------------------------------------------
CONFIG_DIR="$HOME/.nanobot"
mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config.json" ]; then
    echo -e "${YELLOW}Config not found. Initializing...${NC}"

    # Run 'onboard' command inside a temporary container to generate default config
    docker run --rm -v "$CONFIG_DIR:/home/nanobot/.nanobot" nanobot onboard

    # Pause to let the user add their API keys manually
    echo -e "${YELLOW}IMPORTANT: Please edit $CONFIG_DIR/config.json to add your API keys.${NC}"
    echo -e "${YELLOW}Example:${NC}"
    echo -e '  "providers": { "openrouter": { "apiKey": "sk-..." } }'
    read -p "Press Enter when you have configured your API keys (or Ctrl+C to stop)..."
else
    echo -e "${GREEN}Configuration found at $CONFIG_DIR${NC}"
fi

# Fix ownership: the container runs as uid 1000 (nanobot), so all files
# in the config dir must be writable by that uid. On Raspberry Pi OS the
# default "pi" user is also uid 1000, but files created by earlier runs
# (or the onboard container running as root) may be owned by root.
echo -e "${YELLOW}Ensuring correct file ownership in $CONFIG_DIR...${NC}"
sudo chown -R $(id -u):$(id -g) "$CONFIG_DIR"

# ------------------------------------------------------------------------------
# STEP 4: Cleanup Old Containers
# ------------------------------------------------------------------------------
# Why: Avoid port conflicts (Address already in use) by removing any previous instance.
# ------------------------------------------------------------------------------
if [ "$(docker ps -aq -f name=nanobot)" ]; then
    echo -e "${YELLOW}Stopping and removing existing nanobot container...${NC}"
    docker stop nanobot >/dev/null 2>&1 || true
    docker rm nanobot >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------------------
# STEP 5: Run Production Container
# ------------------------------------------------------------------------------
# Flags explanation:
#   -d                  : Detached mode (run in background)
#   --name nanobot      : Name the container for easy management
#   --restart always    : Auto-restart if it crashes or Pi reboots
#   -p 18790:18790      : Expose port for webhooks/API
#   -v ...              : Mount config dir so data persists
# ------------------------------------------------------------------------------
echo -e "${YELLOW}Starting nanobot gateway...${NC}"
docker run -d \
  --name nanobot \
  --restart always \
  -p 18790:18790 \
  -v "$CONFIG_DIR:/home/nanobot/.nanobot" \
  nanobot gateway

# ------------------------------------------------------------------------------
# STEP 6: Verification
# ------------------------------------------------------------------------------
# Why: Confirm everything worked and show useful info to the user.
# ------------------------------------------------------------------------------
if [ "$(docker ps -q -f name=nanobot)" ]; then
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}   Deployment Successful!                ${NC}"
    echo -e "${GREEN}=========================================${NC}"
    echo -e "Container ID: $(docker ps -q -f name=nanobot)"
    echo -e "Status:       $(docker ps -f name=nanobot --format '{{.Status}}')"
    echo -e "Logs:         docker logs nanobot"
    echo -e "Config:       $CONFIG_DIR/config.json"
    echo -e ""
    echo -e "${YELLOW}Tip: Check logs with: docker logs -f nanobot${NC}"
else
    echo -e "${RED}Deployment failed. Container is not running.${NC}"
    docker logs nanobot
    exit 1
fi

# Fix ownership: the container runs as uid 1000 (nanobot), so all files
# in the config dir must be writable by that uid. On Raspberry Pi OS the
# default "pi" user is also uid 1000, but files created by earlier runs
# (or the onboard container running as root) may be owned by root.
echo -e "${YELLOW}Ensuring correct file ownership in $CONFIG_DIR...${NC}"
sudo chown -R $(id -u):$(id -g) "$CONFIG_DIR"
