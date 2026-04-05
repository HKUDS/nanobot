<div align="center">
  <img src="janniebot_logo.png" alt="janniebot" width="500">
  <h1>janniebot: Ultra-Lightweight Personal AI Assistant</h1>
  <p>
    <a href="https://pypi.org/project/janniebot/"><img src="https://img.shields.io/pypi/v/janniebot?label=pypi" alt="PyPI"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

🐈 **janniebot** is an **ultra-lightweight** personal AI assistant inspired by [OpenClaw](https://github.com/openclaw/openclaw).

⚡️ Delivers core agent functionality with **99% fewer lines of code** than OpenClaw.

📏 Real-time line count: run `bash core_agent_lines.sh` to verify anytime.

> 🐈 janniebot is for educational, research, and technical exchange purposes only. It is unrelated to crypto and does not involve any official token or coin.

## Key Features of janniebot:

🪶 **Ultra-Lightweight**: A super lightweight implementation of OpenClaw — 99% smaller, significantly faster.

🔬 **Research-Ready**: Clean, readable code that's easy to understand, modify, and extend for research.

⚡️ **Lightning Fast**: Minimal footprint means faster startup, lower resource usage, and quicker iterations.

💎 **Easy-to-Use**: One-click to deploy and you're ready to go.

## 🏗️ Architecture

<p align="center">
  <img src="janniebot_arch.png" alt="janniebot architecture" width="800">
</p>

## Table of Contents

- [Key Features](#key-features-of-janniebot)
- [Architecture](#️-architecture)
- [Features](#-features)
- [Install](#-install)
- [Quick Start](#-quick-start)
- [Chat Apps](#-chat-apps)
- [Agent Social Network](#-agent-social-network)
- [Configuration](#️-configuration)
  - [Environment variables and `.env`](#environment-variables-and-env)
- [Multiple Instances](#-multiple-instances)
- [Memory](#-memory)
- [CLI Reference](#-cli-reference)
- [In-Chat Commands](#-in-chat-commands)
- [Python SDK](#-python-sdk)
- [OpenAI-Compatible API](#-openai-compatible-api)
- [Docker](#-docker)
- [Linux Service](#-linux-service)
- [Project Structure](#-project-structure)
- [Contribute & Roadmap](#-contribute--roadmap)
- [Star History](#-star-history)

## ✨ Features

<table align="center">
  <tr align="center">
    <th><p align="center">📈 24/7 Real-Time Market Analysis</p></th>
    <th><p align="center">🚀 Full-Stack Software Engineer</p></th>
    <th><p align="center">📅 Smart Daily Routine Manager</p></th>
    <th><p align="center">📚 Personal Knowledge Assistant</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/scedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">Discovery • Insights • Trends</td>
    <td align="center">Develop • Deploy • Scale</td>
    <td align="center">Schedule • Automate • Organize</td>
    <td align="center">Learn • Memory • Reasoning</td>
  </tr>
</table>

## 📦 Install

> [!IMPORTANT]
> This README may describe features that are available first in the latest source code.
> If you want the newest features and experiments, install from source.
> If you want the most stable day-to-day experience, install from PyPI or with `uv`.

**Install from source** (latest features, experimental changes may land here first; recommended for development)

```bash
git clone https://github.com/derek14/janniebot.git
cd janniebot
pip install -e .
```

If you previously used the upstream project, move your data directory once: `mv ~/.nanobot ~/.janniebot` (or copy and verify before removing the old folder).

**Install with [uv](https://github.com/astral-sh/uv)** (stable release, fast)

```bash
uv tool install janniebot
```

**Install from PyPI** (stable release)

```bash
pip install janniebot
```

### Update to latest version

**PyPI / pip**

```bash
pip install -U janniebot
janniebot --version
```

**uv**

```bash
uv tool upgrade janniebot
janniebot --version
```

**Using WhatsApp?** Rebuild the local bridge after upgrading:

```bash
rm -rf ~/.janniebot/bridge
janniebot channels login whatsapp
```

## 🚀 Quick Start

> [!TIP]
> Set your API key in `~/.janniebot/config.json`, **or** in a `.env` file (project root or `~/.janniebot/.env`) — for example `OPENROUTER_API_KEY=sk-or-v1-...`. See [Environment variables and `.env`](#environment-variables-and-env).
> Get API keys: [OpenRouter](https://openrouter.ai/keys) (Global)
>
> For other LLM providers, please see the [Providers](#providers) section.
>
> For web search capability setup, please see [Web Search](#web-search).

**1. Initialize**

```bash
janniebot onboard
```

Use `janniebot onboard --wizard` if you want the interactive setup wizard.

**2. Configure** (`~/.janniebot/config.json`)

Configure these **two parts** in your config (other options have defaults).

*Set your API key* (e.g. OpenRouter, recommended for global users):
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

*Set your model* (optionally pin a provider — defaults to auto-detection):
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

**Alternative: `.env` instead of JSON for keys and overrides**

If you prefer not to put secrets in `config.json`, create `.env` in the project directory (when developing from source) or `~/.janniebot/.env`. Typical entries:

```bash
# Standard names (same as upstream SDKs); janniebot maps these into provider config
OPENROUTER_API_KEY=sk-or-v1-your-key

# Any setting from config.json can be overridden with JANNIEBOT_ + nested __ segments
JANNIEBOT_AGENTS__DEFAULTS__MODEL=openrouter/anthropic/claude-sonnet-4
```

When you use a routing prefix like `openrouter/…` in the model field, janniebot strips that segment before calling the gateway so the remote API receives a valid model id (e.g. `anthropic/claude-sonnet-4`).

**3. Chat**

```bash
janniebot agent
```

That's it! You have a working AI assistant in 2 minutes.

## 💬 Chat Apps

Connect janniebot to your favorite chat platform. Want to build your own? See the [Channel Plugin Guide](./docs/CHANNEL_PLUGIN_GUIDE.md).

| Channel | What you need |
|---------|---------------|
| **Telegram** | Bot token from @BotFather |
| **WhatsApp** | QR code scan (`janniebot channels login whatsapp`) |
| **Email** | IMAP/SMTP credentials |

<details>
<summary><b>Telegram</b> (Recommended)</summary>

**1. Create a bot**
- Open Telegram, search `@BotFather`
- Send `/newbot`, follow prompts
- Copy the token

**2. Configure**

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

> You can find your **User ID** in Telegram settings. It is shown as `@yourUserId`.
> Copy this value **without the `@` symbol** and paste it into the config file.


**3. Run**

```bash
janniebot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

Requires **Node.js ≥18**.

**1. Link device**

```bash
janniebot channels login whatsapp
# Scan QR with WhatsApp → Settings → Linked Devices
```

**2. Configure**

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

**3. Run** (two terminals)

```bash
# Terminal 1
janniebot channels login whatsapp

# Terminal 2
janniebot gateway
```

> WhatsApp bridge updates are not applied automatically for existing installations.
> After upgrading janniebot, rebuild the local bridge with:
> `rm -rf ~/.janniebot/bridge && janniebot channels login whatsapp`

</details>

<details>
<summary><b>Email</b></summary>

Give janniebot its own email account. It polls **IMAP** for incoming mail and replies via **SMTP** — like a personal email assistant.

**1. Get credentials (Gmail example)**
- Create a dedicated Gmail account for your bot (e.g. `my-janniebot@gmail.com`)
- Enable 2-Step Verification → Create an [App Password](https://myaccount.google.com/apppasswords)
- Use this app password for both IMAP and SMTP

**2. Configure**

> - `consentGranted` must be `true` to allow mailbox access. This is a safety gate — set `false` to fully disable.
> - `allowFrom`: Add your email address. Use `["*"]` to accept emails from anyone.
> - `smtpUseTls` and `smtpUseSsl` default to `true` / `false` respectively, which is correct for Gmail (port 587 + STARTTLS). No need to set them explicitly.
> - Set `"autoReplyEnabled": false` if you only want to read/analyze emails without sending automatic replies.

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "my-janniebot@gmail.com",
      "imapPassword": "your-app-password",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "my-janniebot@gmail.com",
      "smtpPassword": "your-app-password",
      "fromAddress": "my-janniebot@gmail.com",
      "allowFrom": ["your-real-email@gmail.com"]
    }
  }
}
```


**3. Run**

```bash
janniebot gateway
```

</details>

## 🌐 Agent Social Network

🐈 janniebot is capable of linking to the agent social network (agent community). **Just send one message and your janniebot joins automatically!**

| Platform | How to Join (send this message to your bot) |
|----------|-------------|
| [**Moltbook**](https://www.moltbook.com/) | `Read https://moltbook.com/skill.md and follow the instructions to join Moltbook` |
| [**ClawdChat**](https://clawdchat.ai/) | `Read https://clawdchat.ai/skill.md and follow the instructions to join ClawdChat` |

Simply send the command above to your janniebot (via CLI or any chat channel), and it will handle the rest.

## ⚙️ Configuration

Primary config file: `~/.janniebot/config.json`

Optional **`.env` files** are loaded (via `python-dotenv`) before settings are resolved: first `./.env` (current working directory), then `~/.janniebot/.env`. Variables **already set in the shell** are not overwritten by `.env` — so a bad `export OPENROUTER_API_KEY=…` in your shell profile will mask values from `.env` until you `unset` it or open a new session.

### Environment variables and `.env`

- **Provider API keys:** You can use the usual env names from each vendor (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …). janniebot copies them into the internal `JANNIEBOT_PROVIDERS__…__API_KEY` form so CLI checks and `config.json` merging behave the same as if you had set keys in JSON.
- **Structured overrides:** Any field under the Pydantic config tree can be set with prefix `JANNIEBOT_` and nested segments joined by `__`, for example `JANNIEBOT_GATEWAY__PORT=18791` or `JANNIEBOT_PROVIDERS__OPENROUTER__API_KEY=…`.
- **CLI and SDK:** The Typer CLI loads dotenv on startup; `Janniebot.from_config()` loads dotenv before reading `config.json`, so library use picks up `.env` when your process cwd is the project (or when you rely on `~/.janniebot/.env`).
- **Web search / fetch:** Keys such as `BRAVE_API_KEY`, `TAVILY_API_KEY`, `SEARXNG_BASE_URL`, and `JINA_API_KEY` are read from the environment (including values injected by `.env`).

> [!NOTE]
> If your config file is older than the current schema, you can refresh it without overwriting your existing values:
> run `janniebot onboard`, then answer `N` when asked whether to overwrite the config.
> janniebot will merge in missing default fields and keep your current settings.

### Providers

> [!TIP]
> - **Groq** provides free voice transcription via Whisper. If configured, Telegram voice messages will be automatically transcribed.
> - **MiniMax Coding Plan**: Exclusive discount links for the janniebot community: [Overseas](https://platform.minimax.io/subscribe/coding-plan?code=9txpdXw04g&source=link) · [Mainland China](https://platform.minimaxi.com/subscribe/token-plan?code=GILTJpMTqZ&source=link)
> - **MiniMax (Mainland China)**: If your API key is from MiniMax's mainland China platform (minimaxi.com), set `"apiBase": "https://api.minimaxi.com/v1"` in your minimax provider config.
> - **VolcEngine / BytePlus Coding Plan**: Use dedicated providers `volcengineCodingPlan` or `byteplusCodingPlan` instead of the pay-per-use `volcengine` / `byteplus` providers.
> - **Zhipu Coding Plan**: If you're on Zhipu's coding plan, set `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"` in your zhipu provider config.
> - **Alibaba Cloud BaiLian**: If you're using Alibaba Cloud BaiLian's OpenAI-compatible endpoint, set `"apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"` in your dashscope provider config.
> - **Step Fun (Mainland China)**: If your API key is from Step Fun's mainland China platform (stepfun.com), set `"apiBase": "https://api.stepfun.com/v1"` in your stepfun provider config.

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `custom` | Any OpenAI-compatible endpoint | — |
| `openrouter` | LLM (recommended, access to all models) | [openrouter.ai](https://openrouter.ai) |
| `volcengine` | LLM (VolcEngine, pay-per-use) | [Coding Plan](https://www.volcengine.com/activity/codingplan?utm_campaign=janniebot&utm_content=janniebot&utm_medium=devrel&utm_source=OWO&utm_term=janniebot) · [volcengine.com](https://www.volcengine.com) |
| `byteplus` | LLM (VolcEngine international, pay-per-use) | [Coding Plan](https://www.byteplus.com/en/activity/codingplan?utm_campaign=janniebot&utm_content=janniebot&utm_medium=devrel&utm_source=OWO&utm_term=janniebot) · [byteplus.com](https://www.byteplus.com) |
| `anthropic` | LLM (Claude direct) | [console.anthropic.com](https://console.anthropic.com) |
| `azure_openai` | LLM (Azure OpenAI) | [portal.azure.com](https://portal.azure.com) |
| `openai` | LLM (GPT direct) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek direct) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **Voice transcription** (Whisper) | [console.groq.com](https://console.groq.com) |
| `minimax` | LLM (MiniMax direct) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `gemini` | LLM (Gemini direct) | [aistudio.google.com](https://aistudio.google.com) |
| `aihubmix` | LLM (API gateway, access to all models) | [aihubmix.com](https://aihubmix.com) |
| `siliconflow` | LLM (SiliconFlow/硅基流动) | [siliconflow.cn](https://siliconflow.cn) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM (Moonshot/Kimi) | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM (Zhipu GLM) | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `mimo` | LLM (MiMo) | [platform.xiaomimimo.com](https://platform.xiaomimimo.com) |
| `ollama` | LLM (local, Ollama) | — |
| `mistral` | LLM | [docs.mistral.ai](https://docs.mistral.ai/) |
| `stepfun` | LLM (Step Fun/阶跃星辰) | [platform.stepfun.com](https://platform.stepfun.com) |
| `vllm` | LLM (local, any OpenAI-compatible server) | — |
| `openai_codex` | LLM (Codex, OAuth) | `janniebot provider login openai-codex` |
| `github_copilot` | LLM (GitHub Copilot, OAuth) | `janniebot provider login github-copilot` |

<details>
<summary><b>OpenAI Codex (OAuth)</b></summary>

Codex uses OAuth instead of API keys. Requires a ChatGPT Plus or Pro account.
No `providers.openaiCodex` block is needed in `config.json`; `janniebot provider login` stores the OAuth session outside config.

**1. Login:**
```bash
janniebot provider login openai-codex
```

**2. Set model** (merge into `~/.janniebot/config.json`):
```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/gpt-5.1-codex"
    }
  }
}
```

**3. Chat:**
```bash
janniebot agent -m "Hello!"

# Target a specific workspace/config locally
janniebot agent -c ~/.janniebot-telegram/config.json -m "Hello!"

# One-off workspace override on top of that config
janniebot agent -c ~/.janniebot-telegram/config.json -w /tmp/janniebot-telegram-test -m "Hello!"
```

> Docker users: use `docker run -it` for interactive OAuth login.

</details>


<details>
<summary><b>GitHub Copilot (OAuth)</b></summary>

GitHub Copilot uses OAuth instead of API keys. Requires a [GitHub account with a plan](https://github.com/features/copilot/plans) configured.
No `providers.githubCopilot` block is needed in `config.json`; `janniebot provider login` stores the OAuth session outside config.

**1. Login:**
```bash
janniebot provider login github-copilot
```

**2. Set model** (merge into `~/.janniebot/config.json`):
```json
{
  "agents": {
    "defaults": {
      "model": "github-copilot/gpt-4.1"
    }
  }
}
```

**3. Chat:**
```bash
janniebot agent -m "Hello!"

# Target a specific workspace/config locally
janniebot agent -c ~/.janniebot-telegram/config.json -m "Hello!"

# One-off workspace override on top of that config
janniebot agent -c ~/.janniebot-telegram/config.json -w /tmp/janniebot-telegram-test -m "Hello!"
```

> Docker users: use `docker run -it` for interactive OAuth login.

</details>

<details>
<summary><b>Custom Provider (Any OpenAI-compatible API)</b></summary>

Connects directly to any OpenAI-compatible endpoint — LM Studio, llama.cpp, Together AI, Fireworks, Azure OpenAI, or any self-hosted server. Model name is passed as-is.

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

> For local servers that don't require a key, set `apiKey` to any non-empty string (e.g. `"no-key"`).

</details>

<details>
<summary><b>Ollama (local)</b></summary>

Run a local model with Ollama, then add to config:

**1. Start Ollama** (example):
```bash
ollama run llama3.2
```

**2. Add to config** (partial — merge into `~/.janniebot/config.json`):
```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434"
    }
  },
  "agents": {
    "defaults": {
      "provider": "ollama",
      "model": "llama3.2"
    }
  }
}
```

> `provider: "auto"` also works when `providers.ollama.apiBase` is configured, but setting `"provider": "ollama"` is the clearest option.

</details>

<details>
<summary><b>vLLM (local / OpenAI-compatible)</b></summary>

Run your own model with vLLM or any OpenAI-compatible server, then add to config:

**1. Start the server** (example):
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. Add to config** (partial — merge into `~/.janniebot/config.json`):

*Provider (key can be any non-empty string for local):*
```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  }
}
```

*Model:*
```json
{
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

</details>

<details>
<summary><b>Adding a New Provider (Developer Guide)</b></summary>

janniebot uses a **Provider Registry** (`janniebot/providers/registry.py`) as the single source of truth.
Adding a new provider only takes **2 steps** — no if-elif chains to touch.

**Step 1.** Add a `ProviderSpec` entry to `PROVIDERS` in `janniebot/providers/registry.py`:

```python
ProviderSpec(
    name="myprovider",                   # config field name
    keywords=("myprovider", "mymodel"),  # model-name keywords for auto-matching
    env_key="MYPROVIDER_API_KEY",        # env var name
    display_name="My Provider",          # shown in `janniebot status`
    default_api_base="https://api.myprovider.com/v1",  # OpenAI-compatible endpoint
)
```

**Step 2.** Add a field to `ProvidersConfig` in `janniebot/config/schema.py`:

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

That's it! Environment variables, model routing, config matching, and `janniebot status` display will all work automatically.

**Common `ProviderSpec` options:**

| Field | Description | Example |
|-------|-------------|---------|
| `default_api_base` | OpenAI-compatible base URL | `"https://api.deepseek.com"` |
| `env_extras` | Additional env vars to set | `(("ZHIPUAI_API_KEY", "{api_key}"),)` |
| `model_overrides` | Per-model parameter overrides | `(("kimi-k2.5", {"temperature": 1.0}),)` |
| `is_gateway` | Can route any model (like OpenRouter) | `True` |
| `detect_by_key_prefix` | Detect gateway by API key prefix | `"sk-or-"` |
| `detect_by_base_keyword` | Detect gateway by API base URL | `"openrouter"` |
| `strip_model_prefix` | Strip provider prefix before sending to gateway | `True` (for AiHubMix) |
| `supports_max_completion_tokens` | Use `max_completion_tokens` instead of `max_tokens`; required for providers that reject both being set simultaneously (e.g. VolcEngine) | `True` |

</details>

### Channel Settings

Global settings that apply to all channels. Configure under the `channels` section in `~/.janniebot/config.json`:

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "sendMaxRetries": 3,
    "telegram": { ... }
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `sendProgress` | `true` | Stream agent's text progress to the channel |
| `sendToolHints` | `false` | Stream tool-call hints (e.g. `read_file("…")`) |
| `sendMaxRetries` | `3` | Max delivery attempts per outbound message, including the initial send (0-10 configured, minimum 1 actual attempt) |

#### Retry Behavior

Retry is intentionally simple.

When a channel `send()` raises, janniebot retries at the channel-manager layer. By default, `channels.sendMaxRetries` is `3`, and that count includes the initial send.

- **Attempt 1**: Send immediately
- **Attempt 2**: Retry after `1s`
- **Attempt 3**: Retry after `2s`
- **Higher retry budgets**: Backoff continues as `1s`, `2s`, `4s`, then stays capped at `4s`
- **Transient failures**: Network hiccups and temporary API limits often recover on the next attempt
- **Permanent failures**: Invalid tokens, revoked access, or banned channels will exhaust the retry budget and fail cleanly

> [!NOTE]
> This design is deliberate: channel implementations should raise on delivery failure, and the channel manager owns the shared retry policy.
>
> Some channels may still apply small API-specific retries internally. For example, Telegram separately retries timeout and flood-control errors before surfacing a final failure to the manager.
>
> If a channel is completely unreachable, janniebot cannot notify the user through that same channel. Watch logs for `Failed to send to {channel} after N attempts` to spot persistent delivery failures.

### Web Search

> [!TIP]
> Use `proxy` in `tools.web` to route all web requests (search + fetch) through a proxy:
> ```json
> { "tools": { "web": { "proxy": "http://127.0.0.1:7890" } } }
> ```

janniebot supports multiple web search providers. Configure in `~/.janniebot/config.json` under `tools.web.search`.

By default, web tools are enabled and web search uses `duckduckgo`, so search works out of the box without an API key.

If you want to disable all built-in web tools entirely, set `tools.web.enable` to `false`. This removes both `web_search` and `web_fetch` from the tool list sent to the LLM.

If you need to allow trusted private ranges such as Tailscale / CGNAT addresses, you can explicitly exempt them from SSRF blocking with `tools.ssrfWhitelist`:

```json
{
  "tools": {
    "ssrfWhitelist": ["100.64.0.0/10"]
  }
}
```

| Provider | Config fields | Env var fallback | Free |
|----------|--------------|------------------|------|
| `brave` | `apiKey` | `BRAVE_API_KEY` | No |
| `tavily` | `apiKey` | `TAVILY_API_KEY` | No |
| `jina` | `apiKey` | `JINA_API_KEY` | Free tier (10M tokens) |
| `searxng` | `baseUrl` | `SEARXNG_BASE_URL` | Yes (self-hosted) |
| `duckduckgo` (default) | — | — | Yes |

**Disable all built-in web tools:**
```json
{
  "tools": {
    "web": {
      "enable": false
    }
  }
}
```

**Brave:**
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "BSA..."
      }
    }
  }
}
```

**Tavily:**
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "tavily",
        "apiKey": "tvly-..."
      }
    }
  }
}
```

**Jina** (free tier with 10M tokens):
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "jina",
        "apiKey": "jina_..."
      }
    }
  }
}
```

**SearXNG** (self-hosted, no API key needed):
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "searxng",
        "baseUrl": "https://searx.example"
      }
    }
  }
}
```

**DuckDuckGo** (zero config):
```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | boolean | `true` | Enable or disable all built-in web tools (`web_search` + `web_fetch`) |
| `proxy` | string or null | `null` | Proxy for all web requests, for example `http://127.0.0.1:7890` |

#### `tools.web.search`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `provider` | string | `"duckduckgo"` | Search backend: `brave`, `tavily`, `jina`, `searxng`, `duckduckgo` |
| `apiKey` | string | `""` | API key for Brave or Tavily |
| `baseUrl` | string | `""` | Base URL for SearXNG |
| `maxResults` | integer | `5` | Results per search (1–10) |

### MCP (Model Context Protocol)

> [!TIP]
> The config format is compatible with Claude Desktop / Cursor. You can copy MCP server configs directly from any MCP server's README.

janniebot supports [MCP](https://modelcontextprotocol.io/) — connect external tool servers and use them as native agent tools.

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

Two transport modes are supported:

| Mode | Config | Example |
|------|--------|---------|
| **Stdio** | `command` + `args` | Local process via `npx` / `uvx` |
| **HTTP** | `url` + `headers` (optional) | Remote endpoint (`https://mcp.example.com/sse`) |

Use `toolTimeout` to override the default 30s per-call timeout for slow servers:

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

Use `enabledTools` to register only a subset of tools from an MCP server:

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
        "enabledTools": ["read_file", "mcp_filesystem_write_file"]
      }
    }
  }
}
```

`enabledTools` accepts either the raw MCP tool name (for example `read_file`) or the wrapped janniebot tool name (for example `mcp_filesystem_write_file`).

- Omit `enabledTools`, or set it to `["*"]`, to register all tools.
- Set `enabledTools` to `[]` to register no tools from that server.
- Set `enabledTools` to a non-empty list of names to register only that subset.

MCP tools are automatically discovered and registered on startup. The LLM can use them alongside built-in tools — no extra configuration needed.




### Security

> [!TIP]
> For production deployments, set `"restrictToWorkspace": true` in your config to sandbox the agent.
> In `v0.1.4.post3` and earlier, an empty `allowFrom` allowed all senders. Since `v0.1.4.post4`, empty `allowFrom` denies all access by default. To allow all senders, set `"allowFrom": ["*"]`.

| Option | Default | Description |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | When `true`, restricts **all** agent tools (shell, file read/write/edit, list) to the workspace directory. Prevents path traversal and out-of-scope access. |
| `tools.exec.enable` | `true` | When `false`, the shell `exec` tool is not registered at all. Use this to completely disable shell command execution. |
| `tools.exec.pathAppend` | `""` | Extra directories to append to `PATH` when running shell commands (e.g. `/usr/sbin` for `ufw`). |
| `channels.*.allowFrom` | `[]` (deny all) | Whitelist of user IDs. Empty denies all; use `["*"]` to allow everyone. |


### Timezone

Time is context. Context should be precise.

By default, janniebot uses `UTC` for runtime time context. If you want the agent to think in your local time, set `agents.defaults.timezone` to a valid [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones):

```json
{
  "agents": {
    "defaults": {
      "timezone": "Asia/Shanghai"
    }
  }
}
```

This affects runtime time strings shown to the model, such as runtime context and heartbeat prompts. It also becomes the default timezone for cron schedules when a cron expression omits `tz`, and for one-shot `at` times when the ISO datetime has no explicit offset.

Common examples: `UTC`, `America/New_York`, `America/Los_Angeles`, `Europe/London`, `Europe/Berlin`, `Asia/Tokyo`, `Asia/Shanghai`, `Asia/Singapore`, `Australia/Sydney`.

> Need another timezone? Browse the full [IANA Time Zone Database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

## 🧩 Multiple Instances

Run multiple janniebot instances simultaneously with separate configs and runtime data. Use `--config` as the main entrypoint. Optionally pass `--workspace` during `onboard` when you want to initialize or update the saved workspace for a specific instance.

### Quick Start

If you want each instance to have its own dedicated workspace from the start, pass both `--config` and `--workspace` during onboarding.

**Initialize instances:**

```bash
# Create separate instance configs and workspaces
janniebot onboard --config ~/.janniebot-telegram/config.json --workspace ~/.janniebot-telegram/workspace
janniebot onboard --config ~/.janniebot-whatsapp/config.json --workspace ~/.janniebot-whatsapp/workspace
janniebot onboard --config ~/.janniebot-email/config.json --workspace ~/.janniebot-email/workspace
```

**Configure each instance:**

Edit each instance `config.json` with different channel settings. The workspace you passed during `onboard` is saved into each config as that instance's default workspace.

**Run instances:**

```bash
# Instance A - Telegram bot
janniebot gateway --config ~/.janniebot-telegram/config.json

# Instance B - WhatsApp bot
janniebot gateway --config ~/.janniebot-whatsapp/config.json

# Instance C - Email gateway with custom port
janniebot gateway --config ~/.janniebot-email/config.json --port 18792
```

### Path Resolution

When using `--config`, janniebot derives its runtime data directory from the config file location. The workspace still comes from `agents.defaults.workspace` unless you override it with `--workspace`.

To open a CLI session against one of these instances locally:

```bash
janniebot agent -c ~/.janniebot-telegram/config.json -m "Hello from Telegram instance"
janniebot agent -c ~/.janniebot-whatsapp/config.json -m "Hello from WhatsApp instance"

# Optional one-off workspace override
janniebot agent -c ~/.janniebot-telegram/config.json -w /tmp/janniebot-telegram-test
```

> `janniebot agent` starts a local CLI agent using the selected workspace/config. It does not attach to or proxy through an already running `janniebot gateway` process.

| Component | Resolved From | Example |
|-----------|---------------|---------|
| **Config** | `--config` path | `~/.janniebot-A/config.json` |
| **Workspace** | `--workspace` or config | `~/.janniebot-A/workspace/` |
| **Cron Jobs** | config directory | `~/.janniebot-A/cron/` |
| **Media / runtime state** | config directory | `~/.janniebot-A/media/` |

### How It Works

- `--config` selects which config file to load
- By default, the workspace comes from `agents.defaults.workspace` in that config
- If you pass `--workspace`, it overrides the workspace from the config file

### Minimal Setup

1. Copy your base config into a new instance directory.
2. Set a different `agents.defaults.workspace` for that instance.
3. Start the instance with `--config`.

Example config:

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.janniebot-telegram/workspace",
      "model": "anthropic/claude-sonnet-4-6"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN"
    }
  },
  "gateway": {
    "port": 18790
  }
}
```

Start separate instances:

```bash
janniebot gateway --config ~/.janniebot-telegram/config.json
janniebot gateway --config ~/.janniebot-whatsapp/config.json
```

Override workspace for one-off runs when needed:

```bash
janniebot gateway --config ~/.janniebot-telegram/config.json --workspace /tmp/janniebot-telegram-test
```

### Common Use Cases

- Run separate bots for Telegram, WhatsApp, Email, and other platforms
- Keep testing and production instances isolated
- Use different models or providers for different teams
- Serve multiple tenants with separate configs and runtime data

### Notes

- Each instance must use a different port if they run at the same time
- Use a different workspace per instance if you want isolated memory, sessions, and skills
- `--workspace` overrides the workspace defined in the config file
- Cron jobs and runtime media/state are derived from the config directory

## 🧠 Memory

janniebot uses a layered memory system designed to stay light in the moment and durable over
time.

- `memory/history.jsonl` stores append-only summarized history
- `SOUL.md`, `USER.md`, and `memory/MEMORY.md` store long-term knowledge managed by Dream
- `Dream` runs on a schedule and can also be triggered manually
- memory changes can be inspected and restored with built-in commands

If you want the full design, see [docs/MEMORY.md](docs/MEMORY.md).

## 💻 CLI Reference

| Command | Description |
|---------|-------------|
| `janniebot onboard` | Initialize config & workspace at `~/.janniebot/` |
| `janniebot onboard --wizard` | Launch the interactive onboarding wizard |
| `janniebot onboard -c <config> -w <workspace>` | Initialize or refresh a specific instance config and workspace |
| `janniebot agent -m "..."` | Chat with the agent |
| `janniebot agent -w <workspace>` | Chat against a specific workspace |
| `janniebot agent -w <workspace> -c <config>` | Chat against a specific workspace/config |
| `janniebot agent` | Interactive chat mode |
| `janniebot agent --no-markdown` | Show plain-text replies |
| `janniebot agent --logs` | Show runtime logs during chat |
| `janniebot serve` | Start the OpenAI-compatible API |
| `janniebot gateway` | Start the gateway |
| `janniebot status` | Show status |
| `janniebot provider login openai-codex` | OAuth login for providers |
| `janniebot channels login <channel>` | Authenticate a channel interactively |
| `janniebot channels status` | Show channel status |

Interactive mode exits: `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.

## 💬 In-Chat Commands

These commands work inside chat channels and interactive agent sessions:

| Command | Description |
|---------|-------------|
| `/new` | Start a new conversation |
| `/stop` | Stop the current task |
| `/restart` | Restart the bot |
| `/status` | Show bot status |
| `/dream` | Run Dream memory consolidation now |
| `/dream-log` | Show the latest Dream memory change |
| `/dream-log <sha>` | Show a specific Dream memory change |
| `/dream-restore` | List recent Dream memory versions |
| `/dream-restore <sha>` | Restore memory to the state before a specific change |
| `/help` | Show available in-chat commands |

<details>
<summary><b>Heartbeat (Periodic Tasks)</b></summary>

The gateway wakes up every 30 minutes and checks `HEARTBEAT.md` in your workspace (`~/.janniebot/workspace/HEARTBEAT.md`). If the file has tasks, the agent executes them and delivers results to your most recently active chat channel.

**Setup:** edit `~/.janniebot/workspace/HEARTBEAT.md` (created automatically by `janniebot onboard`):

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

The agent can also manage this file itself — ask it to "add a periodic task" and it will update `HEARTBEAT.md` for you.

> **Note:** The gateway must be running (`janniebot gateway`) and you must have chatted with the bot at least once so it knows which channel to deliver to.

</details>

## 🐍 Python SDK

Use janniebot as a library — no CLI, no gateway, just Python:

```python
from janniebot import Janniebot

bot = Janniebot.from_config()
result = await bot.run("Summarize the README")
print(result.content)
```

`from_config()` loads `.env` from the current working directory and from `~/.janniebot/.env` before merging `config.json`, so the same env-based setup as the CLI applies to scripts.

Each call carries a `session_key` for conversation isolation — different keys get independent history:

```python
await bot.run("hi", session_key="user-alice")
await bot.run("hi", session_key="task-42")
```

Add lifecycle hooks to observe or customize the agent:

```python
from janniebot.agent import AgentHook, AgentHookContext

class AuditHook(AgentHook):
    async def before_execute_tools(self, ctx: AgentHookContext) -> None:
        for tc in ctx.tool_calls:
            print(f"[tool] {tc.name}")

result = await bot.run("Hello", hooks=[AuditHook()])
```

See [docs/PYTHON_SDK.md](docs/PYTHON_SDK.md) for the full SDK reference.

## 🔌 OpenAI-Compatible API

janniebot can expose a minimal OpenAI-compatible endpoint for local integrations:

```bash
pip install "janniebot[api]"
janniebot serve
```

By default, the API binds to `127.0.0.1:8900`. You can change this in `config.json` or with `JANNIEBOT_API__HOST` / `JANNIEBOT_API__PORT` in `.env`.

### Behavior

- Session isolation: pass `"session_id"` in the request body to isolate conversations; omit for a shared default session (`api:default`)
- Single-message input: each request must contain exactly one `user` message
- Fixed model: omit `model`, or pass the same model shown by `/v1/models`
- No streaming: `stream=true` is not supported

### Endpoints

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`

### curl

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "hi"}],
    "session_id": "my-session"
  }'
```

### Python (`requests`)

```python
import requests

resp = requests.post(
    "http://127.0.0.1:8900/v1/chat/completions",
    json={
        "messages": [{"role": "user", "content": "hi"}],
        "session_id": "my-session",  # optional: isolate conversation
    },
    timeout=120,
)
resp.raise_for_status()
print(resp.json()["choices"][0]["message"]["content"])
```

### Python (`openai`)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8900/v1",
    api_key="dummy",
)

resp = client.chat.completions.create(
    model="MiniMax-M2.7",
    messages=[{"role": "user", "content": "hi"}],
    extra_body={"session_id": "my-session"},  # optional: isolate conversation
)
print(resp.choices[0].message.content)
```

## 🐳 Docker

> [!TIP]
> The `-v ~/.janniebot:/root/.janniebot` flag mounts your local config directory into the container, so your config and workspace persist across container restarts.

### Docker Compose

```bash
docker compose run --rm janniebot-cli onboard   # first-time setup
vim ~/.janniebot/config.json                     # add API keys (or use ~/.janniebot/.env on the host)
docker compose up -d janniebot-gateway           # start gateway
```

You can keep secrets in `~/.janniebot/.env` on the host; the default compose mount `~/.janniebot:/root/.janniebot` makes that file visible inside the container. Alternatively, add `env_file: .env` to a service if you keep a `.env` next to `docker-compose.yml`.

```bash
docker compose run --rm janniebot-cli agent -m "Hello!"   # run CLI
docker compose logs -f janniebot-gateway                   # view logs
docker compose down                                      # stop
```

### Docker

```bash
# Build the image
docker build -t janniebot .

# Initialize config (first time only)
docker run -v ~/.janniebot:/root/.janniebot --rm janniebot onboard

# Edit config on host to add API keys
vim ~/.janniebot/config.json

# Run gateway (connects to enabled channels, e.g. Telegram/WhatsApp/Email)
docker run -v ~/.janniebot:/root/.janniebot -p 18790:18790 janniebot gateway

# Or run a single command
docker run -v ~/.janniebot:/root/.janniebot --rm janniebot agent -m "Hello!"
docker run -v ~/.janniebot:/root/.janniebot --rm janniebot status
```

## 🐧 Linux Service

Run the gateway as a systemd user service so it starts automatically and restarts on failure.

**1. Find the janniebot binary path:**

```bash
which janniebot   # e.g. /home/user/.local/bin/janniebot
```

**2. Create the service file** at `~/.config/systemd/user/janniebot-gateway.service` (replace `ExecStart` path if needed):

```ini
[Unit]
Description=janniebot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/janniebot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

**3. Enable and start:**

```bash
systemctl --user daemon-reload
systemctl --user enable --now janniebot-gateway
```

**Common operations:**

```bash
systemctl --user status janniebot-gateway        # check status
systemctl --user restart janniebot-gateway       # restart after config changes
journalctl --user -u janniebot-gateway -f        # follow logs
```

If you edit the `.service` file itself, run `systemctl --user daemon-reload` before restarting.

> **Note:** User services only run while you are logged in. To keep the gateway running after logout, enable lingering:
>
> ```bash
> loginctl enable-linger $USER
> ```

## 📁 Project Structure

```
janniebot/
├── agent/          # 🧠 Core agent logic
│   ├── loop.py     #    Agent loop (LLM ↔ tool execution)
│   ├── context.py  #    Prompt builder
│   ├── memory.py   #    Persistent memory
│   ├── skills.py   #    Skills loader
│   ├── subagent.py #    Background task execution
│   └── tools/      #    Built-in tools (incl. spawn)
├── skills/         # 🎯 Bundled skills (github, weather, tmux...)
├── channels/       # 📱 Chat channel integrations (supports plugins)
├── bus/            # 🚌 Message routing
├── cron/           # ⏰ Scheduled tasks
├── heartbeat/      # 💓 Proactive wake-up
├── providers/      # 🤖 LLM providers (OpenRouter, etc.)
├── session/        # 💬 Conversation sessions
├── config/         # ⚙️ Configuration
└── cli/            # 🖥️ Commands
```

## 🤝 Contribute & Roadmap

PRs welcome! The codebase is intentionally small and readable. 🤗

### Branching Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases — bug fixes and minor improvements |
| `nightly` | Experimental features — new features and breaking changes |

**Unsure which branch to target?** See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.

**Roadmap** — Pick an item and [open a PR](https://github.com/derek14/janniebot/pulls)!

- [ ] **Multi-modal** — See and hear (images, voice, video)
- [ ] **Long-term memory** — Never forget important context
- [ ] **Better reasoning** — Multi-step planning and reflection
- [ ] **More integrations** — Calendar and more
- [ ] **Self-improvement** — Learn from feedback and mistakes

### Contributors

<a href="https://github.com/derek14/janniebot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=derek14/janniebot&max=100&columns=12&updated=20260210" alt="Contributors" />
</a>


## ⭐ Star History

<div align="center">
  <a href="https://star-history.com/#derek14/janniebot&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=derek14/janniebot&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=derek14/janniebot&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=derek14/janniebot&type=Date" style="border-radius: 15px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.3);" />
    </picture>
  </a>
</div>

<p align="center">
  <em> Thanks for visiting ✨ janniebot!</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=derek14.janniebot&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>janniebot is for educational, research, and technical exchange purposes only</sub>
</p>
