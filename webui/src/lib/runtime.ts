import type { RuntimeCapabilities, RuntimeSurface } from "./types";

export interface RuntimeHost {
  surface: RuntimeSurface;
  capabilities: RuntimeCapabilities;
  socketFactory?: (url: string) => WebSocket;
  pickFolder?: () => Promise<string | null>;
  restartEngine?: () => Promise<void>;
  openLogs?: () => Promise<void>;
  exportDiagnostics?: () => Promise<string>;
}

export interface HostRuntimeInfo {
  surface: "native";
  app_version: string;
  engine_status: "starting" | "ready" | "restarting" | "stopped" | "crashed";
  data_dir: string;
  logs_dir: string;
  config_path: string;
  workspace_path: string;
  python: string;
  api_base?: string;
  engine_transport?: "unix_socket";
}

export interface NanobotHostApi {
  getRuntimeInfo?(): Promise<HostRuntimeInfo>;
  restartEngine?(): Promise<void>;
  pickFolder?(): Promise<string | null>;
  openLogs?(): Promise<void>;
  exportDiagnostics?(): Promise<string>;
  openSocket?(url: string): Promise<string>;
  sendSocket?(id: string, data: string): Promise<void>;
  closeSocket?(id: string): Promise<void>;
  onSocketEvent?(
    listener: (event: HostSocketEvent) => void,
  ): () => void;
  onRuntimeStatus?(
    listener: (status: HostRuntimeInfo["engine_status"]) => void,
  ): () => void;
}

export type HostSocketEvent =
  | { id: string; type: "open" }
  | { data: string; id: string; type: "message" }
  | { id: string; message: string; type: "error" }
  | { code?: number; id: string; reason?: string; type: "close" };

type HostSocketBridge = Required<Pick<
  NanobotHostApi,
  "closeSocket" | "onSocketEvent" | "openSocket" | "sendSocket"
>>;

const HOST_WS_CONNECTING = 0;
const HOST_WS_OPEN = 1;
const HOST_WS_CLOSING = 2;
const HOST_WS_CLOSED = 3;
const LOOPBACK_HOST_PORT_PARAM = "nativeHostPort";
const LOOPBACK_HOST_TOKEN_PARAM = "nativeHostToken";
const LOOPBACK_HOST_STORAGE_KEY = "nanobot-webui.native-host";

interface LoopbackHostConfig {
  port: number;
  token: string;
}

let loopbackHostApi: NanobotHostApi | null = null;

declare global {
  interface Window {
    nanobotHost?: NanobotHostApi;
  }
}

function getHostApi(): NanobotHostApi | null {
  if (typeof window === "undefined") return null;
  return window.nanobotHost ?? loopbackHostApi;
}

/**
 * Install the external native-host bridge advertised in the URL fragment.
 *
 * Only a loopback port is accepted; callers cannot redirect privileged host
 * actions to an arbitrary origin. The short-lived bridge token is removed
 * from the URL and retained only for the lifetime of this browser tab.
 */
export function initializeLoopbackRuntimeHost(): boolean {
  if (typeof window === "undefined") return false;
  const config = consumeLoopbackHostConfig() ?? loadLoopbackHostConfig();
  loopbackHostApi = config ? createLoopbackHostApi(config) : null;
  return loopbackHostApi !== null;
}

export function toRuntimeSurface(surface: string | null | undefined): RuntimeSurface {
  return surface === "native" ? "native" : "browser";
}

export function createRuntimeHost(
  surface: RuntimeSurface,
  capabilities?: Partial<RuntimeCapabilities> | null,
): RuntimeHost {
  const api = getHostApi();
  const mergedCapabilities = {
    can_export_diagnostics: false,
    can_open_logs: false,
    can_pick_folder: false,
    can_restart_engine: false,
    ...(capabilities ?? {}),
  };
  const bridge = getHostSocketBridge();
  return {
    surface,
    capabilities: mergedCapabilities,
    socketFactory: bridge ? createHostWebSocket : undefined,
    pickFolder: api?.pickFolder?.bind(api),
    restartEngine: api?.restartEngine?.bind(api),
    openLogs: api?.openLogs?.bind(api),
    exportDiagnostics: api?.exportDiagnostics?.bind(api),
  };
}

