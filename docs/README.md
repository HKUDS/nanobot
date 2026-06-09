# nanobot Docs

For published release documentation, visit [nanobot.wiki](https://nanobot.wiki/docs/latest/getting-started/nanobot-overview). The pages in this directory track the current repository and may describe features that have not reached the published site yet.

If you have never used a terminal or edited a config file before, start with [`start-without-technical-background.md`](./start-without-technical-background.md). Otherwise, start with [`quick-start.md`](./quick-start.md) and get one local `nanobot agent -m "Hello!"` reply working before connecting chat apps, WebUI, Docker, or custom tools.

Most JSON examples in these docs are snippets to merge into `~/.nanobot/config.json`, not full replacement files.

## Start Here

| Goal | Read | Outcome |
|---|---|---|
| Start with no technical background | [`start-without-technical-background.md`](./start-without-technical-background.md) | A guided path through terminal commands, config, API keys, and the first reply |
| Install and get the first reply | [`quick-start.md`](./quick-start.md) | A working CLI agent and a known-good config path |
| Understand how the pieces fit | [`concepts.md`](./concepts.md) | Mental model for config, workspace, gateway, channels, tools, memory, and sessions |
| Choose or change a model provider | [`providers.md`](./providers.md) | Correct provider/model pairing without reading the full config reference |
| Fix a first-run or runtime problem | [`troubleshooting.md`](./troubleshooting.md) | A diagnosis order and targeted checks for common failures |

## Use nanobot

| Goal | Read | Outcome |
|---|---|---|
| Open the bundled browser UI | [`../webui/README.md`](../webui/README.md) | WebUI on port `8765`, or Vite HMR when developing the frontend |
| Connect Telegram, Discord, WeChat, Slack, and other apps | [`chat-apps.md`](./chat-apps.md) | A gateway-backed chat channel with access control |
| Use slash commands and periodic tasks | [`chat-commands.md`](./chat-commands.md) | Pairing, model presets, heartbeat tasks, and chat-side controls |
| Generate images | [`image-generation.md`](./image-generation.md) | Image provider config, WebUI image mode, and artifact behavior |
| Run several isolated bots | [`multiple-instances.md`](./multiple-instances.md) | Separate configs, workspaces, ports, and sessions |
| Deploy outside a terminal | [`deployment.md`](./deployment.md) | Docker, systemd user services, and macOS LaunchAgent setup |
| Join agent communities | [`agent-social-network.md`](./agent-social-network.md) | External agent-community setup |

## Reference

| Area | Read | Best for |
|---|---|---|
| Full configuration schema | [`configuration.md`](./configuration.md) | Exact fields, defaults, provider tables, web tools, MCP, security, and runtime options |
| CLI commands | [`cli-reference.md`](./cli-reference.md) | Command names, common flags, and entrypoints |
| Architecture | [`architecture.md`](./architecture.md) | Source-level runtime map for core flow, providers, channels, tools, WebUI, memory, security, and extension points |
| Development | [`development.md`](./development.md) | Contributor notes for adding providers and transcription adapters |
| Memory | [`memory.md`](./memory.md) | Session history, Dream consolidation, memory files, and versioning |
| Observability | [`configuration.md#langfuse-observability`](./configuration.md#langfuse-observability) | Langfuse tracing setup and required environment variables |
| WebSocket protocol | [`websocket.md`](./websocket.md) | Custom clients, token issuance, multiplexed chats, media, and protocol events |
| OpenAI-compatible API | [`openai-api.md`](./openai-api.md) | `/v1/chat/completions`, `/v1/models`, file uploads, and SDK-compatible usage |
| Python SDK | [`python-sdk.md`](./python-sdk.md) | Running nanobot from Python and attaching hooks |
| Runtime self-inspection | [`my-tool.md`](./my-tool.md) | Inspecting and tuning the current agent run |

## Extend nanobot

| Goal | Read | Outcome |
|---|---|---|
| Add a provider or transcription adapter | [`development.md`](./development.md) | A registry/schema-aligned implementation path |
| Add a chat channel plugin | [`channel-plugin-guide.md`](./channel-plugin-guide.md) | A packaged channel discovered through entry points |
| Add custom MCP servers | [`configuration.md#mcp-model-context-protocol`](./configuration.md#mcp-model-context-protocol) | External tools exposed to the agent through MCP |
| Tune tool safety | [`configuration.md#security`](./configuration.md#security) | Shell sandboxing, workspace restriction, and SSRF policy |

## Reading Strategy

Use the docs in this order when you are unsure where to go:

1. If terminal commands or config files are new to you, [`start-without-technical-background.md`](./start-without-technical-background.md) explains the setup words and uses one guided OpenRouter path.
2. [`quick-start.md`](./quick-start.md) proves installation, config loading, and provider access.
3. [`concepts.md`](./concepts.md) explains the runtime model so later pages are easier to scan.
4. A task guide, such as [`chat-apps.md`](./chat-apps.md), [`image-generation.md`](./image-generation.md), or [`deployment.md`](./deployment.md), gets one workflow working.
5. [`configuration.md`](./configuration.md) is the source of truth when you need a specific field, default value, or advanced option.
6. [`troubleshooting.md`](./troubleshooting.md) helps isolate whether a failure is install, config, provider, gateway, channel, or tool related.
