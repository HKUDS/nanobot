# nanobot Documentation

Get nanobot running and answering your first message first. Once that works, you can ask nanobot to help you set up the next feature or follow a guide below.

> [!NOTE]
> These docs follow the latest development version. For the latest published release, visit [nanobot.wiki](https://nanobot.wiki/docs/latest/getting-started/nanobot-overview).

When a setting is available in the WebUI, follow the graphical steps first. Expand **Manual configuration** when you manage `config.json` directly or run nanobot on a headless server.

## Start Here

| Your situation | Read this | Done when... |
|---|---|---|
| Terminals, Python, or API keys are new to you | [Start Without Technical Background](./start-without-technical-background.md) | You send `Hello!` in your browser and get a reply |
| You are comfortable running terminal commands | [Install and Quick Start](./quick-start.md) | `nanobot status` passes and you get a reply in the WebUI or terminal |
| nanobot will not start | [Installation Problems](./troubleshooting.md#installation-problems) | nanobot starts, or you know what to fix next |
| nanobot opens, but does not reply | [Provider & Model](./troubleshooting.md#provider-and-model-problems), [WebUI](./troubleshooting.md#webui-problems), or [Chat Apps](./troubleshooting.md#chat-app-problems) | You get a reply or a clear next step |

The fastest first-run path:

1. Install nanobot.
2. Let the installer open the WebUI in your browser.
3. Add a provider and model in **Settings → Models**.
4. Send `Hello!` before configuring anything else.

You do not need to edit JSON to get started. Use **Settings** for models and built-in capabilities, **Channels** for chat apps, and **Apps** for plugins, CLI apps, and MCP tools. On servers without a browser, use `nanobot onboard --wizard` instead.

## After the First Reply

Once nanobot replies, you can ask it directly in chat to help configure your next feature—when the built-in `nanobot-document` skill is enabled, it reads the bundled docs for your version. See [Continue with nanobot](./quick-start.md#continue-with-nanobot) for examples, or pick a guide below.

## Add One Capability

| Goal | Guide |
|---|---|
| Learn the browser workbench | [WebUI](./webui.md) |
| Connect Telegram, Discord, Slack, Feishu, WeChat, Email, or another chat app | [Chat Apps](./chat-apps.md) |
| Set up a hosted, OAuth, company, or local model | [Provider Cookbook](./provider-cookbook.md) |
| Add model fallbacks | [Configure Model Fallback](./guides/configure-model-fallback.md) |
| Enable web search | [Configure Web Search](./guides/configure-web-search.md) |
| Manage Agent Plugins, CLI Apps, or MCP integrations | [WebUI Apps](./webui.md#apps) |
| Add an MCP tool server | [Configure MCP Tools](./guides/configure-mcp-tools.md) |
| Generate images | [Image Generation](./image-generation.md) |
| Schedule recurring tasks or local triggers | [Automations](./automations.md) |
| Understand and manage long-term memory | [Memory](./memory.md) |
| Run nanobot continuously | [Deployment](./deployment.md) |
| Run separate bots or workspaces | [Multiple Instances](./multiple-instances.md) |
| Call nanobot from Python | [Python SDK](./python-sdk.md) |

For shorter, outcome-focused walkthroughs, browse the [task guide index](./guides/README.md).

## Operate nanobot

| Need | Read |
|---|---|
| Commands and flags | [CLI Reference](./cli-reference.md) |
| Update nanobot or recover a failed update | [Updating nanobot](./updating.md) |
| In-chat slash commands | [In-Chat Commands](./chat-commands.md) |
| Plain-language overview of how nanobot works | [Concepts](./concepts.md) |
| Provider and model matching | [Providers and Models](./providers.md) |
| Diagnose setup or runtime problems | [Troubleshooting](./troubleshooting.md) |
| Older development highlights | [Release Archive](./release-archive.md) |

## Reference

Use these pages when you need exact config keys, defaults, or API details:

| Area | Reference |
|---|---|
| Configuration fields and defaults | [Configuration](./configuration.md) |
| Provider and model behavior | [Providers and Models](./providers.md) |
| Chat channel prerequisites and manual JSON | [Chat Apps](./chat-apps.md) |
| WebSocket authentication and wire protocol | [WebSocket](./websocket.md) |
| Python SDK classes, events, sessions, and hooks | [Python SDK](./python-sdk.md) |
| Runtime self-inspection and tuning | [My Tool](./my-tool.md) |

> [!TIP]
> JSON examples in these docs are usually snippets to merge into `~/.nanobot/config.json`, not complete files. Never share real API keys, bot tokens, or passwords in issues or logs.

## Extend or Contribute

You do not need these pages to install or use nanobot.

| Goal | Read |
|---|---|
| Understand source ownership and runtime flow | [Architecture](./architecture.md) |
| Set up a development environment | [Development](./development.md) and [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Add a channel package | [Channel Package Guide](./channel-package-guide.md) |
| Build the WebUI source | [WebUI Development](../webui/README.md) |
| Change update APIs or execution | [Update protocol](./update-protocol.md) |
| Prepare and publish a release | [Release checklist](./releasing.md) |

If a command or screen no longer matches these docs, please [open an issue](https://github.com/HKUDS/nanobot/issues) with your nanobot version, operating system, and the page that needs updating.