export function getRuntimeHost(
  surface?: string | null,
  capabilities?: Partial<RuntimeCapabilities> | null,
): RuntimeHost {
  const api = getHostApi();
  const runtimeSurface =
    surface == null ? (api ? "native" : "browser") : toRuntimeSurface(surface);
  return createRuntimeHost(runtimeSurface, capabilities);
}

export function isNativeRuntime(surface?: string | null): boolean {
  return getHostApi() !== null || toRuntimeSurface(surface) === "native";
}

export function createHostWebSocket(url: string): WebSocket {
  const api = getHostSocketBridge();
  if (!api) {
    throw new Error("Host WebSocket bridge is not available");
  }
  return new HostWebSocket(api, url) as unknown as WebSocket;
}

function getHostSocketBridge(): HostSocketBridge | null {
  const api = getHostApi();
  const { closeSocket, onSocketEvent, openSocket, sendSocket } = api ?? {};
  if (
    !openSocket
    || !sendSocket
    || !closeSocket
    || !onSocketEvent
  ) {
    return null;
  }
  return {
    closeSocket: (id) => closeSocket.call(api, id),
    onSocketEvent: (listener) => onSocketEvent.call(api, listener),
    openSocket: (url) => openSocket.call(api, url),
    sendSocket: (id, data) => sendSocket.call(api, id, data),
  };
}

function consumeLoopbackHostConfig(): LoopbackHostConfig | null {
  const hash = window.location.hash || "";
  const queryStart = hash.indexOf("?");
  if (queryStart < 0) return null;

  const path = hash.slice(0, queryStart) || "#/";
  const params = new URLSearchParams(hash.slice(queryStart + 1));
  const hasBridgeParams = params.has(LOOPBACK_HOST_PORT_PARAM)
    || params.has(LOOPBACK_HOST_TOKEN_PARAM);
  if (!hasBridgeParams) return null;

  const config = validateLoopbackHostConfig({
    port: Number(params.get(LOOPBACK_HOST_PORT_PARAM)),
    token: params.get(LOOPBACK_HOST_TOKEN_PARAM) ?? "",
  });
  params.delete(LOOPBACK_HOST_PORT_PARAM);
  params.delete(LOOPBACK_HOST_TOKEN_PARAM);
  const nextQuery = params.toString();
  const nextHash = `${path}${nextQuery ? `?${nextQuery}` : ""}`;
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${nextHash}`,
  );

  try {
    if (config) {
      window.sessionStorage.setItem(LOOPBACK_HOST_STORAGE_KEY, JSON.stringify(config));
    } else {
      window.sessionStorage.removeItem(LOOPBACK_HOST_STORAGE_KEY);
    }
  } catch {
    // The current page can still use the bridge when session storage is unavailable.
  }
  return config;
}

function loadLoopbackHostConfig(): LoopbackHostConfig | null {
  try {
    const raw = window.sessionStorage.getItem(LOOPBACK_HOST_STORAGE_KEY);
    if (!raw) return null;
    return validateLoopbackHostConfig(JSON.parse(raw) as Partial<LoopbackHostConfig>);
  } catch {
    return null;
  }
}

function validateLoopbackHostConfig(
  value: Partial<LoopbackHostConfig>,
): LoopbackHostConfig | null {
  const port = Number(value.port);
  const token = typeof value.token === "string" ? value.token : "";
  if (!Number.isInteger(port) || port < 1 || port > 65_535) return null;
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(token)) return null;
  return { port, token };
}

function createLoopbackHostApi(config: LoopbackHostConfig): NanobotHostApi {
  return {
    async pickFolder(): Promise<string | null> {
      let response: Response;
      try {
        response = await fetch(`http://127.0.0.1:${config.port}/v1/pick-folder`, {
          method: "POST",
          cache: "no-store",
          credentials: "omit",
          referrerPolicy: "no-referrer",
          headers: { Authorization: `Bearer ${config.token}` },
        });
      } catch {
        throw new Error("Native folder picker is unavailable. Reopen Nanobot and try again.");
      }

      const body = await response.json().catch(() => null) as {
        error?: unknown;
        path?: unknown;
      } | null;
      if (!response.ok) {
        const detail = typeof body?.error === "string" ? body.error : `HTTP ${response.status}`;
        throw new Error(`Native folder picker failed: ${detail}`);
      }
      if (body?.path === null) return null;
      if (typeof body?.path !== "string" || !body.path) {
        throw new Error("Native folder picker returned an invalid path.");
      }
      return body.path;
    },
  };
}

