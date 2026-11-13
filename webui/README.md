# nanobot WebUI Source

This directory contains the React/TypeScript source for the nanobot WebUI. If you installed `nanobot-ai` from PyPI and only want to use the bundled browser UI, read the user guide in [`docs/webui.md`](../docs/webui.md). You do not need Node.js, Bun, Vite, or anything in this directory unless you are changing the frontend.

For the project overview, install guide, and general docs map, see the root [`README.md`](../README.md) and [`docs/README.md`](../docs/README.md).

## Pick a Path

| Goal | Start with | Opens at |
|---|---|---|
| Use the bundled browser UI | [`docs/webui.md`](../docs/webui.md) | `http://127.0.0.1:8765` |
| Use the WebUI from another device | [`docs/webui.md#lan-access`](../docs/webui.md#lan-access) | `http://<your-ip>:8765` |
| Change WebUI source code | [Develop the WebUI (Vite HMR)](#develop-the-webui-vite-hmr) | `http://127.0.0.1:5173` |
| Debug setup failures | [`docs/troubleshooting.md#webui-problems`](../docs/troubleshooting.md#webui-problems) | Diagnosis order and common fixes |

The source app is built with Vite + React 18 + TypeScript + Tailwind 3 + shadcn/ui. It talks to the gateway over the WebSocket multiplex protocol and reads session metadata from the embedded REST surface on the same port.

## Layout

For existing components, ownership boundaries, and interactive examples, see the [component guide](COMPONENTS.md). `bun run gallery` opens the internal component gallery without starting a gateway.

```text
webui/                 source tree (this directory)
nanobot/web/dist/      build output served by the gateway
webui/src/components/settings/   model, capability, and system settings
webui/src/lib/                   transport, API clients, and shared types
webui/src/tests/                 frontend test setup and integration tests
nanobot/channels/*/webui/        channel-owned interface code
nanobot/channels/*/tests/webui/  channel interface tests
```

## Change a behavior

Choose the behavior first, then follow the owning module and its existing tests. Paths below are relative to `webui/` unless they start with `../`. Read [component ownership](COMPONENTS.md#where-components-belong) when introducing or moving a boundary.

| Change | Owning source | Start verification with |
| --- | --- | --- |
| Composer input, attachments, or mentions | [`ThreadComposer.tsx`](src/components/thread/ThreadComposer.tsx) and its input hooks | [`thread-composer.test.tsx`](src/tests/thread-composer.test.tsx), [`thread-composer-attach.test.tsx`](src/tests/thread-composer-attach.test.tsx) |
| Waiting prompts: merging, persistence, sending, or turn completion | [`useQueuedPrompt.ts`](src/components/thread/useQueuedPrompt.ts); Composer supplies draft content and UI feedback | [`queued-guidance.test.tsx`](src/tests/queued-guidance.test.tsx) and queue scenarios in [`thread-composer.test.tsx`](src/tests/thread-composer.test.tsx); completion integration in [`turn-completion.test.tsx`](src/tests/turn-completion.test.tsx), browser flow in [`queued-guidance.spec.ts`](browser/queued-guidance.spec.ts) |
| Chat-channel pairing prompts and approval | [`ChannelPairing.tsx`](src/components/pairing/ChannelPairing.tsx) owns requests and subscriptions; [`PairingCodePopup.tsx`](src/components/pairing/PairingCodePopup.tsx) owns the input/display; backend [`nanobot/pairing/`](../nanobot/pairing/) | Pairing scenarios in [`app-layout.test.tsx`](src/tests/app-layout.test.tsx), [`pairing-refresh.spec.ts`](browser/pairing-refresh.spec.ts) |
| Startup, authentication, navigation, or session selection | [`App.tsx`](src/App.tsx), [`useSessions.ts`](src/hooks/useSessions.ts), [`ClientProvider.tsx`](src/providers/ClientProvider.tsx) | [`app-layout.test.tsx`](src/tests/app-layout.test.tsx); keep shell integration checks when moving an owner |
| Live messages, delivery, or completion | [`nanobot-client.ts`](src/lib/nanobot-client.ts), [`useNanobotStream.ts`](src/hooks/useNanobotStream.ts), [`ThreadShell.tsx`](src/components/thread/ThreadShell.tsx) | [`nanobot-client.test.ts`](src/tests/nanobot-client.test.ts), [`useNanobotStream.test.tsx`](src/tests/useNanobotStream.test.tsx), [`thread-shell.test.tsx`](src/tests/thread-shell.test.tsx) |
| History pagination, reading position, or boundary motion | [`usePromptHistory.ts`](src/hooks/usePromptHistory.ts), [`ThreadViewport.tsx`](src/components/thread/ThreadViewport.tsx); [motion ownership](COMPONENTS.md#history-boundary-motion) | [`thread-viewport.test.tsx`](src/tests/thread-viewport.test.tsx), [`thread-history-spring.test.ts`](src/tests/thread-history-spring.test.ts), [`thread-loading.spec.ts`](browser/thread-loading.spec.ts) |
| Settings forms or persistence | The feature under [`components/settings/`](src/components/settings/) and [`useSettingsController.ts`](src/components/settings/useSettingsController.ts) | Matching `settings-*.test.tsx` in [`src/tests/`](src/tests/); backend settings tests in [`tests/webui/`](../tests/webui/) |
| A channel's setup interface | Its package under [`nanobot/channels/`](../nanobot/channels/), including `webui/` and translations | The same package's `tests/webui/`, plus [`settings-channels.test.tsx`](src/tests/settings-channels.test.tsx) |
| A shared control or content renderer | [Component guide and gallery](COMPONENTS.md) | Its existing component tests and affected production caller; browser tests for layout, focus, or motion |

For a focused component check, run `bun run test src/tests/thread-composer.test.tsx`; for the pairing browser flow, run `bun run test:browser browser/pairing-refresh.spec.ts`. These are examples, not a substitute for [full checks](#test). HTTP/WebSocket, host, or persisted-state changes also require the [client/host compatibility review](../.agent/review-guide.md).

## Develop the WebUI (Vite HMR)

### 1. Install nanobot from source

From the repository root:

```bash
python -m pip install -e .
```

> Editable installs intentionally **skip** the WebUI bundle step — Vite HMR is faster than rebuilding `dist/` on every change.

### 2. Start the gateway and Vite

From the repository root:

```bash
nanobot webui --dev
```

The command safely prepares the local WebSocket channel, starts both the gateway and Vite, and opens `http://127.0.0.1:5173`. Vite proxies HTTP requests to the gateway and applies frontend changes with HMR; the application WebSocket connects directly to the gateway. Ctrl+C stops Vite and releases this gateway client. An on-demand gateway stops when its last interactive client exits; a persistent gateway keeps running.

Use `--no-open` to skip opening a browser. `--dev-port 5174` selects a different Vite port when running multiple development instances; each instance also needs its own config, workspace, WebUI port, and gateway port. `--dev` is foreground-only and cannot be combined with `--background`.

## Manual development setup

The two-terminal workflow remains available when you want to manage each process separately.

### 1. Enable the WebSocket channel

In `~/.nanobot/config.json`, merge:

```json
{ "channels": { "websocket": { "enabled": true } } }
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

By default Vite proxies the HTTP paths `/api`, `/webui`, and `/auth` to `http://127.0.0.1:8765`. The application WebSocket connects directly to the URL returned by the gateway bootstrap response (`ws_url`); Vite does not proxy that connection.

If your gateway listens on a non-default port, point the dev server at it:

```bash
NANOBOT_API_URL=http://127.0.0.1:9000 bun run dev
```

This variable sets the HTTP target. Check the bootstrap response's `ws_url` when HTTP works but chat cannot connect: that address must be reachable by the browser. For a reverse proxy, configure the gateway's `channels.websocket.publicWsUrl` as described in [WebSocket deployment](../docs/websocket.md), rather than adding a Vite WebSocket proxy. If authentication is enabled, use the launcher's full login link or sign in with the configured bootstrap secret.

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
bun run lint
bun run typecheck
bun run test
bun x playwright install chromium
bun run test:browser
bun run build
```

`lint` runs ESLint; `typecheck` checks application and unit-test TypeScript, including channel-owned frontend code and tests; `test` runs Vitest; `test:browser` typechecks and runs Chromium tests with the real components and stylesheet to check tall-dialog reachability and completed-history motion without a gateway; `build` checks production TypeScript and produces the production bundle. Keep tests near the changed behavior and exercise settings save/reload in the browser. Browser-only preferences stay in the frontend; persistent configuration and security policy belong to the Python gateway. When changing that boundary, also run the relevant Python tests from [CONTRIBUTING.md](../CONTRIBUTING.md).

## Acknowledgements

- [`agent-chat-ui`](https://github.com/langchain-ai/agent-chat-ui) for UI and interaction inspiration across the chat surface.
