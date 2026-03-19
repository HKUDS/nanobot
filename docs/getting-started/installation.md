# Installation Guide

This page explains how to install nanobot on your system, covering multiple installation methods and common troubleshooting.

---

## System Requirements

| Requirement | Version |
|------|------|
| **Python** | 3.11 or newer |
| **Operating System** | macOS, Linux, Windows (WSL recommended) |
| **uv** (recommended) | Latest version |
| **Node.js** (optional) | ≥18, required only for WhatsApp channel |

!!! tip "Check Python version"
    ```bash
    python3 --version
    # Should output Python 3.11.x or newer
    ```

---

## Install uv (Recommended)

[uv](https://github.com/astral-sh/uv) is the package manager recommended by nanobot, and it is extremely fast.

=== "macOS / Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

=== "pip"

    ```bash
    pip install uv
    ```

After installation, reopen your terminal and verify:

```bash
uv --version
```

---

## Install nanobot

### Method 1: Using uv (Recommended)

```bash
uv tool install nanobot-ai
```

This is the fastest installation method. nanobot is installed as an independent CLI tool.

**Upgrade to latest version:**

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

### Method 2: Using pip

```bash
pip install nanobot-ai
```

**Upgrade to latest version:**

```bash
pip install -U nanobot-ai
nanobot --version
```

### Method 3: Install from source (Recommended for developers)

Suitable for users who want the latest features or want to contribute.

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
uv sync
```

!!! note "Run from source"
    After source installation, use `uv run nanobot` instead of directly typing `nanobot`:
    ```bash
    uv run nanobot --version
    uv run nanobot onboard
    uv run nanobot agent
    ```

---

## Install with Docker

Do not want to install a local Python environment? You can use Docker.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) is installed and running

### Method 1: Docker Compose (Recommended)

```bash
# Clone repository
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# Initialize configuration (first run)
docker compose run --rm nanobot-cli onboard

# Edit config and add API keys
vim ~/.nanobot/config.json

# Start gateway
docker compose up -d nanobot-gateway
```

Common Docker Compose commands:

```bash
# Run CLI chat
docker compose run --rm nanobot-cli agent -m "Hello!"

# View gateway logs
docker compose logs -f nanobot-gateway

# Stop gateway
docker compose down
```

### Method 2: Use Docker directly

```bash
# Build image
docker build -t nanobot .

# Initialize configuration (first run)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# Edit configuration
vim ~/.nanobot/config.json

# Start gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# Or run one-off CLI commands
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

!!! tip "Data persistence"
    The `-v ~/.nanobot:/root/.nanobot` flag mounts your local config directory into the container so config and workspace remain after container restarts.

!!! note "Interactive OAuth login in Docker"
    If you need interactive OAuth login (e.g., OpenAI Codex), add the `-it` flag:
    ```bash
    docker run -it -v ~/.nanobot:/root/.nanobot --rm nanobot provider login openai-codex
    ```

---

## Install Optional Dependencies

Some channels require additional dependencies:

| Channel | Install Command |
|------|----------|
| **Matrix** | `pip install nanobot-ai[matrix]` |
| **WeCom** | `pip install nanobot-ai[wecom]` |
| **WhatsApp** | Requires Node.js ≥18; running `nanobot channels login` installs bridge automatically |

---

## Verify Installation

After installation, run the following command to verify:

```bash
nanobot --version
```

Expected output example:

```
nanobot 0.1.4.post5
```

Then try checking status:

```bash
nanobot status
```

If installation is correct, you will see an overview of current configuration status.

---

## Common Installation Issues

### `nanobot: command not found`

**Cause:** After `uv tool install`, `~/.local/bin` is not yet in `PATH`.

**Fix:**

```bash
# Add the following to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"

# Reload config
source ~/.bashrc   # or source ~/.zshrc
```

### Python version mismatch

**Error message:** `requires Python >=3.11`

**Fix:** Install Python 3.11+. [pyenv](https://github.com/pyenv/pyenv) is recommended:

```bash
pyenv install 3.11
pyenv global 3.11
```

### pip permission issue (Linux / macOS)

**Fix:** Add `--user` or use a virtual environment:

```bash
pip install --user nanobot-ai
```

Or create a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install nanobot-ai
```

### WhatsApp bridge build failed

**Cause:** Node.js is too old or not installed.

**Fix:**

```bash
# Check Node.js version (requires ≥18)
node --version

# Rebuild bridge
rm -rf ~/.nanobot/bridge
nanobot channels login
```

### SSL certificate errors (corporate network / proxy)

**Fix:** Configure proxy in `~/.nanobot/config.json`:

```json
{
  "tools": {
    "web": {
      "proxy": "http://your-proxy:7890"
    }
  }
}
```

---

## Next Step

After installation, go to [Quick Start](quick-start.md) to complete your first nanobot setup in 5 minutes.