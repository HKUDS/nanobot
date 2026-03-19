# OpenRouter (recommended default provider)

OpenRouter is the recommended on-ramp provider for nanobot. A single API key unlocks access to 300+ models from Anthropic, OpenAI, Google, Meta, Mistral, and many more.

---

## What is OpenRouter and why use it?

OpenRouter is an LLM gateway that exposes a unified OpenAI-compatible API while routing requests to individual provider backends.

**Why we recommend it:**

- **One key fits all** — no need to sign up separately for Anthropic, OpenAI, Google, etc.
- **Pay-as-you-go** — each model is billed individually, so you can try expensive models at lower cost.
- **Free models** — some models (Llama, Qwen series) offer free usage tiers.
- **Automatic fallback** — configure provider fallbacks for the same model.
- **Smart routing** — choose the best provider based on latency or cost.
- **Prompt caching support** — nanobot enables prompt caching when routing through OpenRouter.

---

## Get an API key

1. Visit openrouter.ai
2. Click **Sign In** or **Get Started** and log in via Google/GitHub
3. Open **Settings → Keys**
4. Click **Create Key**
5. Copy the key (format: `sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`)

> **Important:** nanobot detects OpenRouter by the `sk-or-` prefix, so you do not need to set `api_base` manually.

---

## Configuration examples

### Minimal setup (use the default model)

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Full setup

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  },
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "api_base": "https://openrouter.ai/api/v1"
    }
  }
}
```

> `api_base` is optional. When `sk-or-` keys are detected, nanobot automatically defaults to `https://openrouter.ai/api/v1`.

---

## Selecting a specific model via OpenRouter

OpenRouter model IDs use the `{provider}/{model}` format. For example:

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

### Common models

The following model IDs are frequently used through OpenRouter (`provider/model` format):

**Anthropic Claude series**

| Model ID | Notes |
|--------|------|
| `anthropic/claude-opus-4-5` | Claude Opus, top reasoning performance |
| `anthropic/claude-sonnet-4-5` | Claude Sonnet balances capability and cost |
| `anthropic/claude-haiku-3-5` | Claude Haiku, fastest and cheapest |

**OpenAI GPT series**

| Model ID | Notes |
|--------|------|
| `openai/gpt-4o` | GPT-4o multimodal flagship |
| `openai/gpt-4o-mini` | GPT-4o Mini, cost-effective |
| `openai/o3` | o3 reasoning model |

**Google Gemini series**

| Model ID | Notes |
|--------|------|
| `google/gemini-2.0-flash-001` | Gemini 2.0 Flash, optimized for speed |
| `google/gemini-2.5-pro-preview` | Gemini 2.5 Pro preview, long context |

**Open-source models (often free tier)**

| Model ID | Notes |
|--------|------|
| `meta-llama/llama-3.3-70b-instruct` | Meta Llama 3.3 70B |
| `qwen/qwen-2.5-72b-instruct` | Alibaba Qwen 2.5 72B |
| `deepseek/deepseek-chat` | DeepSeek V3 |
| `deepseek/deepseek-r1` | DeepSeek R1 reasoning model |
| `mistralai/mistral-large-2411` | Mistral Large |

> View the full list on the OpenRouter Models page and filter by use case, cost, and context length.

---

## Cost optimization tips

### 1. Use the free-tier models

Many open-source models on OpenRouter offer free quotas, perfect for lightweight workloads:
- `meta-llama/llama-3.3-70b-instruct:free`
- `google/gemini-2.0-flash-exp:free`

Appending `:free` forces the free tier (subject to rate limits).

### 2. Match the model to the task

- **Quick answers** — use `claude-haiku` or `gpt-4o-mini` for 10–20x lower cost
- **Code generation** — `claude-sonnet` or `deepseek-chat` balance quality and cost
- **Complex reasoning** — reserve `claude-opus` or `o3` for heavy tasks

### 3. Take advantage of prompt caching

Nanobot enables prompt caching for OpenRouter so repeated system prompts and tool definitions are not billed multiple times. For cache-capable models, this can cut repeated input costs by 50–90%.

### 4. Set spending limits

Use the Billing page on OpenRouter to configure daily or monthly caps and prevent surprise charges.

---

## Rate limits

Limits vary by account level and model:

| Account status | Limit |
|---------|------|
| Unfunded | 50 requests/day (free models) |
| Funded | Limits depend on the target provider/model, typically more generous |
| Enterprise | Contact OpenRouter sales |

If you see `429 Too Many Requests`, try:
1. Review the rate limit on OpenRouter’s model page
2. Enable Provider Fallback on the OpenRouter dashboard
3. Reduce nanobot’s concurrent request volume

---

## FAQ

**Q: Does OpenRouter support streaming output?**
Yes. Nanobot uses streaming by default, and OpenRouter fully supports it.

**Q: Can I access commercial-licensed models through OpenRouter?**
Some models require compliance with the provider's terms. Check each model's page for requirements.

**Q: Is OpenRouter pricing the same as the provider’s official pricing?**
OpenRouter usually adds a small premium (0.5–1x) for the convenience. Some models may even be cheaper with provider subsidies.

---

## Further reading

- Provider overview: [providers/index.md](./index.md)
- Anthropic direct connect: [providers/anthropic.md](./anthropic.md)
- OpenAI direct connect: [providers/openai.md](./openai.md)
