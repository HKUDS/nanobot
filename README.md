<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: Self-Hosted Personal AI Assistant</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

## What is nanobot?

Nanobot is a self-hosted AI assistant that connects to your chat apps — Telegram, Discord, Slack, WhatsApp, and Email — and runs entirely on your own machine. It works with any LLM provider (OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, or a local model), so you keep full control over your data and costs. Nanobot remembers context across conversations through its persistent memory system and can take actions using built-in tools like file operations, web search, shell commands, and a plugin skill system.

<div align="center">
  <img src="nanobot_arch.png" alt="Architecture" width="800">
</div>

## Install

The PyPI package is **`nanobot-ai`**. After installation, the CLI command is **`nanobot`**.

### Option 1: uv (recommended)

```bash
uv tool install nanobot-ai
```

### Option 2: pip

```bash
pip install nanobot-ai
```

### Option 3: From source

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
make install
```

### Optional extras

Install extras with bracket syntax, e.g. `pip install nanobot-ai[oauth]` or `uv tool install nanobot-ai[oauth,pptx]`.

| Extra | Description |
|-------|-------------|
| `oauth` | OAuth login for OpenAI Codex and GitHub Copilot |
| `pptx` | PowerPoint file tools |
| `prometheus` | Prometheus metrics export |

## Quick Start

Get nanobot running in 2 minutes.

**1. Run the onboarding wizard:**

```bash
nanobot onboard
```

This creates the config directory at `~/.nanobot/` and walks you through initial setup.

**2. Edit `~/.nanobot/config.json`:**

At minimum, you need an LLM provider. Here is an example using OpenRouter:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-..."
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-20250514"
    }
  }
}
```

**3. Test with a single-shot message:**

```bash
nanobot agent -m "Hello!"
```

**4. Enter interactive mode:**

```bash
nanobot agent
```

This starts a REPL session where you can have a back-and-forth conversation. Exit with `Ctrl+D`, `exit`, or `/quit`.

## Chat Apps

Nanobot connects to multiple chat platforms simultaneously via `nanobot gateway`. Each channel is configured in the `channels` section of `~/.nanobot/config.json`.

| Channel | What you need |
|---------|---------------|
| **Telegram** | Bot token from @BotFather |
| **Discord** | Bot token + Message Content intent |
| **WhatsApp** | QR code scan (requires Node.js >=18) |
| **Slack** | Bot token + App-Level token |
| **Email** | IMAP/SMTP credentials |

Start all enabled channels:

```bash
nanobot gateway
```

---

<details>
<summary><b>Telegram</b> (Recommended)</summary>

1. Message [@BotFather](https://t.me/BotFather) on Telegram and create a new bot. Copy the bot token.

2. Get your Telegram user ID (message [@userinfobot](https://t.me/userinfobot) to find it).

3. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

4. Start the gateway:

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Discord</b></summary>

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) and create a new application. Add a Bot under the Bot tab.

2. Under the Bot tab, enable **MESSAGE CONTENT INTENT**.

3. Get your Discord user ID: enable Developer Mode in Discord settings, then right-click your avatar and select **Copy User ID**.

4. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

5. Invite the bot to your server: go to **OAuth2 > URL Generator**, select the `bot` scope, then grant **Send Messages** and **Read Message History** permissions. Open the generated URL to invite.

6. Start the gateway:

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b> (requires Node.js >=18)</summary>

1. Log in by scanning the QR code:

```bash
nanobot channels login
```

2. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

3. Run two terminals — one for the WhatsApp bridge, one for the gateway:

```bash
# Terminal 1
nanobot channels login

# Terminal 2
nanobot gateway
```

</details>

<details>
<summary><b>Slack</b> (Socket Mode — no public URL needed)</summary>

1. Create a new app at [api.slack.com/apps](https://api.slack.com/apps).

2. Enable **Socket Mode** and generate an **App-Level Token** with the `connections:write` scope.

3. Add the following **OAuth scopes** under OAuth & Permissions: `chat:write`, `reactions:write`, `app_mentions:read`.

4. Subscribe to these **events** under Event Subscriptions: `message.im`, `message.channels`, `app_mention`.

5. Go to **App Home** and enable the **Messages Tab** with "Allow users to send Slash commands and messages from the messages tab".

6. **Install to Workspace** and copy the Bot User OAuth Token (`xoxb-...`).

7. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention"
    }
  }
}
```

8. Start the gateway:

```bash
nanobot gateway
```

> [!TIP]
> `groupPolicy` controls how the bot responds in channels: `"mention"` (default, responds when @mentioned), `"open"` (responds to all messages), or `"allowlist"` (responds to listed users). DMs default to open; disable with `"dm": {"enabled": false}`.

</details>

<details>
<summary><b>Email</b> (IMAP/SMTP)</summary>

1. Get your IMAP/SMTP credentials. For Gmail, use a dedicated account with an [App Password](https://support.google.com/accounts/answer/185833).

2. Add to `~/.nanobot/config.json`:

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-nanobot@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-nanobot@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-nanobot@gmail.com",
      "allowFrom": ["your-real-email@gmail.com"]
    }
  }
}
```

