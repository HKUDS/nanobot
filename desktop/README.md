# nanobot Desktop

Electron package for the Mac-first nanobot native app.

This folder is a host shell. It reuses the root WebUI build at
`nanobot/web/dist`; it does not copy or fork `webui/src`. Electron owns the
local engine lifecycle, exposes `window.nanobotHost` to the renderer, serves the
`nanobot-app://` app protocol, and proxies `/api/*` plus `/webui/bootstrap` to a
private Unix socket `nanobot desktop-gateway` process.

## Development

```sh
cd desktop
bun run dev:webui
```

In another terminal:

```sh
cd desktop
bun run dev:app
```

`dev:app` points Electron at the Vite dev server so WebUI changes hot reload.
For source checkouts, the app uses `python3` by default and injects the repo
root into `PYTHONPATH`. Packaged builds look for a bundled interpreter at
`Resources/nanobot-engine/bin/python3`.

## Engine Bundle

Release builds prepare `resources/nanobot-engine/` from a macOS
`python-build-standalone` archive before running `electron-builder`.
By default the script discovers the latest `astral-sh/python-build-standalone`
CPython 3.12 `install_only` asset for the requested architecture.

```sh
cd desktop
bun run make:mac:arm64
bun run make:mac:x64
```

Useful overrides:

- `NANOBOT_DESKTOP_ARCH=arm64|x64`
- `NANOBOT_DESKTOP_PYTHON_VERSION=3.12`
- `PYTHON_STANDALONE_RELEASE=20260510`
- `PYTHON_STANDALONE_TARBALL=/path/to/archive.tar.gz`
- `PYTHON_STANDALONE_URL=https://.../cpython-...tar.gz`
- `NANOBOT_WHEELHOUSE=/path/to/wheels` to install from a locked wheelhouse

The script installs the current checkout's `nanobot-ai[api]` into the bundled
runtime and writes `nanobot-engine.json` for diagnostics.

## Updating Builds

The native host does not copy the WebUI source or fork the Python agent code. A
release bundle is assembled from the current repository state:

1. Build the shared WebUI:

   ```sh
   bun run build --prefix webui
   ```

   `electron-builder` packages the resulting `nanobot/web/dist` directory as
   `Resources/nanobot-webui`.

2. Prepare the bundled Python engine:

   ```sh
   cd desktop
   NANOBOT_DESKTOP_ARCH=arm64 bun run prepare-engine
   ```

   The script installs the current checkout's `nanobot-ai[api]` package into
   `resources/nanobot-engine/`, so agent, provider, tool, WebSocket, and config
   changes flow into the next desktop build automatically.

3. Build the desktop app and DMG:

   ```sh
   bun run make:mac:arm64
   bun run make:mac:x64
   ```

User data is not stored in the app bundle. Config, sessions, logs, workspace
state, and the default workspace remain under the platform app data directory,
so updating the app replaces code without overwriting local user state.

## Runtime Contract

- User data lives under the platform app data directory (`~/Library/Application Support/nanobot/` on macOS).
- Fresh installs start the private engine directly. The Python desktop gateway
  creates the first `config.json` with defaults, then shared WebUI settings own
  provider, model, and credential setup.
- The gateway listens on a per-user Unix socket in the app data directory and uses a transient secret.
- The gateway starts with only the WebSocket local channel enabled and does not serve the WebUI static bundle.
- The renderer loads assets through `nanobot-app://app/...`; browser users cannot open the native UI from a localhost port.
- WebSocket traffic uses the generic `nanobot-host://engine/...` URL, is bridged over Electron IPC, and still uses the short-lived token minted by `/webui/bootstrap`.
- Host IPC only accepts the trusted app origin, and socket bridging only accepts the `nanobot-host://engine/...` scheme.
- Native WebUI responses include a restrictive Content Security Policy.
- WebUI talks only to the generic `window.nanobotHost` contract. Product-specific native behavior stays in this folder.

Generated release artifacts, node modules, and bundled runtimes remain ignored
so the tracked desktop package stays source-only.

See also:

- [`docs/development.md`](docs/development.md)
- [`docs/host-contract.md`](docs/host-contract.md)
- [`docs/webui-sync.md`](docs/webui-sync.md)
