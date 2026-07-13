# nanobot Documentation

Use these docs to get a working agent first, then open a task guide only when
you need the next capability. Source-level design and extension details are
kept in the contributor section.

Repository docs follow the current source tree and can be newer than the latest
package release. For published release docs, visit
[nanobot.wiki](https://nanobot.wiki/docs/latest/getting-started/nanobot-overview).

## Start Here

| Your situation | Read this | You are done when... |
|---|---|---|
| Terminals, Python, or API keys are new to you | [Beginner walkthrough](./start-without-technical-background.md) | The browser can send `Hello!` and receive a reply |
| You are comfortable running commands | [Install and Quick Start](./quick-start.md) | `nanobot status` is healthy and the WebUI or CLI can get one reply |
| Something already failed | [Troubleshooting](./troubleshooting.md) | You have isolated the problem to install, config, model, gateway, channel, or tool access |

The recommended first-run path is:

1. Install nanobot.
2. Choose **Quick Start** in `nanobot onboard --wizard`.
3. Run `nanobot webui`.
4. Send `Hello!` before configuring anything else.

Most people do not need to edit JSON for the first run. The wizard handles the
initial provider, model, and local WebUI settings. After the WebUI opens, use
**Settings** for models and built-in capabilities, **Settings → Channels** for
chat apps, and **Apps** for CLI App or MCP integrations.

## Add One Capability

Pick the row that matches what you want to accomplish next:

| Goal | Guide |
|---|---|
| Learn the browser workbench | [WebUI](./webui.md) |
| Connect Telegram, Discord, Slack, Feishu, WeChat, Email, or another chat app | [Chat Apps](./chat-apps.md) |
| Choose a hosted, OAuth, company, or local model | [Provider Cookbook](./provider-cookbook.md) |
| Add model fallbacks | [Configure Model Fallback](./guides/configure-model-fallback.md) |
| Enable web search | [Configure Web Search](./guides/configure-web-search.md) |
| Add an MCP tool server | [Configure MCP Tools](./guides/configure-mcp-tools.md) |
| Generate images | [Image Generation](./image-generation.md) |
| Schedule work or create a local trigger | [Automations](./automations.md) |
| Understand and manage long-term memory | [Memory](./memory.md) |
| Run nanobot continuously | [Deployment](./deployment.md) |
| Run separate bots or workspaces | [Multiple Instances](./multiple-instances.md) |
| Call nanobot from Python | [Python SDK](./python-sdk.md) |
| Expose an OpenAI-compatible endpoint | [OpenAI-Compatible API](./openai-api.md) |

For shorter, outcome-focused walkthroughs, browse the
[task guide index](./guides/README.md).

## Operate nanobot

| Need | Read |
|---|---|
| Commands and flags | [CLI Reference](./cli-reference.md) |
| In-chat slash commands | [In-Chat Commands](./chat-commands.md) |
| Config, workspace, gateway, sessions, tools, and memory in plain language | [Concepts](./concepts.md) |
| Provider/model matching and selection | [Providers and Models](./providers.md) |
| Setup and runtime diagnosis | [Troubleshooting](./troubleshooting.md) |
| Older development highlights | [Release Archive](./release-archive.md) |

## Reference

Use reference pages to look up an exact option after you know what you are
trying to configure:

| Area | Reference |
|---|---|
| Every configuration field and default | [Configuration](./configuration.md) |
| Provider and model behavior | [Providers and Models](./providers.md) |
| Chat channel prerequisites and manual JSON | [Chat Apps](./chat-apps.md) |
| WebSocket authentication and wire protocol | [WebSocket](./websocket.md) |
| Python SDK classes, events, sessions, and hooks | [Python SDK](./python-sdk.md) |
| OpenAI-compatible HTTP routes and payloads | [OpenAI-Compatible API](./openai-api.md) |
| Runtime self-inspection and tuning | [My Tool](./my-tool.md) |

Configuration examples are usually snippets to merge into
`~/.nanobot/config.json`, not complete replacement files. The docs use
camelCase because nanobot writes config that way. Keep real API keys, bot
tokens, and passwords out of issues and public logs.

## Extend or Contribute

These pages explain implementation and extension points. You do not need them
to install or operate nanobot.

| Goal | Read |
|---|---|
| Understand source ownership and runtime flow | [Architecture](./architecture.md) |
| Set up a development environment | [Development](./development.md) and [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Add a channel package | [Channel Plugin Guide](./channel-plugin-guide.md) |
| Build the WebUI source | [WebUI Development](../webui/README.md) |

If a command or screen no longer matches these docs, please
[open an issue](https://github.com/HKUDS/nanobot/issues) with your nanobot
version, operating system, and the page that needs correction.
