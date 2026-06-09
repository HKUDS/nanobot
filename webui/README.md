# blackcat WebUI

The WebUI is the browser workbench served by `blackcat gateway`. If you installed `blackcat-ai` from PyPI, the WebUI bundle is already included; this `webui/` source tree is only needed when you are changing the frontend.

For the project overview, install guide, and general docs map, see the root [`README.md`](../README.md) and [`docs/README.md`](../docs/README.md).

## Pick a Path

| Goal | Start with | Opens at |
|---|---|---|
| Use the bundled browser UI | [Just want to use the WebUI?](#just-want-to-use-the-webui) | `http://127.0.0.1:8765` |
| Use the WebUI from another device | [Access from another device (LAN)](#access-from-another-device-lan) | `http://<your-ip>:8765` |
| Change WebUI source code | [Develop the WebUI (Vite HMR)](#develop-the-webui-vite-hmr) | `http://127.0.0.1:5173` |
| Debug setup failures | [`docs/troubleshooting.md#webui-problems`](../docs/troubleshooting.md#webui-problems) | Diagnosis order and common fixes |

## Just want to use the WebUI?

If you installed blackcat via `python -m pip install blackcat-ai`, the WebUI is **already bundled** in the wheel. You do **not** need Node.js, Bun, Vite, or anything in this directory unless you are changing the WebUI source code.

First prove the provider path:

```bash
blackcat agent -m "Hello!"
```

If the shell cannot find `blackcat`, use the module form from the same Python environment:

```bash
python -m blackcat agent -m "Hello!"
```

Then merge this WebSocket snippet into your existing `~/.blackcat/config.json` instead of replacing the whole file:

```json
{ "channels": { "websocket": { "enabled": true } } }
```

If you are new to JSON snippets, see [`docs/start-without-technical-background.md#how-to-merge-json-snippets`](../docs/start-without-technical-background.md#how-to-merge-json-snippets).

Start the gateway:

```bash
blackcat gateway
```

Leave this terminal running while you use the WebUI. Closing it stops the browser UI and WebSocket connection.

Open [`http://127.0.0.1:8765`](http://127.0.0.1:8765). The gateway's `18790` port is only the health endpoint, not the browser UI. For setup failures, use [`docs/troubleshooting.md`](../docs/troubleshooting.md#webui-problems).

This `webui/` tree is for people **changing the WebUI source code**. It is built with Vite + React 18 + TypeScript + Tailwind 3 + shadcn/ui, talks to the gateway over the WebSocket multiplex protocol, and reads session metadata from the embedded REST surface on the same port.

## Layout

```text
webui/                 source tree (this directory)
blackcat/web/dist/      build output served by the gateway
```

## Develop the WebUI (Vite HMR)

### 1. Install blackcat from source

From the repository root:

```bash
python -m pip install -e .
```

> Editable installs intentionally **skip** the WebUI bundle step — Vite HMR is faster than rebuilding `dist/` on every change.

### 2. Enable the WebSocket channel

In `~/.blackcat/config.json`, merge:

```json
{ "channels": { "websocket": { "enabled": true } } }
```

### 3. Start the gateway

In one terminal:

```bash
blackcat gateway
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

To use the WebUI from another device on the same network, set `host` to `"0.0.0.0"` and configure a `token` or `tokenIssueSecret` in `~/.blackcat/config.json`:

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
bun run build          # writes to ../blackcat/web/dist
```

The gateway picks up the new bundle on the next restart.

## Test

```bash
cd webui
bun run test
```

## Acknowledgements

- [`agent-chat-ui`](https://github.com/langchain-ai/agent-chat-ui) for UI and interaction inspiration across the chat surface.