class HostWebSocket {
  binaryType: BinaryType = "blob";
  onclose: ((this: WebSocket, ev: CloseEvent) => unknown) | null = null;
  onerror: ((this: WebSocket, ev: Event) => unknown) | null = null;
  onmessage: ((this: WebSocket, ev: MessageEvent) => unknown) | null = null;
  onopen: ((this: WebSocket, ev: Event) => unknown) | null = null;
  readyState: number = HOST_WS_CONNECTING;
  readonly url: string;

  private id: string | null = null;
  private readonly queued: string[] = [];
  private readonly unsubscribe: () => void;

  constructor(
    private readonly api: HostSocketBridge,
    url: string,
  ) {
    this.url = url;
    this.unsubscribe = api.onSocketEvent((event) => this.handleEvent(event));
    void api.openSocket(url).then(
      (id) => {
        this.id = id;
      },
      () => {
        this.readyState = HOST_WS_CLOSED;
        this.onerror?.call(this as unknown as WebSocket, new Event("error"));
        this.onclose?.call(this as unknown as WebSocket, closeEvent());
        this.unsubscribe();
      },
    );
  }

  close(): void {
    if (this.readyState === HOST_WS_CLOSING || this.readyState === HOST_WS_CLOSED) {
      return;
    }
    this.readyState = HOST_WS_CLOSING;
    if (this.id) {
      void this.api.closeSocket(this.id);
    } else {
      this.readyState = HOST_WS_CLOSED;
      this.unsubscribe();
    }
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    if (typeof data !== "string") {
      throw new Error("Host WebSocket bridge only supports text frames");
    }
    if (this.readyState === HOST_WS_OPEN && this.id) {
      void this.api.sendSocket(this.id, data);
      return;
    }
    this.queued.push(data);
  }

  private handleEvent(event: HostSocketEvent): void {
    if (!this.id || event.id !== this.id) return;
    if (event.type === "open") {
      this.readyState = HOST_WS_OPEN;
      this.onopen?.call(this as unknown as WebSocket, new Event("open"));
      while (this.queued.length > 0 && this.id) {
        const data = this.queued.shift();
        if (data !== undefined) void this.api.sendSocket(this.id, data);
      }
      return;
    }
    if (event.type === "message") {
      this.onmessage?.call(
        this as unknown as WebSocket,
        new MessageEvent("message", { data: event.data }),
      );
      return;
    }
    if (event.type === "error") {
      this.onerror?.call(this as unknown as WebSocket, new Event("error"));
      return;
    }
    this.readyState = HOST_WS_CLOSED;
    this.onclose?.call(
      this as unknown as WebSocket,
      closeEvent(event.code, event.reason),
    );
    this.unsubscribe();
  }
}

function closeEvent(code = 1006, reason = ""): CloseEvent {
  if (typeof CloseEvent !== "undefined") {
    return new CloseEvent("close", { code, reason });
  }
  return new Event("close") as CloseEvent;
}
