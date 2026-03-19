# CLI Command Reference

This document provides complete coverage of all nanobot command-line commands.

## Quick Reference Table

| Command | Description |
|------|------|
| `nanobot --version` | Show version number |
| `nanobot --help` | Show help documentation |
| `nanobot onboard` | Interactively initialize configuration and workspace |
| `nanobot onboard -c <path> -w <path>` | Initialize or update a specific instance configuration |
| `nanobot agent` | Enter interactive chat mode |
| `nanobot agent -m "..."` | Single-message mode (non-interactive) |
| `nanobot agent --no-markdown` | Display responses as plain text |
| `nanobot agent --logs` | Show runtime logs during chat |
| `nanobot gateway` | Start Gateway service (connects chat channels) |
| `nanobot gateway --port <port>` | Start Gateway on a specified port |
| `nanobot status` | Show configuration and connection status |
| `nanobot channels login` | WhatsApp QR Code login |
| `nanobot channels status` | Show connection status of each channel |
| `nanobot plugins list` | List all installed channel plugins |
| `nanobot provider login <provider>` | OAuth login (`openai-codex`, `github-copilot`) |

---

## nanobot — Main Command

```
nanobot [OPTIONS] COMMAND [ARGS]...
```

The main entry point for the nanobot personal AI assistant framework.

### Global Options

| Option | Description |
|------|------|
| `--version`, `-v` | Show version number and exit |
| `--help` | Show help documentation |

### Examples

```bash
# Show version
nanobot --version

# Show all available commands
nanobot --help
```

---

## nanobot onboard

```
nanobot onboard [OPTIONS]
```

Interactively initialize configuration and workspace. The wizard guides you through API keys, LLM provider setup, and basic settings.

### Options

| Option | Default | Description |
|------|--------|------|
| `-c`, `--config PATH` | `~/.nanobot/config.json` | Configuration file path |
| `-w`, `--workspace PATH` | `~/.nanobot/workspace` | Workspace path |
| `--non-interactive` | `false` | Skip interactive wizard and directly create or update config |

### Behavior

- **Interactive mode (default):** Launches guided setup to configure LLM provider, API key, and channels step by step.
- **Non-interactive mode (`--non-interactive`):** If config does not exist, create it with defaults; if it exists, prompt to overwrite or fill missing fields.

### Examples

```bash
# Interactive initialization (recommended for first-time use)
nanobot onboard

# Initialize a specific instance
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace

# Non-interactively create default config
nanobot onboard --non-interactive

# Non-interactive initialization with a specific config path
nanobot onboard -c ~/my-nanobot/config.json --non-interactive
```

### Next Steps After Completion

```bash
# Test whether configuration is correct
nanobot agent -m "Hello!"

# Start Gateway service to connect chat channels
nanobot gateway
```

---

## nanobot agent

```
nanobot agent [OPTIONS]
```

Chat directly with the AI agent. Supports both single-message mode and persistent interactive conversations.

### Options

| Option | Default | Description |
|------|--------|------|
| `-m`, `--message TEXT` | None | Single-message mode (non-interactive); sends one message and exits immediately |
| `-c`, `--config PATH` | `~/.nanobot/config.json` | Configuration file path |
| `-w`, `--workspace PATH` | Value from config | Workspace path (overrides config value) |
| `-s`, `--session TEXT` | `cli:direct` | Session ID |
| `--markdown` / `--no-markdown` | `--markdown` | Whether to render responses in Markdown |
| `--logs` / `--no-logs` | `--no-logs` | Whether to show tool execution logs during chat |

### Interactive Mode Shortcuts

| Key / Command | Function |
|-----------|------|
| `exit`, `quit`, `:q` | Exit chat |
| `Ctrl+D` | Exit chat |
| `Ctrl+C` | Exit chat |
| Up/Down arrow keys | Browse command history |
| Paste multiline text | Automatically supports multiline input (bracketed paste) |

### Examples

```bash
# Single-message mode
nanobot agent -m "What's the weather today?"

# Enter interactive chat
nanobot agent

# Use a specific config file
nanobot agent --config ~/.nanobot-telegram/config.json

# Use a specific workspace
nanobot agent --workspace /tmp/nanobot-test

# Specify config and workspace together
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test

# Display plain-text responses (do not render Markdown)
nanobot agent --no-markdown

# Show tool execution logs (for debugging)
nanobot agent --logs

# Single-message mode with logs
nanobot agent -m "List files in the workspace" --logs
```

---

## nanobot gateway

```
nanobot gateway [OPTIONS]
```

Start the nanobot Gateway service and connect all enabled chat channels (Telegram, Discord, Slack, WhatsApp, etc.). Gateway also manages scheduled tasks (Cron) and periodic heartbeat checks.

### Options

