# Configuration Overview

Nanobot keeps all of its behavior in a single JSON file, covering models, channels, tools, and gateway settings.

---

## Config file location

The default config is stored at:

```
~/.nanobot/config.json
```

Running `nanobot onboard` prompts you for the necessary values and writes this file.

### Custom config paths

Use the `-c` / `--config` flag to point nanobot at any config path:

```bash
# Use a specific config for the gateway
nanobot gateway --config ~/.nanobot-work/config.json

# Run the CLI agent against another config
nanobot agent -c ~/.nanobot-personal/config.json -m "Hello!"
```

> [!TIP]
> When deploying multiple instances, each instance uses its own config path. See the [multi-instance guide](./multi-instance.md).

---

## Config format

The config file is standard JSON and accepts a mix of **camelCase** and **snake_case** keys:

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "max_tool_iterations": 40
    }
  }
}
```

> [!NOTE]
> Standard JSON does not support comments (`//`). The examples in this guide sometimes include them for clarity, but do not copy them into your config.

---

## Pydantic validation

Nanobot uses [Pydantic](https://docs.pydantic.dev/) to parse and validate configs. Startup fails fast with a clear error if any value is invalid—no silent overrides.

---

## Environment variable overrides

Every setting can be overridden through environment variables with the `NANOBOT_` prefix. Nested keys are separated by double underscores (`__`):

| Environment variable | Config key |
|----------------------|------------|
| `NANOBOT_AGENTS__DEFAULTS__MODEL` | `agents.defaults.model` |
| `NANOBOT_PROVIDERS__ANTHROPIC__API_KEY` | `providers.anthropic.api_key` |
| `NANOBOT_GATEWAY__PORT` | `gateway.port` |
| `NANOBOT_TOOLS__EXEC__TIMEOUT` | `tools.exec.timeout` |

Environment variables override config file values, which is useful for injecting secrets in Docker or CI/CD pipelines.

```bash
export NANOBOT_PROVIDERS__ANTHROPIC__API_KEY="sk-ant-..."
nanobot gateway
```

---

## Top-level keys quick reference

| Key | Type | Purpose |
|-----|------|---------|
| [`agents`](./reference.md#agents) | object | Agent defaults (model, workspace, token limits, etc.) |
| [`channels`](./reference.md#channels) | object | Chat platforms (Slack, Discord, Telegram, etc.) |
| [`providers`](./reference.md#providers) | object | LLM provider API keys and endpoints |
| [`gateway`](./reference.md#gateway) | object | HTTP gateway server (host, port, heartbeat) |
| [`tools`](./reference.md#tools) | object | Tool settings (web search, shell exec, MCP servers, etc.) |

---

## Minimum viable config example

The smallest config that enables Telegram and Anthropic:

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

Every option not listed uses its default value.

---

## Further reading

- [Full config reference](./reference.md) — detailed descriptions and defaults
- [Multi-instance guide](./multi-instance.md) — run multiple nanobot instances simultaneously
- [CLI reference](../cli-reference.md) — every command and flag
