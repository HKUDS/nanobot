# Anthropic (Claude models)

Anthropic develops the Claude family of models and offers direct API access. Compared to routing through OpenRouter, a direct Anthropic connection delivers lower latency, more consistent prompt caching, and advanced features such as Thinking (reasoning effort control).

---

## Get an API key

1. Visit the Anthropic Console (console.anthropic.com)
2. Sign up using Google or Email
3. Open the **API Keys** page
4. Click **Create Key**, give it a name, and generate the key
5. Copy the key (format: `sk-ant-api03-xxxxxxxx...`)

> Anthropic uses a credit-based billing system. New accounts usually receive a free trial credit; production use requires topping up or subscribing.

---

## Available models

Anthropic offers three tiers of Claude models to match differing cost and capability requirements.

### Claude Opus — reasoning flagship

| Model ID | Description |
|--------|------|
| `claude-opus-4-5` | Latest Opus model with the highest reasoning ability and Thinking support |

Use cases: complex analysis, architecture design, long-form writing

### Claude Sonnet — balanced choice

| Model ID | Description |
|--------|------|
| `claude-sonnet-4-5` | Latest Sonnet with excellent performance at a reasonable cost |
| `claude-sonnet-3-7` | Supports enhanced Extended Thinking |
| `claude-sonnet-3-5` | Stable and widely adopted |

Use cases: general tasks, code generation, Q&A

### Claude Haiku — speed first

| Model ID | Description |
|--------|------|
| `claude-haiku-3-5` | Latest Haiku model, fastest and most cost-effective |

Use cases: instant replies, batch processing, lightweight workloads

---

## Configuration examples

### Minimal setup

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5"
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
  }
}
```

### Enable prompt caching

nanobot enables `cache_control` when connected directly to Anthropic. Prompt caching automatically applies to system prompts and tool definitions without extra settings. If you want to be explicit, set it in `agents.defaults`:

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5",
      "prompt_caching": true
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

Prompt caching can reduce repeated input costs by 50–90% for long system prompts (over 1024 tokens).

> **Note:** Prompt caching works only for Anthropic direct connections or OpenRouter routing. Other gateways may not support the `cache_control` header.

### Configure Thinking (reasoning effort)

Claude Opus and some Sonnet versions support Extended Thinking, which can improve complex reasoning results:

```json
{
  "agents": {
    "defaults": {
      "model": "claude-opus-4-5",
      "thinking": {
        "type": "enabled",
        "budget_tokens": 10000
      }
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

| Parameter | Description |
|------|------|
| `type` | Set to `"enabled"` to enable Thinking; `"disabled"` turns it off |
| `budget_tokens` | Maximum tokens allowed for the thinking phase (recommended 1000–32000) |

> **Note:** Anthropic requires `temperature` to be 1 when Thinking is enabled. Nanobot enforces this automatically.

### Full example

```json
{
  "agents": {
    "defaults": {
      "model": "claude-sonnet-4-5",
      "max_tokens": 8192,
      "temperature": 0.7
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "sk-ant-api03-..."
    }
  }
}
```

---

## Model detection

Nanobot automatically routes to Anthropic when the chosen model includes Anthropic-related keywords (no explicit `provider` required):

- Model names that contain `anthropic` or `claude`

For example, `model: "claude-haiku-3-5"` will automatically use the Anthropic provider configuration.

---

## Prompt caching savings

Anthropic's prompt caching discounts identical repeated content (system prompts, tool definitions, long files), often reducing input token charges by around 90% when a cache hit occurs.

Nanobot automatically caches recurrent content such as:
- Fixed system prompts used for every conversation
- MCP tool definition lists (usually lengthy)
- Long memory summaries (memory consolidation output)

For high-frequency bots or long conversations, prompt caching significantly cuts total cost.

---

## FAQ

**Q: Can I configure both Anthropic and OpenRouter?**
Yes. Nanobot selects providers based on model keywords. If both are configured and `provider` is not explicitly set, models containing `anthropic` or `claude` route to Anthropic.

**Q: Is Anthropic available in mainland China?**
The Anthropic endpoint (`api.anthropic.com`) requires a VPN in mainland China. Use OpenRouter or SiliconFlow as alternatives if access is restricted.

**Q: How can I check my usage?**
Visit the **Usage** page in the Anthropic Console to review token usage, billing breakdowns, and per-model statistics.

---

## Further reading

- Provider overview: [providers/index.md](./index.md)
- OpenRouter (alternative gateway): [providers/openrouter.md](./openrouter.md)
- Official documentation: Anthropic API Reference and Models pages
