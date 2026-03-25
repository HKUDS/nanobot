# LLM Provider Overview

This document explains nanobot’s provider mechanism—what a provider is, how it is auto-detected, and how to choose a service.

---

## What is a provider?

A **provider** bridges nanobot with an external large language model (LLM) service. Each provider encapsulates:

- API key and endpoint URL
- Model name keywords (used for auto-detection)
- Whether it is a gateway service or a local deployment
- Special parameter overrides (for example, Kimi requires `temperature >= 1.0`)

All providers are defined in `nanobot/providers/registry.py`, which acts as the single source of truth.

---

## Auto-detection order

nanobot uses a three-stage priority to resolve which provider should handle a request:

### 1. API key prefix detection

Some providers expose distinct API key prefixes, and nanobot recognizes them automatically:

| Key prefix | Provider |
|------------|----------|
| `sk-or-v1-...` | OpenRouter |

### 2. API base URL keyword detection

When you override `api_base`, nanobot checks the URL for known keywords:

| URL keyword | Provider |
|-------------|----------|
| `openrouter` | OpenRouter |
| `aihubmix` | AiHubMix |
| `siliconflow` | SiliconFlow |
| `volces` | VolcEngine |
| `bytepluses` | BytePlus |
| `11434` | Ollama (local) |

### 3. Model name keyword detection

If neither of the above match, nanobot inspects the model name:

| Keyword in model | Provider |
|------------------|----------|
| `anthropic`, `claude` | Anthropic |
| `openai`, `gpt` | OpenAI |
| `deepseek` | DeepSeek |
| `gemini` | Google Gemini |
| `zhipu`, `glm`, `zai` | Zhipu AI |
| `qwen`, `dashscope` | DashScope (Alibaba Cloud) |
| `moonshot`, `kimi` | Moonshot |
| `minimax` | MiniMax |
| `stepfun`, `step` | Step Fun |
| `mistral` | Mistral |
| `groq` | Groq |
| `ollama`, `nemotron` | Ollama |
| `vllm` | vLLM / local |

> **Note:** Gateway services and local deployments are only detected via API key prefixes or URL keywords; they do not participate in model name matching.

---

## Supported providers

nanobot supports over 28 providers, grouped by type:

### Gateway services (route any model)

Gateway providers offer access to multiple vendors through a single API key. They typically provide billing flexibility and failover resilience.

| Provider | Description | Recommendation |
|----------|-------------|----------------|
| **OpenRouter** | Global gateway with 300+ models | ⭐⭐⭐⭐⭐ Top choice |
| **AiHubMix** | OpenAI-compatible interface with multi-model support | ⭐⭐⭐⭐ |
| **SiliconFlow** | Local provider with free quota and open-source models | ⭐⭐⭐⭐ |
| **VolcEngine** | ByteDance cloud, pay-as-you-go | ⭐⭐⭐ |
| **VolcEngine Coding Plan** | Coding-focused plan on VolcEngine | ⭐⭐⭐ |
| **BytePlus** | ByteDance international cloud | ⭐⭐⭐ |
| **BytePlus Coding Plan** | Coding-focused BytePlus plan | ⭐⭐⭐ |

### Direct cloud providers

Official API endpoints from each vendor:

| Provider | Primary models | Region |
|----------|----------------|--------|
| **Anthropic** | Claude Opus / Sonnet / Haiku | Global |
| **OpenAI** | GPT-4o, GPT-4 Turbo, o1 / o3 | Global |
| **DeepSeek** | DeepSeek-V3, DeepSeek-R1 | Global / China |
| **Google Gemini** | Gemini 2.0 Flash / Pro | Global |
| **Zhipu AI** | GLM-4, GLM-Z1 | China |
| **DashScope** | Qwen series | China / global |
| **Moonshot (Kimi)** | Kimi K2.5, moonshot-v1 | China / global |
| **MiniMax** | MiniMax-M2.1 | China |
| **Step Fun** | Step (阶跃星辰) models | Global / China |
| **Mistral** | Mistral Large, Codestral | Global (Europe) |
| **Groq** | Llama, Mixtral (ultra-fast inference) + Whisper voice | Global |

### OAuth providers (no API key required)

| Provider | Auth method | Requirement |
|----------|-------------|-------------|
| **OpenAI Codex** | OAuth login | ChatGPT Plus / Pro subscription |
| **GitHub Copilot** | OAuth login | GitHub Copilot subscription |

### Direct endpoints

| Provider | Description |
|----------|-------------|
| **Azure OpenAI** | Call Azure deployment directly |
| **Custom** | Any OpenAI-compatible endpoint |

### Local deployments

| Provider | Description |
|----------|-------------|
| **Ollama** | Auto-detected on `localhost:11434` |
| **vLLM** | Any OpenAI-compatible local server |

---

## How to choose a provider

### New user who just wants to get started

Use **OpenRouter**. One key unlocks almost every mainstream model, so you do not need to sign up for multiple vendors. See the [OpenRouter setup guide](./openrouter.md).

### Want to use Claude directly

Use the official **Anthropic** API. It supports prompt caching to save costs and exposes the Thinking parameter for reasoning intensity. See the [Anthropic setup guide](./anthropic.md).

### Prefer GPT models

Use the **OpenAI** API or the **OpenAI Codex** OAuth flow (requires ChatGPT Plus / Pro). See the [OpenAI setup guide](./openai.md).

### Operating in mainland China

Recommended vendors:

- **SiliconFlow** — free tier and open-source models such as Qwen and DeepSeek
- **DashScope** — Alibaba’s Qwen lineup with the most stable experience
- **Moonshot** — Kimi K2.5 via `api.moonshot.cn`
- **Zhipu AI** — GLM series models

See the [other cloud providers](./others.md) guide for details.

### Running locally without touching the cloud

Use **Ollama** or **vLLM**. See the [local/self-hosted models](./local.md) guide.

### Already have GitHub Copilot or ChatGPT Plus

Use OAuth—no additional API quota needed. See the [OpenAI setup guide](./openai.md).

---

## Provider configuration format

All provider configurations live under the `providers` node and follow the same structure:

```json
{
  "providers": {
    "<provider_name>": {
      "api_key": "your-api-key",
      "api_base": "https://custom-endpoint.example.com/v1",
      "extra_headers": {
        "X-Custom-Header": "value"
      }
    }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `api_key` | Yes (except OAuth providers) | The service API key |
| `api_base` | No | Override the default endpoint |
| `extra_headers` | No | Additional HTTP headers |

---

## Provider failover and routing

### Configuring multiple providers

You may configure multiple providers under `providers`. nanobot auto-selects the most suitable one based on the model name.

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5"
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-..."
    },
    "openai": {
      "api_key": "sk-..."
    },
    "deepseek": {
      "api_key": "sk-..."
    }
  }
}
```

`claude-opus-4-5` contains the keyword `claude`, so nanobot automatically routes it through the `anthropic` provider.

### Force a specific provider

To always use a particular provider regardless of the model name, set `agents.defaults.provider`:

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-..."
    }
  }
}
```

### Gateway priority

Gateway providers (OpenRouter, AiHubMix, etc.) are listed first in `registry.py`. When a gateway key is configured and valid, nanobot prefers it. Standard providers (Anthropic, OpenAI, etc.) follow, using model keyword matching.

---

## Further reading

- [OpenRouter (recommended gateway)](./openrouter.md)
- [Anthropic / Claude models](./anthropic.md)
- [OpenAI / GPT models](./openai.md)
- [Other cloud providers](./others.md)
- [Local / self-hosted models](./local.md)
