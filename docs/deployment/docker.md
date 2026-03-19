# Docker Deployment Guide

This guide explains how to deploy nanobot using Docker or Docker Compose, which is ideal for isolated environments or quick server rollouts.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/) v2 (recommended)

## Docker Compose Quick Start

This is the recommended deployment method because it gives you full service management.

### First-time setup

```bash
# 1. Run the interactive onboarding wizard
docker compose run --rm nanobot-cli onboard

# 2. Edit the config file and add your API keys
vim ~/.nanobot/config.json

# 3. Start the gateway in the background
docker compose up -d nanobot-gateway
```

### Daily operations

```bash
# Run a one-off CLI agent
docker compose run --rm nanobot-cli agent -m "Hello!"

# Follow gateway logs
docker compose logs -f nanobot-gateway

# Stop everything
docker compose down

# Restart gateway after config changes
docker compose restart nanobot-gateway
```

## Docker Compose file breakdown

`docker-compose.yml` in the repo root defines two services:

```yaml
x-common-config: &common-config
  build:
    context: .
    dockerfile: Dockerfile
  volumes:
    - ~/.nanobot:/root/.nanobot   # Mounts the host config directory

services:
  nanobot-gateway:
    container_name: nanobot-gateway
    <<: *common-config
    command: ["gateway"]
    restart: unless-stopped       # Auto-restart when the container crashes
    ports:
      - 18790:18790               # Gateway default port
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 256M

  nanobot-cli:
    <<: *common-config
    profiles:
      - cli                       # Starts only when explicitly requested
    command: ["status"]
    stdin_open: true
    tty: true
```

### Multi-instance Docker Compose example

If you want to run multiple gateway instances (each targeting different channel sets):

```yaml
x-base: &base
  image: hkuds/nanobot:latest
  restart: unless-stopped

services:
  nanobot-telegram:
    <<: *base
    container_name: nanobot-telegram
    command: ["gateway", "--config", "/root/.nanobot-telegram/config.json"]
    ports:
      - "18790:18790"
    volumes:
      - ~/.nanobot-telegram:/root/.nanobot-telegram

  nanobot-discord:
    <<: *base
    container_name: nanobot-discord
    command: ["gateway", "--config", "/root/.nanobot-discord/config.json"]
    ports:
      - "18791:18790"
    volumes:
      - ~/.nanobot-discord:/root/.nanobot-discord

  nanobot-feishu:
    <<: *base
    container_name: nanobot-feishu
    command: ["gateway", "--config", "/root/.nanobot-feishu/config.json", "--port", "18792"]
    ports:
      - "18792:18792"
    volumes:
      - ~/.nanobot-feishu:/root/.nanobot-feishu
```

## Dockerfile structure

The repository `Dockerfile` uses layered caching:

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install Node.js 20 (for the WhatsApp bridge)
RUN apt-get update && apt-get install -y nodejs ...

WORKDIR /app

# Layer 1: Install Python dependencies only (benefits cache)
COPY pyproject.toml README.md LICENSE ./
RUN uv pip install --system --no-cache .

# Layer 2: Copy full source
COPY nanobot/ nanobot/
COPY bridge/ bridge/
RUN uv pip install --system --no-cache .

# Build WhatsApp Bridge
WORKDIR /app/bridge
RUN npm install && npm run build

WORKDIR /app
RUN mkdir -p /root/.nanobot

EXPOSE 18790           # Gateway default port

ENTRYPOINT ["nanobot"]
CMD ["status"]
```

**Caching tips:** Install dependencies before copying the full source so that Docker reuses the cached layer whenever the dependencies stay unchanged, speeding up rebuilds.

## Using Docker Hub image

You can pull a prebuilt image instead of building from scratch:

```bash
# Pull the latest image
docker pull hkuds/nanobot:latest

# Initialize config
docker run -v ~/.nanobot:/root/.nanobot --rm hkuds/nanobot onboard

# Start the gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 \
  --name nanobot-gateway \
  --restart unless-stopped \
  -d hkuds/nanobot gateway
```

## Build from source

```bash
# Clone the repository
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# Build the image
docker build -t nanobot .

# Initialize config
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# Edit the config on the host
vim ~/.nanobot/config.json

# Start the gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway
```

## Volume mounts

| Host path | Container path | Purpose |
|-----------|----------------|---------|
| `~/.nanobot` | `/root/.nanobot` | Config and workspace (required) |
| `~/.ssh` | `/root/.ssh` | SSH keys (if you run git commands) |
| `/custom/workspace` | `/root/.nanobot/workspace` | Custom workspace directory |

### Mount SSH keys example

```bash
docker run \
  -v ~/.nanobot:/root/.nanobot \
  -v ~/.ssh:/root/.ssh:ro \
  -p 18790:18790 \
  nanobot gateway
```

## Environment variables

Override config or pass API keys using env vars:

```bash
docker run \
  -v ~/.nanobot:/root/.nanobot \
  -p 18790:18790 \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  -e OPENAI_API_KEY=sk-xxx \
  nanobot gateway
```

In Docker Compose, load them from a `.env` file:

```yaml
# docker-compose.yml
services:
  nanobot-gateway:
    env_file:
      - .env
```

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-xxx
TELEGRAM_BOT_TOKEN=xxx
```

## Health checks

Add a health check to Docker Compose:

```yaml
services:
  nanobot-gateway:
    image: hkuds/nanobot:latest
    command: ["gateway"]
    healthcheck:
      test: ["CMD", "nanobot", "status"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    restart: unless-stopped
```

## Log management

### Follow live logs

```bash
# Docker Compose
docker compose logs -f nanobot-gateway

# Docker
docker logs -f nanobot-gateway
```

### Limit log size

Configure log rotation in Docker Compose:

```yaml
services:
  nanobot-gateway:
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
```

### Send logs to syslog

```yaml
services:
  nanobot-gateway:
    logging:
      driver: syslog
      options:
        syslog-address: "tcp://localhost:514"
        tag: "nanobot"
```

## FAQ

**The container exits immediately after starting**

```bash
# Inspect the exit reason
docker logs nanobot-gateway

# Ensure the config is valid
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

**Cannot reach the gateway port**

Verify the port mapping and any firewalls:

```bash
# Check whether the container is listening
docker inspect nanobot-gateway | grep -A 10 "Ports"
```

**Config changes do not take effect**

```bash
# Restart the gateway
docker compose restart nanobot-gateway
```
