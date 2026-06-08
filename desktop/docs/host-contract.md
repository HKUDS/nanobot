# Native Host Contract

This is a contributor reference for the boundary between the shared WebUI and
the native desktop host. Users should not need this contract to run the app, but
it explains why the desktop app can use native capabilities without turning the
WebUI into Electron-specific code.

`desktop` is a native host shell around the shared WebUI build. The renderer
must not import Electron directly. It receives a minimal bridge at
`window.nanobotHost`.

## Runtime API

```ts
type HostRuntimeInfo = {
  surface: "native";
  app_version: string;
  engine_status: "starting" | "ready" | "restarting" | "stopped" | "crashed";
  data_dir: string;
  logs_dir: string;
  config_path: string;
  workspace_path: string;
  python: string;
  engine_transport?: "unix_socket";
};

type HostSocketEvent =
  | { id: string; type: "open" }
  | { id: string; type: "message"; data: string }
  | { id: string; type: "error"; message: string }
  | { id: string; type: "close"; code?: number; reason?: string };

type NanobotHost = {
  getRuntimeInfo(): Promise<HostRuntimeInfo>;
  restartEngine(): Promise<void>;
  pickFolder(): Promise<string | null>;
  openLogs(): Promise<void>;
  exportDiagnostics(): Promise<string>;
  checkForUpdates(): Promise<{ supported: boolean; message?: string }>;
  openSocket(url: string): Promise<string>;
  sendSocket(id: string, data: string): Promise<void>;
  closeSocket(id: string): Promise<void>;
  onSocketEvent(listener: (event: HostSocketEvent) => void): () => void;
  onRuntimeStatus(listener: (status: HostRuntimeInfo["engine_status"]) => void): () => void;
};
```

## First Run

The desktop host starts the private engine immediately. If the native data
directory has no `config.json`, `nanobot desktop-gateway` creates one with
defaults before serving the shared WebUI. Provider, model, credential, and login
setup stay in WebUI settings instead of Electron-owned HTML.

## Socket Bridge

The engine listens on a per-user Unix socket under the app data directory.
`/webui/bootstrap` returns `runtime_surface: "native"` and a WebSocket URL in
the `nanobot-host://engine/...` scheme. WebUI never opens that URL directly in
the browser runtime; it hands the URL to `window.nanobotHost.openSocket`.

The native host then performs the WebSocket handshake against the Unix socket
and forwards events over Electron IPC.

## Host Security Boundary

The host bridge is intentionally narrower than a general Electron preload:

- IPC calls are accepted only from renderer frames loaded from `nanobot-app://app/...`.
- `openSocket` accepts only `nanobot-host://engine/...` URLs.
- External navigation is denied in the app window; safe web links are opened by
  the operating system.
- Native WebUI responses carry a restrictive Content Security Policy and
  `X-Content-Type-Options: nosniff`.
- The renderer runs with `nodeIntegration: false`, `contextIsolation: true`,
  `sandbox: true`, and `webSecurity: true`.

Security-sensitive tool behavior still belongs in nanobot core. The host
protects the native app boundary; the engine protects file, network, and tool
permissions.

## Data Directory

The host stores config, workspace, sessions, logs, and transient socket files
under Electron's platform app data directory. In development on macOS this is
usually:

```text
~/Library/Application Support/@nanobot/desktop/
```

Packaged builds use the packaged app name.

The app bundle is replaceable. User data is not stored in the bundle.
