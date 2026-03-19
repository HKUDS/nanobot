# Multi-Instance Guide

Nanobot supports running multiple isolated instances simultaneously. Each instance keeps its own config file, workspace, scheduled tasks, and runtime state so they never interfere with one another.

---

## Why Multiple Instances?

| Scenario | Description |
|----------|-------------|
| **Different platforms** | Use one instance for work (Slack + WeCom) and another for personal chats (Telegram + Discord) |
| **Different models** | Let one instance run Claude for complex workflows while another uses a local Ollama model |
| **Different workspaces** | Give each team or project its own workspace directory and memory | 
| **Different safety boundaries** | Production instance enables `restrictToWorkspace` while testing instance stays open |
| **Different schedules** | Maintain separate Cron task lists for each instance |

---

## Path Resolution Rules

All runtime data for an instance derives from its config file path:

| Component | Source | Example |
|-----------|--------|---------|
| **Config** | `--config` flag | `~/.nanobot-work/config.json` |
| **Workspace** | `--workspace` flag, or `agents.defaults.workspace` in the config | `~/.nanobot-work/workspace/` |
| **Scheduled tasks** | Directory containing the config file | `~/.nanobot-work/cron/` |
| **Media & runtime state** | Directory containing the config file | `~/.nanobot-work/media/` |

> [!NOTE]
> `--config` selects which config file to load. The workspace is read from `agents.defaults.workspace` inside that config by default. Pass `--workspace` to temporarily override the workspace without editing the config.

---

## Quick Start

### 1. Create configs and workspaces for each instance

Use `nanobot onboard` while specifying both config and workspace paths:

```bash
# Work instance
nanobot onboard --config ~/.nanobot-work/config.json \
                --workspace ~/.nanobot-work/workspace

# Personal instance
nanobot onboard --config ~/.nanobot-personal/config.json \
                --workspace ~/.nanobot-personal/workspace
```

The onboarding wizard writes the workspace path back into each config so you rarely need to re-specify it.

### 2. Edit each config separately

Open `~/.nanobot-work/config.json` and `~/.nanobot-personal/config.json` to fill in different channel credentials and models.

### 3. Start all instances simultaneously

```bash
# Work instance (default port 18790)
nanobot gateway --config ~/.nanobot-work/config.json

# Personal instance on a different port
nanobot gateway --config ~/.nanobot-personal/config.json --port 18791
```

---

## Example: Work + Personal Instances

### Work config (`~/.nanobot-work/config.json`)

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot-work/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "maxToolIterations": 40
    }
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": true,
    "slack": {
      "enabled": true,
      "botToken": "xoxb-WORK-BOT-TOKEN",
      "appToken": "xapp-WORK-APP-TOKEN",
      "allowFrom": ["U01234567", "U07654321"]
    },
    "wecom": {
      "enabled": true,
      "corpId": "YOUR_CORP_ID",
      "corpSecret": "YOUR_CORP_SECRET",
      "agentId": 1000001,
      "allowFrom": ["zhangsan", "lisi"]
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-work-key"
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  },
  "tools": {
    "restrictToWorkspace": true,
    "exec": {
      "timeout": 60
    },
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "BSA-BRAVE-KEY"
      }
    }
  }
}
```

### Personal config (`~/.nanobot-personal/config.json`)

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot-personal/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192
    }
  },
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "telegram": {
      "enabled": true,
      "token": "TELEGRAM-BOT-TOKEN",
      "allowFrom": ["MY_TELEGRAM_USER_ID"]
    },
    "discord": {
      "enabled": true,
      "token": "DISCORD-BOT-TOKEN",
      "allowFrom": ["MY_DISCORD_USER_ID"]
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-personal-key"
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18791
  },
  "tools": {
    "restrictToWorkspace": false,
    "web": {
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

---

## Test Instances with CLI Agent

```bash
# Test work instance
nanobot agent -c ~/.nanobot-work/config.json -m "Hello from my work instance"