| Option | Default | Description |
|------|--------|------|
| `-c`, `--config PATH` | `~/.nanobot/config.json` | Configuration file path |
| `-w`, `--workspace PATH` | Value from config | Workspace path (overrides config value) |
| `-p`, `--port INT` | Value from config | Override Gateway port |
| `-v`, `--verbose` | `false` | Show verbose debug logs |

### Examples

```bash
# Start Gateway (using default config)
nanobot gateway

# Start on a specified port
nanobot gateway --port 18792

# Start with a specified config file (multi-instance deployment)
nanobot gateway --config ~/.nanobot-telegram/config.json

# Run multiple instances simultaneously
nanobot gateway --config ~/.nanobot-telegram/config.json &
nanobot gateway --config ~/.nanobot-discord/config.json &
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792 &

# Enable verbose logs (for debugging)
nanobot gateway --verbose
```

### Startup Information

When Gateway starts, it shows:

- List of enabled channels
- Number of configured scheduled tasks
- Heartbeat check interval

---

## nanobot status

```
nanobot status
```

Show current configuration and connection status, including config path, workspace path, selected model, and API key status for each LLM provider.

### Example

```bash
nanobot status
```

### Example Output

```
🐈 nanobot Status

Config: /Users/yourname/.nanobot/config.json ✓
Workspace: /Users/yourname/.nanobot/workspace ✓
Model: openrouter/anthropic/claude-3.5-sonnet
OpenRouter: ✓
Anthropic: not set
OpenAI: not set
```

---

## nanobot channels

```
nanobot channels COMMAND [ARGS]...
```

Subcommand group for managing chat channel connections.

### Subcommands

#### nanobot channels login

```
nanobot channels login
```

Log in to WhatsApp by scanning a QR Code. Run this command for first-time use or re-authorization.

If Node.js bridge is not installed, this command will download and build it automatically.

**Requirements:**
- Node.js >= 18
- npm

**Examples:**

```bash
# First-time WhatsApp login
nanobot channels login

# Rebuild bridge and login again (after upgrade)
rm -rf ~/.nanobot/bridge && nanobot channels login
```

---

#### nanobot channels status

```
nanobot channels status
```

Show enabled status of all discovered channels (built-in and plugin) in table format.

**Example:**

```bash
nanobot channels status
```

**Example Output:**

```
        Channel Status
┌──────────────┬─────────┐
│ Channel      │ Enabled │
├──────────────┼─────────┤
│ Telegram     │ ✓       │
│ Discord      │ ✗       │
│ Slack        │ ✗       │
│ WhatsApp     │ ✓       │
└──────────────┴─────────┘
```

---

## nanobot plugins

```
nanobot plugins COMMAND [ARGS]...
```

Subcommand group for managing channel plugins.

### Subcommands

#### nanobot plugins list

```
nanobot plugins list
```

List all discovered channels (including built-in channels and third-party plugins), showing name, source (`builtin` / `plugin`), and enabled status.

**Example:**

```bash
nanobot plugins list
```

---

## nanobot provider

```
nanobot provider COMMAND [ARGS]...
```

Subcommand group for managing LLM providers.

### Subcommands

#### nanobot provider login

```
nanobot provider login PROVIDER
```

Log in to the specified LLM provider through OAuth.

**Arguments:**

| Argument | Description |
|------|------|
| `PROVIDER` | Provider name (see table below) |

**Supported OAuth providers:**

| Provider Name | Description |
|-----------|------|
| `openai-codex` | OpenAI Codex (OAuth authorization) |
| `github-copilot` | GitHub Copilot (device authorization flow) |

**Examples:**

```bash
# Log in to OpenAI Codex
nanobot provider login openai-codex

# Log in to GitHub Copilot
nanobot provider login github-copilot
```

---

## Multi-Instance Deployment

nanobot supports running multiple independent instances at the same time, each with its own config file and workspace. Use `--config` as the primary discriminator.

### Quick Setup

```bash
# Initialize each instance
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace
nanobot onboard --config ~/.nanobot-feishu/config.json --workspace ~/.nanobot-feishu/workspace

# Start Gateway for each instance separately
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792
```

### Using agent Command with Multiple Instances

```bash
# Send a message to a specific instance
nanobot agent -c ~/.nanobot-telegram/config.json -m "Hello from Telegram instance"
nanobot agent -c ~/.nanobot-discord/config.json -m "Hello from Discord instance"

# Override workspace (for testing)
nanobot agent -c ~/.nanobot-telegram/config.json -w /tmp/nanobot-telegram-test
```

### Path Resolution Logic

| Setting Item | Source |
|---------|------|
| Config file | Path specified by `--config` |
| Workspace | `--workspace` override > `agents.defaults.workspace` in config |
| Runtime data directory | Automatically derived from config file location |