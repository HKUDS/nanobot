# Onboarding Wizard

`nanobot onboard` is nanobot’s interactive initialization wizard. It creates configuration files and workspace templates so you can get started quickly.

---

## What the Wizard Does

When you run `nanobot onboard`, the wizard will:

1. **Create config file** `~/.nanobot/config.json` (if it does not exist)
2. **Create workspace directory** `~/.nanobot/workspace/`
3. **Generate workspace template files** (AGENTS.md, USER.md, SOUL.md, TOOLS.md, HEARTBEAT.md)
4. **Guide you through basic options** (LLM provider, model, etc.)

!!! note "Safe to run repeatedly"
    Running `nanobot onboard` again does not overwrite existing config or workspace content. It only fills in missing files.

---

## Run the Wizard

```bash
nanobot onboard
```

The wizard is interactive and asks your preferences step by step. After completion, all required files are created.

---

## Config Locations

### Default Paths

| File / Directory | Path |
|------------|------|
| **Config file** | `~/.nanobot/config.json` |
| **Workspace** | `~/.nanobot/workspace/` |
| **Cron jobs** | `~/.nanobot/cron/` |
| **Media / state** | `~/.nanobot/media/` |

### Custom Paths

You can use `-c` (`--config`) and `-w` (`--workspace`) flags to specify custom paths, useful for multi-instance deployment:

```bash
# Create isolated instances for specific channels
nanobot onboard --config ~/.nanobot-telegram/config.json \
                --workspace ~/.nanobot-telegram/workspace

nanobot onboard --config ~/.nanobot-discord/config.json \
                --workspace ~/.nanobot-discord/workspace
```

!!! tip "Multi-instance deployment"
    With different `--config` paths, you can run multiple nanobot instances at once for different chat platforms or use cases. See [Multi-Instance Deployment](../configuration/multi-instance.md).

---

## Config File Explanation (`config.json`)

The generated `~/.nanobot/config.json` includes all configuration options. Main structure:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": ""
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter",
      "workspace": "~/.nanobot/workspace"
    }
  },
  "channels": {},
  "tools": {
    "restrictToWorkspace": false
  },
  "gateway": {
    "port": 18790
  }
}
```

### Key Config Fields

| Field | Description |
|------|------|
| `providers.<name>.apiKey` | API key for LLM provider |
| `agents.defaults.model` | Default model name |
| `agents.defaults.provider` | Default provider (`"auto"` for auto-detection) |
| `agents.defaults.workspace` | Workspace directory path |
| `channels.<name>.enabled` | Whether to enable the chat channel |
| `tools.restrictToWorkspace` | Whether tools are restricted to workspace access only |
| `gateway.port` | HTTP port listened by Gateway (default: 18790) |

---

## Workspace Template Files

The wizard creates the following template files under `~/.nanobot/workspace/`. These files are used as agent system prompt context:

### AGENTS.md — Agent Behavior Guide

Defines agent core behavior, capabilities, and limits.

```markdown
# Agent Instructions

You are a helpful personal AI assistant powered by nanobot.

## Capabilities
- Answer questions and provide information
- Help with coding, writing, and analysis
- Execute shell commands and manage files
- Search the web for current information

## Guidelines
- Be concise and helpful
- Ask for clarification when needed
- Respect user privacy
```

**Usage:** Customize response style, domain expertise, constraints, and so on.

### USER.md — User Profile

Describes user background, preferences, and commonly used info so the agent can provide personalized responses.

```markdown
# User Profile

## About Me
- Name: [Your Name]
- Location: [Your City/Timezone]
- Occupation: [Your Role]

## Preferences
- Language: English preferred
- Response style: Concise and practical

## Frequently Used
- Work directory: ~/projects
- Preferred editor: vim
```

**Usage:** Helps the agent understand your context and avoid repeated explanations.

### SOUL.md — Agent Personality Definition

Defines personality traits and communication style.

```markdown
# Soul

You have a friendly, professional personality.
You are curious, helpful, and direct.
You communicate clearly and adapt your tone to the conversation.
```

**Usage:** Tune personality so interaction better matches your preference.

### TOOLS.md — Tool Usage Preferences

Explains how the agent should use tools.

```markdown
# Tool Usage Guidelines