`consentGranted` must be set to `true` for the channel to start. If `allowFrom` is empty, all senders are accepted. The default TLS/SSL settings are correct for Gmail. Set `autoReplyEnabled` to `false` to disable automatic replies.

3. Start the gateway:

```bash
nanobot gateway
```

</details>

## Configuration

All configuration lives in `~/.nanobot/config.json`.

<details>
<summary><b>Agent Capabilities</b></summary>

Configure agent behavior via `agents.defaults` in your config:

| Feature | Config Key | Default | Description |
|---------|-----------|---------|-------------|
| Planning | `planning_enabled` | `true` | Decomposes complex tasks into sub-steps before acting |
| Self-critique | `verification_mode` | `"on_uncertainty"` | Verifies tool outputs for correctness (`on_uncertainty`/`always`/`off`) |
| Summary compression | `summary_model` | `""` | LLM model for context window compression (empty = use main model) |
| Memory cap | `memory_md_token_cap` | `1500` | Max tokens injected from MEMORY.md into system prompt |
| Shell mode | `shell_mode` | `"denylist"` | Shell command security (`denylist` blocks destructive commands, `allowlist` for strict allowlisting) |

**Rollout flags** (environment variables):

| Variable | Values | Description |
|----------|--------|-------------|
| `NANOBOT_RERANKER_MODE` | `disabled`/`shadow`/`enabled` | Cross-encoder re-ranker for memory retrieval |
| `NANOBOT_RERANKER_ALPHA` | `0.0`-`1.0` | Blend weight (1.0 = pure cross-encoder, 0.0 = pure heuristic) |
| `NANOBOT_RERANKER_MODEL` | model name | Override re-ranker model (default: `ms-marco-MiniLM-L-6-v2`) |

</details>

<details>
<summary><b>Providers</b></summary>

