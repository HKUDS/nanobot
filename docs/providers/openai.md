# OpenAI (GPT models)

Nanobot supports three ways to use OpenAI models: direct API key access, OpenAI Codex OAuth (ChatGPT Plus/Pro), and GitHub Copilot OAuth.

---

## Method 1: Direct OpenAI API

### Get an API key

1. Visit the OpenAI Platform (platform.openai.com)
2. After signing in, open the **API Keys** page
3. Click **Create new secret key**
4. Copy the key (format: `sk-proj-xxxxxxxx...` or legacy `sk-xxxxxxxx...`)

> OpenAI uses a prepaid billing model. You must add funds on the Billing page before the API becomes usable.

### Available models

**GPT-4o series**

| Model ID | Description |
|--------|------|
| `gpt-4o` | Multimodal flagship with image inputs |
| `gpt-4o-mini` | Cost-effective, faster response |
| `gpt-4o-audio-preview` | Supports audio input and output |

**o-series reasoning models**

| Model ID | Description |
|--------|------|
| `o3` | Latest inference flagship |
| `o3-mini` | Lightweight reasoning model |
| `o4-mini` | Fast inference with balanced cost |
| `o1` | First-generation reasoning model |

**GPT-4 Turbo**

| Model ID | Description |
|--------|------|
| `gpt-4-turbo` | 128K context window with vision support |
| `gpt-4` | Standard GPT-4 |

> See the OpenAI Platform Models page for the full list.

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "gpt-4o"
    }
  },
  "providers": {
    "openai": {
      "api_key": "sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Use a custom API base (e.g., proxy server)

```json
{
  "providers": {
    "openai": {
      "api_key": "sk-proj-...",
      "api_base": "https://your-proxy.example.com/v1"
    }
  }
}
```

---

## Method 2: OpenAI Codex OAuth (ChatGPT Plus/Pro)

The OpenAI Codex provider allows ChatGPT Plus or Pro subscribers to authenticate via OAuth without buying API credits.

> **Important:** This route goes through the ChatGPT web backend, so behavior may not match the official API exactly and is subject to ChatGPT's terms of service.

### Prerequisites

- Active ChatGPT Plus or Pro subscription
- Logged in to ChatGPT (chatgpt.com) in a browser

### Setup steps

1. Enable the `openai_codex` provider in your config (no `api_key` needed):

```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/auto",
      "provider": "openai_codex"
    }
  },
  "providers": {
    "openai_codex": {}
  }
}
```

2. Start nanobot; it will guide you through the OAuth flow (opens a browser to log into ChatGPT).
3. Once authorized, the OAuth token is cached locally for future launches.

### Model detection

Nanobot detects this provider when the `api_base` contains `codex` or the model name contains `openai-codex`:

```json
{
  "providers": {
    "openai_codex": {
      "api_base": "https://chatgpt.com/backend-api"
    }
  }
}
```

> **Limitation:** OAuth providers cannot serve as fallbacks. You must explicitly specify `provider: "openai_codex"` or use models prefixed with `openai-codex/`.

---

## Method 3: GitHub Copilot OAuth

The GitHub Copilot provider lets subscribers authenticate via OAuth with their Copilot subscription.

### Prerequisites

- Active GitHub Copilot Individual, Business, or Enterprise subscription
- GitHub CLI (`gh`) or GitHub Desktop installed and logged in

### Configuration example

```json
{
  "agents": {
    "defaults": {
      "model": "github_copilot/claude-sonnet-4-5",
      "provider": "github_copilot"
    }
  },
  "providers": {
    "github_copilot": {}
  }
}
```

Model names follow the `github_copilot/{model}` pattern. Examples:

- `github_copilot/claude-sonnet-4-5`
- `github_copilot/gpt-4o`
- `github_copilot/o3-mini`

### Authorization flow

When nanobot starts, it automatically launches the OAuth flow. Log in with your GitHub account; the token is cached for later use.

### Model detection

Nanobot identifies GitHub Copilot when:
- The model name contains `github_copilot` or `copilot`
- `provider` is explicitly set to `github_copilot`

Because `skip_prefixes` is configured, `github_copilot/claude-sonnet-4-5` won't be mistaken for OpenAI Codex.

---

## Comparison of the three methods

| | Direct API | Codex OAuth | Copilot OAuth |
|--|---------|-------------|---------------|
| **Requires API key** | Yes | No | No |
| **Requires subscription** | No (pay-as-you-go) | ChatGPT Plus/Pro | GitHub Copilot |
| **Available models** | All OpenAI models | Models available via ChatGPT | Models supported by Copilot |
| **Cost** | Token-based billing | Covered by subscription | Covered by subscription |
| **Stability** | Most stable | Depends on ChatGPT service | Depends on GitHub service |
| **Recommended for** | General developers | ChatGPT subscribers | Copilot subscribers |

---

## FAQ

**Q: What is the difference between `gpt-4o` and `gpt-4o-mini`?**
`gpt-4o` is the premium version with stronger reasoning; `gpt-4o-mini` offers sufficient performance for most tasks at around 15x lower cost.

**Q: Do the o-series reasoning models support streaming outputs?**
Yes. Nanobot supports streaming with the o-series. These models skip incompatible parameters like `temperature` automatically.

**Q: How do I go from ChatGPT Plus to an OpenAI API account?**
They are separate account systems. For API access, create an account at platform.openai.com and add funds. The Codex OAuth route lets you leverage your existing ChatGPT Plus subscription without extra charges.

---

## Further reading

- Provider overview: [providers/index.md](./index.md)
- OpenRouter (unified gateway): [providers/openrouter.md](./openrouter.md)
- Official docs: OpenAI Platform API Reference and Models pages
