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
  getRuntimeInfo(): Promise<HostRuntimeInfo>;
  restartEngine(): Promise<void>;
  pickFolder(): Promise<string | null>;
  openLogs(): Promise<void>;
  exportDiagnostics(): Promise<string>;
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

declare global {
  interface Window {
    nanobotHost?: NanobotHostApi;
  }
}

export function getHostApi(): NanobotHostApi | null {
  if (typeof window === "undefined") return null;
  return window.nanobotHost ?? null;
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
    pickFolder: api?.pickFolder,
    restartEngine: api?.restartEngine,
    openLogs: api?.openLogs,
    exportDiagnostics: api?.exportDiagnostics,
  };
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
  if (
    !api?.openSocket
    || !api.sendSocket
    || !api.closeSocket
    || !api.onSocketEvent
  ) {
    return null;
  }
  return {
    closeSocket: api.closeSocket,
    onSocketEvent: api.onSocketEvent,
    openSocket: api.openSocket,
    sendSocket: api.sendSocket,
  };
}

class HostWebSocket {
  binaryType: BinaryType = "blob";
  onclose: ((this: WebSocket, ev: CloseEvent) => unknown) | null = null;
  onerror: ((this: WebSocket, ev: Event) => unknown) | null = null;
  onmessage: ((this: WebSocket, ev: MessageEvent) => unknown) | null = null;
  onopen: ((this: WebSocket, ev: Event) => unknown) | null = null;
  readyState: number = WebSocket.CONNECTING;
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
        this.readyState = WebSocket.CLOSED;
        this.onerror?.call(this as unknown as WebSocket, new Event("error"));
        this.onclose?.call(this as unknown as WebSocket, closeEvent());
        this.unsubscribe();
      },
    );
  }

  close(): void {
    if (this.readyState === WebSocket.CLOSING || this.readyState === WebSocket.CLOSED) {
      return;
    }
    this.readyState = WebSocket.CLOSING;
    if (this.id) {
      void this.api.closeSocket(this.id);
    } else {
      this.readyState = WebSocket.CLOSED;
      this.unsubscribe();
    }
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    if (typeof data !== "string") {
      throw new Error("Host WebSocket bridge only supports text frames");
    }
    if (this.readyState === WebSocket.OPEN && this.id) {
      void this.api.sendSocket(this.id, data);
      return;
    }
    this.queued.push(data);
  }

  private handleEvent(event: HostSocketEvent): void {
    if (!this.id || event.id !== this.id) return;
    if (event.type === "open") {
      this.readyState = WebSocket.OPEN;
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
    this.readyState = WebSocket.CLOSED;
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
