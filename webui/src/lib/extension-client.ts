/**
 * Tiny client-side helper for WebUI extension iframes.
 *
 * Extensions call ``nanobotExtension.request(path)`` to read JSON from their
 * own ``/api/extensions/<id>`` namespace. The host performs the authenticated
 * fetch on their behalf; credentials never reach the extension frame.
 */
export function normalizeExtensionRequestPath(extensionId: string, path: string): string {
  const value = path.trim();
  if (!value) return `/api/extensions/${extensionId}`;
  if (value.startsWith("/api/extensions/")) return value;
  const relative = value.startsWith("/") ? value : `/${value}`;
  return `/api/extensions/${extensionId}${relative}`;
}

export interface NanobotExtensionInit {
  id: string;
  name: string;
  description: string;
  entry: string;
  version: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
}

export interface NanobotExtensionResponse<T = unknown> {
  id: string;
  status: number;
  ok: boolean;
  data?: T;
  error?: string;
}

declare global {
  interface Window {
    nanobotExtension?: {
      request: <T = unknown>(path: string) => Promise<NanobotExtensionResponse<T>>;
      init: Promise<NanobotExtensionInit>;
    };
  }
}

let requestCounter = 0;
const pending = new Map<string, {
  resolve: (value: NanobotExtensionResponse) => void;
  reject: (error: Error) => void;
}>();

export function initializeNanobotExtension(): void {
  if (typeof window === "undefined" || window.nanobotExtension) return;

  const init = new Promise<NanobotExtensionInit>((resolve) => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as { type?: string; extension?: NanobotExtensionInit } | null;
      if (data?.type !== "nanobot:extension:init" || !data.extension) return;
      window.removeEventListener("message", onMessage);
      resolve(data.extension);
    };
    window.addEventListener("message", onMessage);
  });

  const request = <T,>(path: string): Promise<NanobotExtensionResponse<T>> => {
    const id = `req_${++requestCounter}`;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve: resolve as (value: NanobotExtensionResponse) => void, reject });
      window.parent.postMessage(
        { source: "nanobot-webui-extension", type: "nanobot:request", id, path },
        window.location.origin,
      );
      // The host always answers; a safety timeout prevents dangling promises.
      window.setTimeout(() => {
        if (pending.delete(id)) {
          reject(new Error(`nanobot extension request timed out: ${path}`));
        }
      }, 20_000);
    });
  };

  const onResponse = (event: MessageEvent) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data as { type?: string; id?: string } | null;
    if (data?.type !== "nanobot:response" || typeof data.id !== "string") return;
    const entry = pending.get(data.id);
    if (!entry) return;
    pending.delete(data.id);
    entry.resolve(data as NanobotExtensionResponse);
  };
  window.addEventListener("message", onResponse);

  window.nanobotExtension = { request, init };
}

// Self-initialize when loaded inside an extension iframe.
if (typeof window !== "undefined" && window.parent !== window) {
  initializeNanobotExtension();
}
