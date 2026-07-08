# How to Use an AI Agent WebUI with nanobot

nanobot includes a browser WebUI for persistent chat sessions, visible agent
activity, workspace controls, Apps, MCP presets, Skills, settings, and
Automations.

## What you will build

- a local browser workbench
- one persistent chat session
- a visible timeline of agent messages, tool calls, and file activity
- a gateway-backed WebSocket connection

## When to use this

Use the WebUI when you want a local AI agent interface that is easier to operate
than a terminal, especially for project work, file attachments, model switching,
workspace selection, Apps, Skills, and scheduled automations.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

The published wheel already includes the WebUI bundle. You only need the
`webui/` source directory when changing the frontend.

## Minimal working example

```bash
nanobot webui
```

The launcher checks setup, enables the local WebSocket channel after
confirmation, starts the gateway, and opens the browser.

## Production notes

- Use `nanobot webui --background` when you do not want to keep a terminal open.
- Use `nanobot gateway status`, `logs`, `restart`, and `stop` to manage a
  background gateway.
- If you expose the WebUI beyond localhost, set a token issue secret and review
  workspace/tool access.

## Security notes

- The first-run WebUI path binds to `127.0.0.1` by default.
- Do not expose the WebUI on a LAN or public host without an intentional access
  model.
- Keep file and shell tools scoped to the workspace before inviting other users.

## Troubleshooting

- The WebUI is served by the WebSocket channel on port `8765` by default.
- The gateway health endpoint is separate from the browser UI.
- If the page opens but messages fail, check provider setup with
  `nanobot agent -m "Hello!"`.

## Related nanobot docs

- [Nanobot WebUI](../webui.md)
- [Quick Start](../quick-start.md)
- [WebSocket protocol](../websocket.md)
- [Configuration](../configuration.md)