> [!TIP]
> - **Groq** provides free voice transcription via Whisper. Telegram voice messages are automatically transcribed.
> - **Zhipu Coding Plan**: Set `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"` in your zhipu provider config.
> - **MiniMax (Mainland China)**: Set `"apiBase": "https://api.minimaxi.com/v1"` in your minimax provider config.
> - **VolcEngine Coding Plan**: Set `"apiBase": "https://ark.cn-beijing.volces.com/api/coding/v3"` in your volcengine provider config.

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `custom` | Any OpenAI-compatible endpoint (direct, no LiteLLM) | — |
| `openrouter` | LLM (recommended, access to all models) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM (Claude direct) | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM (GPT direct) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek direct) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **Voice transcription** (Whisper) | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM (Gemini direct) | [aistudio.google.com](https://aistudio.google.com) |
| `minimax` | LLM (MiniMax direct) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `aihubmix` | LLM (API gateway, access to all models) | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | LLM (SiliconFlow/硅基流动) | [siliconflow.cn](https://siliconflow.cn) |
| `volcengine` | LLM (VolcEngine/火山引擎) | [volcengine.com](https://www.volcengine.com) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Moonshot/Kimi) | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM (Zhipu GLM) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `vllm` | LLM (local, any OpenAI-compatible server) | — |
| `openai_codex` | LLM (Codex, OAuth) | `nanobot provider login openai-codex` |
| `github_copilot` | LLM (GitHub Copilot, OAuth) | `nanobot provider login github-copilot` |

<details>
<summary>OpenAI Codex (OAuth)</summary>

1. Log in:

```bash
nanobot provider login openai-codex
```

2. Set your model in `config.json`:

```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/gpt-5.1-codex"
    }
  }
}
```

3. Chat:

```bash
nanobot agent -m "Hello!"
```

> [!NOTE]
> When running inside Docker, use `docker run -it` for interactive OAuth login.

</details>

<details>
<summary>GitHub Copilot (OAuth)</summary>

1. Log in:

```bash
nanobot provider login github-copilot
```

2. Set your model in `config.json`:

```json
{
  "agents": {
    "defaults": {
      "model": "github-copilot/gpt-4o"
    }
  }
}
```

3. Chat:

```bash
nanobot agent -m "Hello!"
```

> [!NOTE]
> When running inside Docker, use `docker run -it` for interactive OAuth login.

</details>

<details>
<summary>Custom Provider</summary>

Use any OpenAI-compatible endpoint directly (LM Studio, llama.cpp, Together AI, etc.) without going through LiteLLM.

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://your-endpoint.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

> [!NOTE]
> For local servers that don't require authentication, set `apiKey` to any non-empty string (e.g., `"dummy"`).

</details>

<details>
<summary>vLLM</summary>

1. Start a vLLM server:

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

2. Configure nanobot:

```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

</details>

<details>
<summary>Adding a New Provider (Developer Guide)</summary>

Providers are defined in the Provider Registry (`nanobot/providers/registry.py`). Each provider is a `ProviderSpec`:

1. **Add a `ProviderSpec`** to `PROVIDERS` in `registry.py`:

```python
ProviderSpec(
    name="myprovider",
    litellm_prefix="myprovider",
    env_extras={"MYPROVIDER_API_KEY": "apiKey"},
)
```

2. **Add a config field** to `ProvidersConfig` in `nanobot/config/schema.py`:

```python
myprovider: ProviderConfig = Field(default_factory=ProviderConfig)
```

`ProviderSpec` options:

| Field | Type | Description |
|-------|------|-------------|
| `litellm_prefix` | `str` | Prefix added to model names for LiteLLM routing |
| `skip_prefixes` | `list[str]` | Model prefixes that skip the litellm_prefix |
| `env_extras` | `dict` | Extra environment variables to set from config |
| `model_overrides` | `dict` | Rewrite model names before sending to LiteLLM |
| `is_gateway` | `bool` | If true, acts as a gateway (no prefix added) |
| `detect_by_key_prefix` | `str` | Auto-detect provider by API key prefix |
| `detect_by_base_keyword` | `str` | Auto-detect provider by API base URL keyword |
| `strip_model_prefix` | `bool` | Strip the provider prefix before sending to the API |

</details>

</details>

<details>
<summary><b>MCP (Model Context Protocol)</b></summary>

> [!TIP]
> The config format is compatible with Claude Desktop / Cursor. You can copy MCP server configs directly from any MCP server's README.

nanobot supports [MCP](https://modelcontextprotocol.io/) — connect external tool servers and use them as native agent tools.

Add MCP servers to your `config.json`:

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "my-remote-mcp": {
        "url": "https://example.com/mcp/",
        "headers": {
          "Authorization": "Bearer xxxxx"
        }
      }
    }
  }
}
```

Two transport modes:

| Mode | Config | Example |
|------|--------|---------|
| **Stdio** | `command` + `args` | Local process via `npx` / `uvx` |
| **HTTP** | `url` + `headers` (optional) | Remote endpoint |

Use `toolTimeout` to override the default 30s per-call timeout:

```json
{
  "tools": {
    "mcpServers": {
      "my-slow-server": {
        "url": "https://example.com/mcp/",
        "toolTimeout": 120
      }
    }
  }
}
```

MCP tools are automatically discovered and registered on startup.

</details>

<details>
<summary><b>Multi-Agent Routing</b></summary>

A lightweight LLM classifier routes each message to a specialized agent role. Each role can have its own model, system prompt, temperature, and tool restrictions — while sharing conversation history and memory.

Routing is **disabled by default**. Enable it in your config:

```json
{
  "agents": {
    "routing": {
      "enabled": true,
      "classifierModel": "gpt-4o-mini",
      "defaultRole": "general",
      "roles": [
        {
          "name": "code",
          "description": "Code generation, debugging, refactoring",
          "model": "claude-sonnet-4-20250514",
          "deniedTools": ["message"]
        },
        {
          "name": "research",
          "description": "Web search, document analysis, fact-finding",
          "deniedTools": ["write_file", "edit_file"]
        }
      ]
    }
  }
}
```

Six built-in roles: **code**, **research**, **writing**, **system**, **pm**, and **general**. Custom roles extend or override these.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Feature gate |
| `classifierModel` | `string` | `null` | Cheap model for intent classification |
| `defaultRole` | `string` | `"general"` | Fallback when classifier is uncertain |
| `roles` | `array` | `[]` | Custom role definitions |

Each role supports: `name`, `description`, `model`, `temperature`, `systemPrompt`, `allowedTools`, `deniedTools`, `skills`, `maxIterations`, `enabled`.

</details>

<details>
<summary><b>Feature Flags</b></summary>

Master switches in the `features` config block. These override per-agent settings.

| Flag | Default | What it controls |
|------|---------|-----------------|
| `planning_enabled` | `true` | Task decomposition and planning |
| `verification_enabled` | `true` | Answer verification (master switch — distinct from `verification_mode` in agent defaults) |
| `delegation_enabled` | `true` | Multi-agent delegation |
| `memory_enabled` | `true` | Persistent memory |
| `skills_enabled` | `true` | Skill discovery and loading |
| `streaming_enabled` | `true` | Streaming LLM responses |

```json
{
  "features": {
    "planning_enabled": false,
    "delegation_enabled": false
  }
}
```

</details>

<details>
<summary><b>Observability (Langfuse)</b></summary>

nanobot traces LLM calls, tool invocations, and agent turns to [Langfuse](https://langfuse.com/).

```json
{
  "langfuse": {
    "enabled": true,
    "publicKey": "pk-...",
    "secretKey": "sk-...",
    "host": "https://cloud.langfuse.com"
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Enable/disable tracing |
| `publicKey` | `""` | Langfuse public key |
| `secretKey` | `""` | Langfuse secret key |
| `host` | `"https://cloud.langfuse.com"` | Langfuse server URL (self-hosted or cloud) |
| `environment` | `"development"` | Environment tag |
| `sampleRate` | `1.0` | Fraction of traces to send (0.0-1.0) |

</details>

<details>
<summary><b>Security</b></summary>

| Option | Default | Description |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | Restricts all agent tools (shell, file read/write/edit, list) to the workspace directory. Prevents path traversal. |
| `channels.*.allowFrom` | `[]` (allow all) | Whitelist of user IDs per channel. Empty = allow everyone. |

> [!TIP]
> For production deployments, set `"restrictToWorkspace": true` to sandbox the agent.

</details>

## Deployment

<details>
<summary><b>Docker Compose</b></summary>

```bash
docker compose run --rm nanobot-cli onboard   # first-time setup
vim ~/.nanobot/config.json                     # add API keys
docker compose up -d nanobot-gateway           # start gateway
```

```bash
docker compose run --rm nanobot-cli agent -m "Hello!"   # run CLI
docker compose logs -f nanobot-gateway                   # view logs
docker compose down                                      # stop
```

> [!TIP]
> The `-v ~/.nanobot:/root/.nanobot` flag mounts your local config directory into the container, so your config and workspace persist across container restarts.

</details>

<details>
<summary><b>Docker</b></summary>

```bash
# Build the image
docker build -t nanobot .

# Initialize config (first time only)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# Edit config on host to add API keys
vim ~/.nanobot/config.json

# Run gateway (connects to enabled channels)
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# Or run a single command
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot status
```

</details>

<details>
<summary><b>Production and Staging</b></summary>

Use the deployment script for production and staging environments:

```bash
# Deploy to production
bash deploy/deploy.sh --env production

# Deploy to staging
bash deploy/deploy.sh --env staging

# Rollback
bash deploy/deploy.sh --env production --rollback
```

Configuration files:
- Production: `deploy/production/docker-compose.yml` + `deploy/production/.env.example`
- Staging: `deploy/staging/docker-compose.yml` + `deploy/staging/.env.example`
- Caddy reverse proxy: `deploy/caddy-snippet.conf`

> Former systemd users: run `deploy/migrate-from-systemd.sh` to migrate to Docker Compose.

</details>

## CLI Reference

| Command | Description |
|---------|-------------|
| `nanobot onboard` | Initialize config and workspace |
| `nanobot agent` | Interactive chat (REPL) |
| `nanobot agent -m "..."` | Single-shot message |
| `nanobot gateway` | Start the gateway (all channels) |
| `nanobot ui` | Launch web UI |
| `nanobot status` | Show provider and channel status |
| `nanobot provider login <name>` | OAuth login (openai-codex, github-copilot) |
| `nanobot channels status` | Show channel connection status |
| `nanobot channels login` | Link WhatsApp (scan QR) |
| `nanobot replay-deadletters` | Replay failed messages from dead-letter queue |

Interactive mode exits: `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.

<details>
<summary><b>Scheduled Tasks (Cron)</b></summary>

```bash
# Add a cron job
nanobot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "Check status" --every 3600

# List jobs
nanobot cron list

# Remove a job
nanobot cron remove <job_id>

# Enable/disable a job
nanobot cron enable <job_id>
nanobot cron enable <job_id> --disable

# Manually run a job
nanobot cron run <job_id>
```

</details>

<details>
<summary><b>Heartbeat (Periodic Tasks)</b></summary>

The gateway wakes up every 30 minutes and checks `HEARTBEAT.md` in your workspace (`~/.nanobot/workspace/HEARTBEAT.md`). If the file has tasks, the agent executes them and delivers results to your most recently active chat channel.

**Setup:** edit `~/.nanobot/workspace/HEARTBEAT.md` (created automatically by `nanobot onboard`):

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

The agent can also manage this file itself — ask it to "add a periodic task" and it will update `HEARTBEAT.md` for you.

> **Note:** The gateway must be running (`nanobot gateway`) and you must have chatted with the bot at least once so it knows which channel to deliver to.

</details>

<details>
<summary><b>Routing Diagnostics</b></summary>

```bash
nanobot routing trace         # Show recent routing decisions
nanobot routing metrics       # Show routing metrics/stats
nanobot routing dlq           # Show dead-letter queue
nanobot routing replay        # Replay from dead-letter queue
```

</details>

<details>
<summary><b>Memory Management</b></summary>

```bash
nanobot memory inspect        # Inspect memory state
nanobot memory metrics        # Show memory metrics
nanobot memory rebuild        # Rebuild memory store
nanobot memory reindex        # Reindex vector store
nanobot memory compact        # Compact memory
nanobot memory verify         # Verify memory integrity
nanobot memory eval           # Run memory evaluation
nanobot memory conflicts      # Show memory conflicts
nanobot memory resolve        # Resolve memory conflicts
nanobot memory pin            # Pin a memory (prevent deletion)
nanobot memory unpin          # Unpin a memory
nanobot memory outdated       # Show outdated memories
```

</details>
