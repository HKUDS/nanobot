# nanobot Docs

For published release documentation, visit [nanobot.wiki](https://nanobot.wiki/docs/latest/getting-started/nanobot-overview). The pages in this directory track the current repository and may describe features that have not reached the published site yet.

If you have never used a terminal or edited a config file before, start with [`start-without-technical-background.md`](./start-without-technical-background.md). Otherwise, start with [`quick-start.md`](./quick-start.md), open the browser workbench with `nanobot webui`, and use terminal checks when you need lower-level diagnosis.

Most JSON examples in these docs are snippets to merge into `~/.nanobot/config.json`, not full replacement files.

Provider examples are concrete walkthroughs, not rankings or endorsements. Use the provider whose key, endpoint, and model ID you actually control.

If you find a docs mistake, outdated command, or confusing step, please open an issue: <https://github.com/HKUDS/nanobot/issues>.

## Pick a Track

| You are | Start with | Then use |
|---|---|---|
| New to terminals and config files | [`start-without-technical-background.md`](./start-without-technical-background.md) | [`troubleshooting.md`](./troubleshooting.md) if the first reply fails |
| Comfortable pasting commands and JSON | [`quick-start.md`](./quick-start.md) | [`provider-cookbook.md`](./provider-cookbook.md) for pasteable provider setups |
| Operating a long-running bot | [`concepts.md`](./concepts.md) | [`chat-apps.md`](./chat-apps.md), [`webui.md`](./webui.md), and [`deployment.md`](./deployment.md) |
| Integrating or extending nanobot | [`architecture.md`](./architecture.md) | [`configuration.md`](./configuration.md), [`openai-api.md`](./openai-api.md), [`python-sdk.md`](./python-sdk.md), [`development.md`](./development.md), and [`channel-plugin-guide.md`](./channel-plugin-guide.md) |

## Start Here

| Goal | Read | Outcome |
|---|---|---|
| Start with no technical background | [`start-without-technical-background.md`](./start-without-technical-background.md) | One-command setup, terminal basics, config, API keys, and the first reply |
| Install and get the first reply | [`quick-start.md`](./quick-start.md) | A working CLI agent and a known-good config path |
| Understand how the pieces fit | [`concepts.md`](./concepts.md) | Mental model for config, workspace, gateway, channels, tools, memory, and sessions |
| Choose or change a model provider | [`providers.md`](./providers.md) | Correct provider/model pairing without reading the full config reference |
| Copy a provider setup recipe | [`provider-cookbook.md`](./provider-cookbook.md) | Pasteable OpenRouter, OpenAI, Anthropic, local model, fallback, and Langfuse setups |
| Fix a first-run or runtime problem | [`troubleshooting.md`](./troubleshooting.md) | A diagnosis order and targeted checks for common failures |

## Task Guides

Use these pages when you know the workflow you want and do not want to scan the
full reference first.

| Goal | Guide |
|---|---|
| Build a personal AI agent | [`guides/build-a-personal-ai-agent.md`](./guides/build-a-personal-ai-agent.md) |
| Run a self-hosted AI agent | [`guides/self-hosted-ai-agent.md`](./guides/self-hosted-ai-agent.md) |
| Use a browser AI agent WebUI | [`guides/ai-agent-webui.md`](./guides/ai-agent-webui.md) |
| Connect an AI agent to chat apps | [`guides/chat-app-ai-agent.md`](./guides/chat-app-ai-agent.md) |
| Run long-running agent tasks | [`guides/long-running-ai-agent.md`](./guides/long-running-ai-agent.md) |
| Schedule or trigger agent turns | [`automations.md`](./automations.md) |
| Add long-term agent memory | [`guides/ai-agent-memory.md`](./guides/ai-agent-memory.md) |
| Add MCP tools to an agent | [`guides/mcp-tools-for-ai-agents.md`](./guides/mcp-tools-for-ai-agents.md) |
| Run an agent from Python | [`guides/python-ai-agent-sdk.md`](./guides/python-ai-agent-sdk.md) |
| Expose an OpenAI-compatible agent API | [`guides/openai-compatible-agent-api.md`](./guides/openai-compatible-agent-api.md) |
| Deploy a long-running agent gateway | [`guides/deploy-nanobot-gateway.md`](./guides/deploy-nanobot-gateway.md) |

Platform-specific chat guides:
[`Telegram`](./guides/telegram-ai-agent.md),
[`Discord`](./guides/discord-ai-agent.md),
[`Slack`](./guides/slack-ai-agent.md),
[`Feishu`](./guides/feishu-ai-agent.md),
[`WhatsApp`](./guides/whatsapp-ai-agent.md),
[`WeChat`](./guides/wechat-ai-agent.md),
[`QQ`](./guides/qq-ai-agent.md),
[`Email`](./guides/email-ai-agent.md), and
[`Mattermost`](./guides/mattermost-ai-agent.md).

Configuration guides:
[`MCP tools`](./guides/configure-mcp-tools.md),
[`web search`](./guides/configure-web-search.md),
[`model fallback`](./guides/configure-model-fallback.md),
[`OpenAI-compatible providers`](./guides/configure-openai-compatible-provider.md),
[`Langfuse`](./guides/configure-langfuse-observability.md),
[`local security`](./guides/secure-local-ai-agent.md), and
[`gateway deployment`](./guides/deploy-nanobot-gateway.md).

## After the First Reply Works

Do not configure everything at once. Pick one next surface:

If a local `nanobot agent` session can already answer normally, you can also ask nanobot to help configure itself: have it read the relevant docs, inspect your current config, make one specific next change, and tell you when to run `/restart`.

| Next goal | Read | First check |
|---|---|---|
| Use nanobot in a browser | [`webui.md`](./webui.md) | Run `nanobot webui` and open the local browser workbench |
| Talk through a chat app | [`chat-apps.md`](./chat-apps.md) | Merge one channel snippet, run `nanobot channels status`, keep `nanobot gateway` running |
| Change provider or add fallbacks | [`provider-cookbook.md`](./provider-cookbook.md) | Keep `modelPresets` named and set `agents.defaults.modelPreset` |
| Call nanobot from Python | [`python-sdk.md`](./python-sdk.md) | Reuse the same config/workspace from code, then run or stream one agent turn |
| Understand before operating long-term | [`concepts.md`](./concepts.md) | Know what config, workspace, gateway, sessions, memory, and tools mean |
| Diagnose a new failure | [`troubleshooting.md`](./troubleshooting.md) | Start with `nanobot status`, then `nanobot agent -m "Hello!"` |

## Use nanobot

| Goal | Read | Outcome |
|---|---|---|
| Open the bundled browser UI | [`webui.md`](./webui.md) | `nanobot webui`, chat workspace, Apps, Skills, Automations, and settings |
| Connect Telegram, Discord, WeChat, Slack, Email, Mattermost, or another chat app | [`chat-apps.md`](./chat-apps.md) | A gateway-backed chat channel with access control |
| Use automations | [`automations.md`](./automations.md) | Scheduled automations, local triggers, heartbeat, WebUI management, and delivery behavior |
| Use slash commands | [`chat-commands.md`](./chat-commands.md) | Pairing, model presets, local triggers, heartbeat tasks, and chat-side controls |
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
| Release archive | [`release-archive.md`](./release-archive.md) | Older release and daily update highlights moved out of the README |
| Development | [`development.md`](./development.md) | Contributor notes for adding providers and transcription adapters |
| Memory | [`memory.md`](./memory.md) | Session history, Dream consolidation, memory files, and versioning |
| Observability | [`configuration.md#langfuse-observability`](./configuration.md#langfuse-observability) | Langfuse tracing setup and required environment variables |
| WebSocket protocol | [`websocket.md`](./websocket.md) | Custom clients, token issuance, multiplexed chats, media, and protocol events |
| OpenAI-compatible API | [`openai-api.md`](./openai-api.md) | `/v1/chat/completions`, `/v1/models`, file uploads, and SDK-compatible usage |
| Python SDK | [`python-sdk.md`](./python-sdk.md) | SDK 101, sessions, streaming, model overrides, runtime helpers, and hooks |
| Runtime self-inspection | [`my-tool.md`](./my-tool.md) | Inspecting and tuning the current agent run |

## Fast Lookup

| Need | Jump to |
|---|---|
| Provider/model resolution order | [`providers.md#provider-resolution`](./providers.md#provider-resolution) |
| Model presets and fallback chains | [`providers.md#model-presets`](./providers.md#model-presets) and [`providers.md#fallback-models`](./providers.md#fallback-models) |
| Langfuse environment variables | [`configuration.md#langfuse-observability`](./configuration.md#langfuse-observability) |
| WebSocket/WebUI protocol details | [`websocket.md`](./websocket.md) |
| OpenAI-compatible API usage | [`openai-api.md`](./openai-api.md) |
| Python SDK usage | [`python-sdk.md`](./python-sdk.md) |
| Scheduled automations and local triggers | [`automations.md`](./automations.md) |
| Multiple configs, workspaces, and ports | [`multiple-instances.md`](./multiple-instances.md) |
| Security, sandboxing, and SSRF controls | [`configuration.md#security`](./configuration.md#security) |
| Channel plugin development | [`channel-plugin-guide.md`](./channel-plugin-guide.md) |

## Extend nanobot

| Goal | Read | Outcome |
|---|---|---|
| Add a provider or transcription adapter | [`development.md`](./development.md) | A registry/schema-aligned implementation path |
| Add a chat channel plugin | [`channel-plugin-guide.md`](./channel-plugin-guide.md) | A packaged channel discovered through entry points |
| Add custom MCP servers | [`configuration.md#mcp-model-context-protocol`](./configuration.md#mcp-model-context-protocol) | External tools exposed to the agent through MCP |
| Tune tool safety | [`configuration.md#security`](./configuration.md#security) | Shell sandboxing, workspace restriction, and SSRF policy |

## Reading Strategy

Use the docs in this order when you are unsure where to go:

1. If terminal commands or config files are new to you, [`start-without-technical-background.md`](./start-without-technical-background.md) explains the setup words and uses one concrete provider example so there is only one decision at a time.
2. [`quick-start.md`](./quick-start.md) proves installation, config loading, and provider access.
3. [`concepts.md`](./concepts.md) explains the runtime model so later pages are easier to scan.
4. [`provider-cookbook.md`](./provider-cookbook.md) gives pasteable provider, fallback, local model, and Langfuse recipes.
5. A task guide, such as [`chat-apps.md`](./chat-apps.md), [`image-generation.md`](./image-generation.md), or [`deployment.md`](./deployment.md), gets one workflow working.
6. [`configuration.md`](./configuration.md) is the source of truth when you need a specific field, default value, or advanced option.
7. [`troubleshooting.md`](./troubleshooting.md) helps isolate whether a failure is install, config, provider, gateway, channel, or tool related.
