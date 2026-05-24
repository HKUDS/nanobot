# nanobot webui

The browser front-end for the nanobot gateway. It is built with Vite + React 18 +
TypeScript + Tailwind 3 + shadcn/ui, talks to the gateway over the WebSocket
multiplex protocol, and reads session metadata from the embedded REST surface
on the same port.

For the project overview, install guide, and general docs map, see the root
[`README.md`](../README.md).

## Just want to use the WebUI?

If you installed nanobot via `pip install nanobot-ai`, the WebUI is **already bundled** in the wheel. Enable the WebSocket channel in `~/.nanobot/config.json` and run `nanobot gateway` — see the root [`README.md`](../README.md#-webui) for the 3-step setup. You do **not** need anything in this directory.

This `webui/` tree is for people **hacking on the WebUI itself** (UI changes, new components, styling, etc.).

## Layout

```text
webui/                 source tree (this directory)
nanobot/web/dist/      build output served by the gateway
```

## Develop the WebUI (Vite HMR)

### 1. Install nanobot from source

From the repository root:

```bash
pip install -e .
```

> Editable installs intentionally **skip** the WebUI bundle step — Vite HMR is faster than rebuilding `dist/` on every change.

### 2. Enable the WebSocket channel

In `~/.nanobot/config.json`:

```json
{ "channels": { "websocket": { "enabled": true } } }
```

### 3. Start the gateway

In one terminal:

```bash
nanobot gateway
```

### 4. Start the WebUI dev server

In another terminal:

```bash
cd webui
bun install            # npm install also works
bun run dev
```

Then open `http://127.0.0.1:5173`.

By default the dev server proxies `/api`, `/webui`, `/auth`, and WebSocket traffic to `http://127.0.0.1:8765`.

If your gateway listens on a non-default port, point the dev server at it:

```bash
NANOBOT_API_URL=http://127.0.0.1:9000 bun run dev
```

### Access from another device (LAN)

To use the WebUI from another device on the same network, set `host` to `"0.0.0.0"` and configure a `token` or `tokenIssueSecret` in `~/.nanobot/config.json`:

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 8765,
      "tokenIssueSecret": "your-secret-here"
    }
  }
}
```

The gateway will refuse to start if `host` is `"0.0.0.0"` and neither `token` nor `tokenIssueSecret` is set.

Then open `http://<your-ip>:8765` on the other device. The WebUI will show an authentication form where you enter the secret. It is saved in your browser so you only need to enter it once.

## Build for packaged runtime

You usually do not need to run this by hand: `python -m build` invokes the WebUI build automatically when packaging the wheel.

If you want to preview the production bundle locally without rebuilding the wheel:

```bash
cd webui
bun run build          # writes to ../nanobot/web/dist
```

The gateway picks up the new bundle on the next restart.

## Test

```bash
cd webui
bun run test
```

## Acknowledgements

- [`agent-chat-ui`](https://github.com/langchain-ai/agent-chat-ui) for UI and
  interaction inspiration across the chat surface.
