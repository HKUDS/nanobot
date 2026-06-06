# Desktop Development Guide

This guide is for GitHub contributors who want to change the desktop app. If
you are using nanobot rather than developing it, the important bit is simpler:
desktop runs the local engine for you and shows the same chat, settings, apps,
skills, and workspace UI as the browser WebUI.

`desktop` is the native host for the shared nanobot WebUI. It is not a fork of
the WebUI, and it should not grow a second copy of product UI.

The healthy mental model is:

```text
nanobot core  -> agent runtime, gateway, providers, tools, memory
webui         -> shared product UI and runtime-aware UI
desktop       -> native host, engine lifecycle, secure host capabilities
```

## Development Workflow

Use this when developing from a source checkout.

Run the shared WebUI dev server:

```sh
cd desktop
bun run dev:webui
```

Run the Electron host in another terminal:

```sh
cd desktop
bun run dev:app
```

In development, Electron loads `http://127.0.0.1:5173`, so changes under
`webui/src` hot reload. Changes under `desktop/src` require restarting
`dev:app`.

For source checkouts, the host starts the engine with local `python3` and
injects the repository root into `PYTHONPATH`. This means Python changes under
`nanobot/` are picked up from the current checkout.

## Where Code Goes

Use this table before adding a desktop feature:

| Change | Location |
| --- | --- |
| Agent behavior, tools, providers, memory, config schema | `nanobot/` |
| Shared chat UI, settings UI, reusable product UI | `webui/` |
| Runtime-aware UI rows, such as native engine status or open logs buttons | `webui/` |
| The implementation behind native capabilities | `desktop/src/main.ts` |
| The trusted renderer bridge contract | `desktop/src/preload.cts` and `desktop/docs/host-contract.md` |
| Electron window, app protocol, native menus, lifecycle, packaging | `desktop/src` and `desktop/package.json` |
| WebSocket-over-Unix-socket bridge | `desktop/src/unixWebSocket.ts` |
| Bundled Python runtime preparation | `desktop/scripts/prepare-engine.mjs` |

For example, if desktop Settings needs an "Open logs" button, the button belongs
in the shared WebUI settings page because it is product UI. The actual filesystem
operation belongs in the desktop host and is exposed through `window.nanobotHost`.

## Host Contract

The shared WebUI talks to desktop through `window.nanobotHost`. WebUI code may
check for host capabilities, but it must not import Electron, Node.js modules,
or desktop source files.

Prefer capability-driven UI:

```text
if host can open logs -> show Open logs
if host can restart engine -> show Restart engine
```

Avoid platform-driven UI:

```text
if desktop -> run Electron-specific logic in WebUI
```

This keeps the WebUI usable in browsers and leaves room for future native hosts
without rewriting product screens.

## Adding A Desktop Feature

Before implementing, answer these questions:

1. Is this product UI or a native capability?
2. Can the WebUI express it through a generic capability instead of a desktop flag?
3. Does the host API validate trusted origins and accepted URL schemes?
4. Does browser WebUI still work when `window.nanobotHost` is missing?
5. Does the engine behavior belong in nanobot core instead of Electron?
6. Does packaged mode use app data for user state instead of app resources?

## Anti-Patterns

- Do not copy or fork `webui/src` into `desktop/`.
- Do not import Electron or Node.js modules from `webui/src`.
- Do not add provider-specific onboarding screens to `desktop/`.
- Do not duplicate WebUI settings or login flows in Electron-owned HTML.
- Do not make `desktop/src/main.ts` own agent behavior.
- Do not commit `desktop/node_modules`, `desktop/build`, `desktop/dist`, DMGs,
  or `desktop/resources/nanobot-engine`.

## Release Shape

Release builds assemble three existing parts:

1. the shared WebUI build from `nanobot/web/dist`,
2. the Python engine prepared under `desktop/resources/nanobot-engine`,
3. the Electron host compiled from `desktop/src`.

User config, logs, sessions, workspace state, and the default workspace live in
the platform app data directory, not inside the app bundle.