# Test personal instance
nanobot agent -c ~/.nanobot-personal/config.json -m "Hello from my personal instance"

# Use a temporary workspace (no config edits)
nanobot agent -c ~/.nanobot-work/config.json -w /tmp/work-test -m "Test"
```

> [!NOTE]
> `nanobot agent` starts a local CLI agent directly against the chosen workspace/config. It does not proxy through an already running `nanobot gateway` process.

---

## Manage Multiple Instances via systemd

Ideal for Linux production deployments.

### Template service

Create `/etc/systemd/system/nanobot@.service`:

```ini
[Unit]
Description=Nanobot AI Assistant - %i instance
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
Group=YOUR_GROUP
WorkingDirectory=/home/YOUR_USER
ExecStart=/home/YOUR_USER/.local/bin/nanobot gateway \
    --config /home/YOUR_USER/.nanobot-%i/config.json
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nanobot-%i

# Security hardening (optional)
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/home/YOUR_USER/.nanobot-%i

[Install]
WantedBy=multi-user.target
```

### Start each instance

```bash
# Reload new service definition
sudo systemctl daemon-reload

# Enable + start work instance
sudo systemctl enable nanobot@work
sudo systemctl start nanobot@work

# Enable + start personal instance
sudo systemctl enable nanobot@personal
sudo systemctl start nanobot@personal

# Status & logs
ing systemctl status nanobot@work
sudo systemctl status nanobot@personal
sudo journalctl -u nanobot@work -f
sudo journalctl -u nanobot@personal -f
```

### Separate service files (no template)

If you prefer one service per instance, create `/etc/systemd/system/nanobot-work.service`:

```ini
[Unit]
Description=Nanobot AI Assistant - Work Instance
After=network.target

[Service]
Type=simple
User=YOUR_USER
ExecStart=/home/YOUR_USER/.local/bin/nanobot gateway \
    --config /home/YOUR_USER/.nanobot-work/config.json
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Duplicate for `nanobot-personal.service`, pointing to `~/.nanobot-personal/config.json`.

---

## Minimal Setup: Manual Copy

If you skip the wizard, build the directories yourself:

```bash
mkdir -p ~/.nanobot-work/workspace
mkdir -p ~/.nanobot-personal/workspace
cp ~/.nanobot/config.json ~/.nanobot-work/config.json
cp ~/.nanobot/config.json ~/.nanobot-personal/config.json
```

Then edit each config to adjust:

1. `agents.defaults.workspace` → each workspace path
2. Channel credentials for the desired platforms
3. `gateway.port` → ensure every instance uses a different port

---

## Instance Data Isolation at a Glance

| Data type | Isolation | Notes |
|-----------|-----------|-------|
| Workspace files | Dedicated `workspace` directory | Agents operate on totally separate files |
| Memory summaries | `memory/` inside each workspace | Each instance retains its own conversation context |
| Scheduled tasks | `cron/` under the config directory | Independent cron job lists |
| Media cache | `media/` under the config directory | Images and uploads do not interfere |
| API keys | Stored in each config | Use different keys per instance if needed |

---

## Frequently Asked Questions

**Q: What if ports conflict?**

Set different `gateway.port` values in each config or pass `--port` at startup. The default port is `18790`.

**Q: Can instances share a workspace?**

Technically yes, but not recommended. Sharing a workspace mixes memory, cron jobs, and agent artifacts, making management harder.

**Q: How do I verify an instance is running?**

```bash
lsof -i :18790
lsof -i :18791

nanobot status --config ~/.nanobot-work/config.json
nanobot status --config ~/.nanobot-personal/config.json
```

**Q: Can I switch models dynamically?**

Ask the agent during chat to switch models, or edit the config and restart the instance. You can also pass `--model` on the CLI (`nanobot agent` only) for temporary overrides.