## Shell Commands
- Always explain what a command does before running it
- Ask for confirmation before destructive operations

## Web Search
- Search for current information when needed
- Cite sources when providing factual information

## File Operations
- Work within the workspace directory by default
- Create backups before modifying important files
```

**Usage:** Control tool usage style and timing.

### HEARTBEAT.md — Periodic Task Settings

Defines periodic tasks that gateway runs automatically every 30 minutes.

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

!!! info "How Heartbeat Works"
    Gateway reads `HEARTBEAT.md` every 30 minutes, executes listed tasks, and sends results to your most recently active chat channel.

    **Note:** Gateway must be running (`nanobot gateway`), and you must have sent at least one message so nanobot knows where to deliver results.

---

## Customize Workspace

Workspace files are plain Markdown text, so you can edit them directly:

```bash
# Edit Agent instructions
vim ~/.nanobot/workspace/AGENTS.md

# Edit user profile
vim ~/.nanobot/workspace/USER.md

# Configure periodic tasks
vim ~/.nanobot/workspace/HEARTBEAT.md
```

### Common Customization Examples

**Set a preferred response language:**

Add to `AGENTS.md`:

```markdown
## Language
Always respond in English unless the user writes in another language.
```

**Restrict tool usage:**

Add to `AGENTS.md`:

```markdown
## Security
- Never execute shell commands without explicit user approval
- Do not access files outside the workspace directory
```

**Set domain expertise:**

Add to `AGENTS.md`:

```markdown
## Expertise
You specialize in Python development and data analysis.
Prioritize clean, Pythonic code and provide explanations for complex algorithms.
```

**Set daily summaries:**

Add to `HEARTBEAT.md`:

```markdown
## Periodic Tasks

- [ ] Every morning at 9am: Check today's calendar events and send a summary
- [ ] Every evening at 6pm: Summarize today's news in English
```

### Automatic Workspace Template Sync

!!! tip "Template updates"
    After nanobot upgrades, template contents may change. Re-running `nanobot onboard` can add new template fields without overwriting existing content.

---

## Using `-c` and `-w` Flags

All nanobot commands support `-c` (`--config`) and `-w` (`--workspace`) for flexible switching across instances:

### `-c` / `--config`: Specify config file

```bash
# Start gateway with a specific config file
nanobot gateway --config ~/.nanobot-telegram/config.json

# Use a specific config file for CLI chat
nanobot agent --config ~/.nanobot-discord/config.json -m "Hello!"
```

### `-w` / `--workspace`: Specify workspace directory

```bash
# Use a testing workspace
nanobot agent --workspace /tmp/nanobot-test

# Use with custom config
nanobot agent --config ~/.nanobot-telegram/config.json \
              --workspace /tmp/nanobot-telegram-test
```

!!! note "Flag precedence"
    The `--workspace` flag overrides `agents.defaults.workspace` in config for the current run only.

### Multi-Instance Initialization Example

```bash
# Create instance for Telegram
nanobot onboard \
  --config ~/.nanobot-telegram/config.json \
  --workspace ~/.nanobot-telegram/workspace

# Create instance for Discord
nanobot onboard \
  --config ~/.nanobot-discord/config.json \
  --workspace ~/.nanobot-discord/workspace

# Start separately (using different ports)
nanobot gateway --config ~/.nanobot-telegram/config.json
nanobot gateway --config ~/.nanobot-discord/config.json --port 18791
```

---

## Full Onboarding Flow Recap

```
nanobot onboard
    ↓
Create ~/.nanobot/config.json
    ↓
Create ~/.nanobot/workspace/
    ├── AGENTS.md
    ├── USER.md
    ├── SOUL.md
    ├── TOOLS.md
    └── HEARTBEAT.md
    ↓
Edit config.json and add API keys
    ↓
(Optional) Edit workspace templates to customize agent behavior
    ↓
nanobot agent   ← CLI chat
nanobot gateway ← Start channel service
```

---

## Next Steps

- **Quick Start**: [5-minute quick setup guide](quick-start.md)
- **Connect chat channels**: [Channel setup guide](../channels/index.md)
- **Configure LLM providers**: [Providers docs](../providers/index.md)