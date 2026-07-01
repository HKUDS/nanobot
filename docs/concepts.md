# Concepts

Use this page when you want to understand nanobot before changing advanced settings. It explains the moving parts without requiring you to read the source first.

If you want source-file ownership and extension points, read [`architecture.md`](./architecture.md) after this page.

## Runtime Shape

nanobot has one small core loop and several ways to enter it:

| Part | What it does |
|---|---|
| Agent loop | Builds context, selects the session, calls the provider, runs tools, and publishes replies |
| Providers | LLM backends such as OpenRouter, Anthropic, OpenAI, Bedrock, Ollama, vLLM, and other OpenAI-compatible APIs |
| Channels | User-facing transports such as CLI, WebUI/WebSocket, Telegram, Discord, Slack, Feishu, WeChat, Email, and others |
| Tools | Capabilities the model may call, including files, shell, web search/fetch, MCP, cron, image generation, and subagents |
| Memory | Workspace files and session history that keep useful context across turns |
| Gateway | Long-running process that connects enabled channels and serves the health endpoint |

The simplest path is `nanobot agent -m "Hello!"`: one inbound message goes through the agent loop and prints the reply in your terminal. The long-running path is `nanobot gateway`: channels receive messages from chat apps or the WebUI, publish them to the same agent loop, and send replies back to the originating channel.

## Config vs Workspace

The default instance lives under `~/.nanobot/`:

| Path | Meaning |
|---|---|
| `~/.nanobot/config.json` | Instance configuration: providers, model defaults, channels, tools, gateway, API, and runtime options |
| `~/.nanobot/workspace/` | Agent workspace: memory, sessions, heartbeat tasks, cron jobs, skills, and generated artifacts |

You can override both with command flags:

```bash
nanobot onboard --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot agent --config ./bot-a/config.json --workspace ./bot-a/workspace -m "Hello"
nanobot gateway --config ./bot-a/config.json --workspace ./bot-a/workspace
```

The config file controls what nanobot may use. The workspace is where nanobot keeps state for that instance.

## Config Format

`config.json` accepts both camelCase and snake_case keys. The docs use camelCase because nanobot writes config back to disk with camelCase aliases, for example `apiKey`, `modelPresets`, `intervalS`, and `maxToolResultChars`.

Most examples are partial snippets. Merge them into the existing file created by `nanobot onboard`; do not replace the whole file unless you want to reset the instance.

## One Agent Turn

A normal turn follows this flow:

1. A channel receives a user message and publishes it to the message bus.
2. The agent loop chooses a session key and builds context from the workspace, skills, memory, recent messages, channel metadata, and runtime settings.
3. The provider receives the model request.
4. If the model asks for tools, the runner executes them and feeds results back to the model.
5. The final reply is saved to the session and sent back through the channel.

That flow is the same whether the message starts in the CLI, WebUI, Telegram, Discord, or another channel.

## CLI, Gateway, API, and WebUI

| Entry point | Command | Use it for |
|---|---|---|
| CLI one-shot | `nanobot agent -m "..."` | First-run checks, scripts, and quick local questions |
| CLI interactive | `nanobot agent` | Terminal chat with persistent session history |
| Gateway | `nanobot gateway` | Chat apps, WebUI, heartbeat, Dream, and long-running service mode |
| OpenAI-compatible API | `nanobot serve` | Programmatic access through `/v1/chat/completions` |
| WebUI | `nanobot gateway` plus WebSocket channel | Browser workbench served by the WebSocket channel on port `8765` |

The gateway health endpoint is on `gateway.port` (`18790` by default). The browser WebUI is served by the WebSocket channel (`8765` by default), not by the health endpoint.

## Provider and Model Selection

The active model should normally come from a named `modelPresets` entry selected by `agents.defaults.modelPreset`. Direct `agents.defaults.provider` and `agents.defaults.model` still form the implicit `default` preset for older or minimal configs. The active provider is resolved in this order:

1. If the active preset provider or implicit default provider is not `"auto"`, nanobot uses that provider.
2. If provider is `"auto"`, nanobot tries to infer the provider from the model name, configured API keys, local provider base URLs, or gateway providers.
3. OAuth providers such as OpenAI Codex, Anthropic OAuth, and GitHub Copilot require explicit login and explicit provider/model selection inside the active preset.

Pin the provider inside the preset when setting up for the first time. It is easier to debug:

```json
{
  "modelPresets": {
    "primary": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4.5"
    }
  },
  "agents": {
    "defaults": {
      "modelPreset": "primary"
    }
  }
}
```

See [`providers.md`](./providers.md) for practical examples and [`configuration.md#providers`](./configuration.md#providers) for the full provider reference.

## Channels and Sessions

Each channel maps inbound messages to a session key. That lets independent conversations keep separate history. The WebUI also supports multiple chats and workspace-scoped metadata for project workspaces.

`agents.defaults.unifiedSession` can intentionally share one session across channels for a single-user multi-device setup. Leave it off if you expect separate people, groups, channels, or projects to keep separate context.

## Memory, Sessions, and Dream

nanobot uses two related stores:

| Store | Location | Purpose |
|---|---|---|
| Sessions | `<workspace>/sessions/*.jsonl` | Recent conversation turns replayed into context |
| Memory | `<workspace>/memory/MEMORY.md` and `<workspace>/memory/history.jsonl` | Long-term facts and consolidated history |

Dream is a periodic consolidation job. It reads accumulated history and updates workspace memory so useful context can survive beyond short session replay.

See [`memory.md`](./memory.md) for the detailed design.

## Tools and Safety

Tools are discovered automatically from built-in modules and plugin entry points. Common tool groups include:

- file read/write/edit and patching;
- shell execution with configurable sandboxing;
- web search and web fetch with SSRF checks;
- MCP servers;
- cron reminders and heartbeat tasks;
- image generation;
- subagents and runtime self-inspection.

Security-sensitive controls live in [`configuration.md#security`](./configuration.md#security). For production or shared chat apps, also configure channel access controls such as `allowFrom`, pairing, or WebSocket tokens.

## Background Jobs

When `nanobot gateway` starts, it creates workspace-scoped cron storage at `<workspace>/cron/jobs.json` and registers system jobs:

- `dream`, when `agents.defaults.dream.enabled` is true;
- `heartbeat`, when `gateway.heartbeat.enabled` is true.

Heartbeat reads `<workspace>/HEARTBEAT.md`. If the file has tasks under `## Active Tasks`, nanobot executes them and sends only useful/actionable results to the most recently active chat target. Routine "nothing changed" results are suppressed.

User-created reminders use the same cron service but are not the same as the protected heartbeat system job. They run as scheduled turns in their origin chat/session and normally deliver the result back to that channel.

## Where to Go Next

| Need | Read |
|---|---|
| First working install | [`quick-start.md`](./quick-start.md) |
| Provider/model setup | [`providers.md`](./providers.md) |
| Chat app setup | [`chat-apps.md`](./chat-apps.md) |
| Complete config reference | [`configuration.md`](./configuration.md) |
| Runtime debugging | [`troubleshooting.md`](./troubleshooting.md) |
