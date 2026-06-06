# WebUI Sync Workflow

This workflow is for contributors keeping the desktop app and browser WebUI in
sync. Users should experience them as one product surface: desktop adds a native
host and local engine lifecycle, while chat, settings, apps, skills, and
workspace UI still come from the shared WebUI.

`desktop` consumes the shared WebUI build output. It must not copy, fork, or
vendor `webui/src`.

## Development

Run the WebUI dev server:

```sh
cd desktop
bun run dev:webui
```

Run the native host in another terminal:

```sh
cd desktop
bun run dev:app
```

The host loads `http://127.0.0.1:5173` in development, so React changes hot
reload. Main/preload changes still require restarting `dev:app`.

## Release Build

1. Build the shared WebUI:

   ```sh
   bun run build --prefix webui
   ```

2. Prepare the bundled Python engine:

   ```sh
   cd desktop
   NANOBOT_DESKTOP_ARCH=arm64 bun run prepare-engine
   ```

3. Build the app:

   ```sh
   bun run make:mac:arm64
   bun run make:mac:x64
   ```

`electron-builder` packages `nanobot/web/dist` as `Resources/nanobot-webui`.

## Checklist

- WebUI source remains host-neutral: it may branch on generic runtime
  capabilities, but it must not import Electron or desktop source files.

  ```sh
  rg -n "from ['\\\"]electron|desktop/src|nanobotDesktop" webui/src
  ```

  This command should print nothing.

- Native host behavior is implemented in `desktop/src`.
- Provider, model, credential, and login setup stay in shared WebUI settings.
  Do not duplicate those flows in Electron-owned HTML.
- Shared UI behavior is implemented in `webui/src` through `window.nanobotHost`
  and generic runtime capability checks.
- Do not copy React components from `webui/src` into this folder.
- Do not commit bundled runtimes, DMGs, or `node_modules`.
