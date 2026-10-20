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

Use `--no-open` to skip opening a browser. `--dev` is foreground-only and cannot be combined with `--background`.

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

## Execution-state contract

`webui.runs.v1` is an optional capability within WebUI protocol 1; it does not raise the core protocol floor. Hosts without it remain usable for basic chat. The client reports execution state as unavailable rather than inferring it from legacy `goal_status`, transcript markers or local actions.

The authenticated socket's `ready.run_state_instance_id` pins the runtime authority. `run_state` snapshots on `ready`, `attached`, session index rows, thread responses and dedicated `{event: "run_state", chat_id, run_state}` notifications carry `{instance_id, revision, runs, completed}`. Revisions are monotonic within one gateway instance; they are unrelated to history ETags or client generations. Each run has an opaque execution `run_id`, optional `turn_id`, `phase` (`queued`, `running`, `stopping`) and nullable epoch-second `started_at`. An empty run set explicitly means idle. Bounded completion receipts report execution outcomes, not successful result delivery; an absent receipt never proves success.

`{type: "watch_runs", chat_ids: [...]}` replaces a socket's state-only subscriptions. The gateway validates access, registers the set and enqueues a full baseline for each chat without an intervening await. This avoids a snapshot/subscription gap and does not subscribe sidebar sessions to transcript text. Full chat attachment also sends a baseline. Updates reuse the bounded socket outbound queue; backpressure disconnects require a fresh baseline rather than silently losing the final state.

The client accepts runtime snapshots only from its pinned instance and at nondecreasing per-session revisions. Replaced sockets cannot update the store; disconnect marks state unknown, and reconnection requires fresh confirmation even if the revision is unchanged. HTTP can supply versioned state only after the current socket pins its instance; HTTP alone cannot restore freshness after a disconnect, even at the same revision. No history marker, text chunk, local send, upload or cancellation request can change confirmed execution.

Stop uses the existing correlated `webui_request` action `runs.stop` with `{chat_id, run_ids}`. The gateway targets those execution owners, not whatever happens to be running when a delayed request arrives. A successful mutation response acknowledges the request, not execution exit. Input delivery, execution liveness, cancellation intent, transcript recovery and final-result settlement remain separate. The rendered or cached canonical result must be committed before completion fences prune buffered events or queued input is released.

## Acknowledgements

- [`agent-chat-ui`](https://github.com/langchain-ai/agent-chat-ui) for UI and interaction inspiration across the chat surface.
