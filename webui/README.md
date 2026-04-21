# nanobot webui

The browser front-end for `nanobot web`. It is built with Vite + React 18 +
TypeScript + Tailwind 3 + shadcn/ui, talks to the gateway over the WebSocket
multiplex protocol, and reads session metadata from the embedded REST surface
on the same port.

For the project overview, install guide, and general docs map, see the root
[`README.md`](../README.md).

## Current status

> [!NOTE]
> The standalone WebUI development workflow currently requires a source
> checkout.
>
> WebUI changes in the GitHub repository may land before they are included in
> the next packaged release, so source installs and published package versions
> are not yet guaranteed to move in lockstep.

## Layout

```text
webui/                 source tree (this directory)
nanobot/web/dist/      build output consumed by `nanobot web`
```

## Develop from source

### 1. Install nanobot from source

From the repository root:

```bash
pip install -e .
```

### 2. Start the gateway

In one terminal:

```bash
nanobot gateway
```

### 3. Start the WebUI dev server

In another terminal:

```bash
cd webui
bun install            # npm install also works
bun run dev
```

Then open `http://127.0.0.1:5173`.

By default, the dev server proxies `/api`, `/webui`, `/auth`, and WebSocket
traffic to `http://127.0.0.1:8765`.

If your gateway listens on a non-default port, point the dev server at it:

```bash
NANOBOT_API_URL=http://127.0.0.1:9000 bun run dev
```

## Build for packaged runtime

```bash
cd webui
bun run build
```

This writes the production assets to `../nanobot/web/dist`, which is the
directory served by `nanobot web` and bundled into the Python wheel.

If you are cutting a release, run the build before packaging so the published
wheel contains the current WebUI assets.

## Test

```bash
cd webui
bun run test
```

## Acknowledgements

- [`agent-chat-ui`](https://github.com/langchain-ai/agent-chat-ui) for UI and
  interaction inspiration across the chat surface.
