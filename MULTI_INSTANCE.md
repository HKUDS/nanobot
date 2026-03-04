# Multi-Instance Configuration Guide

This guide explains how to run multiple nanobot instances with complete isolation.

## Overview

The multi-instance architecture allows you to:
- Run multiple AI assistants with different configurations
- Isolate workspaces, memory, sessions, and cron jobs
- Use different LLM models and providers per instance
- Connect to different messaging platforms (e.g., multiple Feishu apps)

## Architecture

Each instance has its own:
- **Config file** (`config.json`) - LLM settings, channel credentials, ports
- **Workspace** - Skills, memory, sessions, history
- **Cron jobs** - Scheduled tasks and reminders
- **Logs** - Separate log files
- **Media** - Uploaded files and attachments

## Quick Start

### 1. Create a New Instance

```bash
# Create instance directory
mkdir -p ~/.nanobot-instance2

# Copy default config
cp ~/.nanobot/config.json ~/.nanobot-instance2/config.json

# Edit configuration
nano ~/.nanobot-instance2/config.json
```

### 2. Configure the Instance

Edit `~/.nanobot-instance2/config.json`:

```json
{
  "gateway": {
    "port": 18791  // Different port for each instance
  },
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_your_app_id_2",
      "appSecret": "your_app_secret_2"
    }
  },
  "agents": {
    "defaults": {
      "model": "claude-opus-4",
      "provider": "anthropic"
    }
  }
}
```

**Important**: Each instance must use a unique port number.

### 3. Start the Instance

**Foreground mode** (see logs in terminal):
```bash
nanobot gateway --config ~/.nanobot-instance2/config.json
```

**Daemon mode** (background):
```bash
./start_nanobot_daemon.sh ~/.nanobot-instance2/config.json \
                          ~/.nanobot-instance2/nanobot.pid \
                          /tmp/nanobot-instance2.log
```

### 4. Verify the Instance

```bash
# Check process
ps aux | grep "nanobot gateway"

# Run diagnostics
./diagnose.sh ~/.nanobot-instance2/config.json

# View logs
tail -f /tmp/nanobot-instance2.log
```

## Use Cases

### Scenario 1: Multiple Teams

Run separate instances for different teams with isolated workspaces:

```bash
# Product team instance
nanobot gateway --config ~/.nanobot-product/config.json

# Engineering team instance
nanobot gateway --config ~/.nanobot-engineering/config.json
```

### Scenario 2: Different LLM Models

Test different models without affecting production:

```bash
# Production (Claude Opus)
nanobot gateway --config ~/.nanobot-prod/config.json

# Testing (Claude Sonnet)
nanobot gateway --config ~/.nanobot-test/config.json
```

### Scenario 3: Multiple Feishu Apps

Connect to different Feishu organizations:

```bash
# Company A
nanobot gateway --config ~/.nanobot-companyA/config.json

# Company B
nanobot gateway --config ~/.nanobot-companyB/config.json
```

## Management Scripts

### Start Script

`start_nanobot.sh` - Start instance in foreground:
```bash
./start_nanobot.sh [config_path]
```

### Daemon Script

`start_nanobot_daemon.sh` - Start instance as daemon:
```bash
./start_nanobot_daemon.sh [config_path] [pid_file] [log_file]
```

### Diagnostic Script

`diagnose.sh` - Check instance status:
```bash
./diagnose.sh [config_path]
```

## Best Practices

1. **Naming Convention**: Use descriptive directory names
   - `~/.nanobot-{team}` (e.g., `~/.nanobot-product`)
   - `~/.nanobot-{purpose}` (e.g., `~/.nanobot-testing`)

2. **Port Assignment**: Use sequential ports
   - Main instance: 18790
   - Instance 2: 18791
   - Instance 3: 18792

3. **PID Files**: Store in instance directory
   - `~/.nanobot-instance2/nanobot.pid`

4. **Log Files**: Use descriptive names
   - `/tmp/nanobot-instance2.log`
   - `/var/log/nanobot-instance2.log` (production)

5. **Backup**: Regularly backup instance directories
   ```bash
   tar -czf nanobot-instance2-backup.tar.gz ~/.nanobot-instance2
   ```

## Troubleshooting

### Port Already in Use

```bash
# Find process using port
lsof -i :18791

# Kill process
kill $(lsof -t -i :18791)
```

### Instance Won't Start

```bash
# Check config syntax
cat ~/.nanobot-instance2/config.json | python -m json.tool

# Check permissions
ls -la ~/.nanobot-instance2/

# View detailed logs
nanobot gateway --config ~/.nanobot-instance2/config.json --verbose
```

### Cron Jobs Not Running

Cron jobs are stored in `{instance_dir}/cron/jobs.json`. Each instance has independent cron scheduling.

```bash
# List cron jobs for instance
cat ~/.nanobot-instance2/cron/jobs.json

# Check cron logs
tail -f ~/.nanobot-instance2/logs/cron.log
```

## Technical Details

### How It Works

The `--config` parameter sets the configuration file path. The data directory is automatically derived from the config file location:

```
Config: ~/.nanobot-instance2/config.json
Data Dir: ~/.nanobot-instance2/
```

All instance data (workspace, cron, logs, media) is stored relative to the data directory.

### Modified Files

The multi-instance support required changes to 3 core files:

1. **nanobot/cli/commands.py** - Added `--config` parameter to gateway command
2. **nanobot/config/loader.py** - Added `set_config_path()` and modified `get_data_dir()`
3. **nanobot/utils/helpers.py** - Modified `get_data_path()` to use unified data directory

### Migration from Single Instance

Existing single-instance setups continue to work without changes. The default config path is `~/.nanobot/config.json`.

## System Service Setup

### systemd (Linux)

Create `/etc/systemd/system/nanobot-instance2.service`:

```ini
[Unit]
Description=Nanobot Instance 2
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/nanobot
ExecStart=/path/to/nanobot/venv/bin/nanobot gateway --config /home/your_user/.nanobot-instance2/config.json
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable nanobot-instance2
sudo systemctl start nanobot-instance2
```

### launchd (macOS)

Create `~/Library/LaunchAgents/com.nanobot.instance2.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nanobot.instance2</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/nanobot/venv/bin/nanobot</string>
        <string>gateway</string>
        <string>--config</string>
        <string>/Users/your_user/.nanobot-instance2/config.json</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

Load:
```bash
launchctl load ~/Library/LaunchAgents/com.nanobot.instance2.plist
```

## Further Reading

- [nanobot Documentation](https://github.com/HKUDS/nanobot)
- [Configuration Reference](https://github.com/HKUDS/nanobot/blob/main/docs/configuration.md)
- [Feishu Integration Guide](https://github.com/HKUDS/nanobot/blob/main/docs/channels/feishu.md)
