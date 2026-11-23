# How to Use an AI Agent WebUI with nanobot

nanobot includes a browser WebUI for persistent chat sessions, visible agent activity, workspace controls, Apps, MCP presets, Skills, settings, and Automations.

## What you will build

- a local browser workbench
- one persistent chat session
- a visible timeline of agent messages, tool calls, and file edit diffs
- a gateway-backed WebSocket connection

## When to use this

Use the WebUI when you want a local AI agent interface that is easier to operate than a terminal, especially for project work, file attachments, model switching, workspace selection, Apps, Skills, and scheduled automations.

## Before you start

Complete [Quick Start](../quick-start.md) if nanobot is not installed or cannot reply yet. If you already have a working WebUI or CLI session, continue here using that instance; no reinstall or second gateway is needed.

The published wheel already includes the WebUI bundle. You only need the `webui/` source directory when changing the frontend.

## Minimal working example

```bash
nanobot webui
```

The launcher checks setup, enables the local WebSocket channel after confirmation, starts the gateway, and opens the browser.

When nanobot edits a file, the WebUI activity timeline can show the changed line counts, a unified diff, and an **Open file** action for a read-only preview. File previews use the chat's current workspace access mode: restricted access stays inside the selected workspace, while Full Access can preview files outside the workspace when the gateway allows it.

## Browser notifications

When the WebUI is in the background, browser notifications tell you when a task finishes, fails, or needs attention. Click a notification to return to its chat.

1. Open **Settings → Notifications**.
2. Turn on **Browser notifications** and allow the browser's permission request.
3. Select **Test notification** to try it. If nothing appears, check the browser's site permissions, system notification settings, and Do Not Disturb.
4. Enable **Completion sound** separately if you want a page chime.

Keep the page open and connected, and use HTTPS or localhost. On iPhone or iPad, open the web app from the Home Screen. If your browser cannot enable notifications, follow the guidance shown in Settings.

## Production notes

- Use `nanobot gateway --background` when you do not want to keep a terminal open, then open the configured WebUI URL in a browser.
- Use `nanobot gateway status`, `logs`, `restart`, and `stop` to manage a background gateway.
- If you expose the WebUI beyond localhost, set a token issue secret and review workspace/tool access.

## Security notes

- The first-run WebUI path binds to `127.0.0.1` by default.
- Do not expose the WebUI on a LAN or public host without an intentional access model.
- Keep file and shell tools scoped to the workspace before inviting other users.

## Troubleshooting

- The WebUI is served by the WebSocket channel on port `8765` by default.
- The gateway health endpoint is separate from the browser UI.
- If the page opens but messages fail, check provider setup with `nanobot agent -m "Hello!"`.

## Related nanobot docs

- [Nanobot WebUI](../webui.md)
- [Quick Start](../quick-start.md)
- [WebSocket protocol](../websocket.md)
- [Configuration](../configuration.md)
