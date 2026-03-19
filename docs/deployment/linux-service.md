# Linux systemd Service Guide

This guide explains how to register the nanobot Gateway as a systemd user service so it starts on login, restarts on failure, and integrates with system logs.

## Why use systemd?

- **Auto-start on login** — the gateway launches immediately after you log in
- **Auto-restart on crash** — systemd observes the process and restarts it on failure
- **System log integration** — view logs through `journalctl`
- **Standardized management** — control the service using familiar `systemctl` commands

## Prerequisites

### Confirm nanobot is installed

```bash
which nanobot
# Should output something like: /home/user/.local/bin/nanobot
```

If not found, install nanobot:

```bash
pip install nanobot-ai
# or use uv
uv pip install nanobot-ai
```

### Complete initial setup

```bash
nanobot onboard
# Follow the prompts to fill in API keys and channel configs
```

## Create the systemd user service

### Step 1: Confirm the nanobot path

```bash
which nanobot
# e.g.: /home/user/.local/bin/nanobot
```

### Step 2: Create the service directory

```bash
mkdir -p ~/.config/systemd/user
```

### Step 3: Create the service file

Write the following to `~/.config/systemd/user/nanobot-gateway.service` (adjust `ExecStart` if nanobot is installed elsewhere):

```ini
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

> **Note:** `%h` expands to the user home directory (`$HOME`).

### Step 4: Enable and start the service

```bash
# Reload systemd configuration
systemctl --user daemon-reload

# Enable and start the service immediately
systemctl --user enable --now nanobot-gateway
```

## Common management commands

```bash
# Check service status
systemctl --user status nanobot-gateway

# Start the service
systemctl --user start nanobot-gateway

# Stop the service
systemctl --user stop nanobot-gateway

# Restart after config changes
systemctl --user restart nanobot-gateway

# Disable auto-start (but leave it running)
systemctl --user disable nanobot-gateway
```

## View logs

```bash
# Follow live logs
journalctl --user -u nanobot-gateway -f

# Read the last 100 lines
journalctl --user -u nanobot-gateway -n 100

# Logs since today
journalctl --user -u nanobot-gateway --since today

# Logs for a specific time range
journalctl --user -u nanobot-gateway --since "2026-01-01 09:00" --until "2026-01-01 18:00"

# Output logs as JSON for analysis
journalctl --user -u nanobot-gateway -o json
```

## Modify the service file

If you need to change the port or config path, edit the service file and reload systemd:

```bash
# Edit the service file
vim ~/.config/systemd/user/nanobot-gateway.service

# Reload systemd
systemctl --user daemon-reload

# Restart the service
systemctl --user restart nanobot-gateway
```

## Keep it running after logout

By default, user services only run while you are logged in. Enable lingering to keep nanobot alive after logout (useful on servers):

```bash
loginctl enable-linger $USER
```

Verify the setting:

```bash
loginctl show-user $USER | grep Linger
# Linger=yes
```

## Multiple instances

Run multiple nanobot gateways for different channels by creating additional service files.

### Telegram instance

```ini
# ~/.config/systemd/user/nanobot-telegram.service
[Unit]
Description=Nanobot Gateway (Telegram)
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway --config %h/.nanobot-telegram/config.json
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

### Discord instance

```ini
# ~/.config/systemd/user/nanobot-discord.service
[Unit]
Description=Nanobot Gateway (Discord)
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway --config %h/.nanobot-discord/config.json --port 18791
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

Enable both instances:

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-telegram
systemctl --user enable --now nanobot-discord
```

## Full service example (with env vars)

```ini
[Unit]
Description=Nanobot Gateway
Documentation=https://github.com/HKUDS/nanobot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

# Adjust the exec path if needed
ExecStart=%h/.local/bin/nanobot gateway

# Environment variables (optional — can be stored in config.json)
# Environment=ANTHROPIC_API_KEY=sk-ant-xxx
# Environment=TELEGRAM_BOT_TOKEN=xxx

Restart=always
RestartSec=10

NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

## Set environment variables

Two options:

**Option 1: Put them directly in config.json (recommended)**

```bash
vim ~/.nanobot/config.json
# Add your API keys to the config
```

**Option 2: Use an EnvironmentFile**

```ini
[Service]
EnvironmentFile=%h/.nanobot/nanobot.env
ExecStart=%h/.local/bin/nanobot gateway
```

```bash
# ~/.nanobot/nanobot.env
ANTHROPIC_API_KEY=sk-ant-xxx
TELEGRAM_BOT_TOKEN=xxx
```

## Troubleshooting

**Service fails to start**

```bash
# View the latest error logs
journalctl --user -u nanobot-gateway -n 50

# Test the command manually
/home/user/.local/bin/nanobot gateway
```

**Service keeps restarting**

```bash
# Check restart reason
systemctl --user status nanobot-gateway
journalctl --user -u nanobot-gateway --since "5 minutes ago"
```

**Binary not found**

```bash
# Confirm the install path
which nanobot
pip show nanobot-ai | grep Location

# Use the absolute path in ExecStart
ExecStart=/full/path/to/nanobot gateway
```
