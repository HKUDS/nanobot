# How to Build a Personal AI Agent with nanobot

This guide builds a personal AI agent you can run locally, talk to from the
terminal or browser, and later connect to chat apps, memory, tools, and
automations.

## What you will build

- a configured nanobot install
- one working model provider
- one local agent reply
- a browser WebUI session for ongoing work

## When to use this

Use this when you want a personal AI agent that you control rather than a hosted
chat-only interface. nanobot is useful when the agent needs local workspace
access, tool calls, session history, memory, scheduled work, or chat app
delivery.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

The wizard creates `~/.nanobot/config.json` and helps you choose a provider and
model. If terminals and config files are new to you, use
[Start Without Technical Background](../start-without-technical-background.md)
instead.

## Minimal working example

First prove the runtime can answer:

```bash
nanobot agent -m "Hello!"
```

Then open the browser workbench:

```bash
nanobot webui
```

The WebUI starts the local gateway, opens a browser, and keeps persistent chat
sessions for longer work.

## Production notes

- Keep one workspace per project or personal context.
- Use `modelPresets` when you want stable names for fast, deep, local, or
  fallback models.
- Keep `nanobot gateway` running for WebUI, chat apps, automations, and the
  WebSocket channel.
- Use the Python SDK or OpenAI-compatible API when another program should call
  the agent.

## Security notes

- Do not store API keys directly in shared files; use environment variables.
- Keep chat app `allowFrom` lists narrow.
- Enable workspace restriction before exposing file or shell tools to other
  users.
- Use a separate workspace for experiments that can modify files.

## Troubleshooting

- `nanobot status` shows the config path, workspace path, and active model.
- If `nanobot agent -m "Hello!"` fails, fix provider setup before opening the
  WebUI or chat apps.
- If the WebUI opens but does not answer, check gateway logs and provider
  credentials.

## Related nanobot docs

- [Quick Start](../quick-start.md)
- [Concepts](../concepts.md)
- [WebUI](../webui.md)
- [Configuration](../configuration.md)
- [Troubleshooting](../troubleshooting.md)
