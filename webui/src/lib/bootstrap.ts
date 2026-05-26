import type { BootstrapResponse } from "./types";

const SECRET_STORAGE_KEY = "nanobot-webui.bootstrap-secret";

/** Read a previously saved bootstrap secret from localStorage. */
export function loadSavedSecret(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(SECRET_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

/** Persist the bootstrap secret so page reloads don't re-prompt. */
export function saveSecret(secret: string): void {
  try {
    window.localStorage.setItem(SECRET_STORAGE_KEY, secret);
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}

/** Clear the saved bootstrap secret (sign out). */
export function clearSavedSecret(): void {
  try {
    window.localStorage.removeItem(SECRET_STORAGE_KEY);
  } catch {
    // ignore
  }
}

/**
 * Fetch a short-lived token + the WebSocket path from the gateway's
 * ``/webui/bootstrap`` endpoint.
 */
export async function fetchBootstrap(
  baseUrl: string = "",
  secret: string = "",
): Promise<BootstrapResponse> {
  const headers: Record<string, string> = {};
  if (secret) {
    headers["X-Nanobot-Auth"] = secret;
  }
  const res = await fetch(`${baseUrl}/webui/bootstrap`, {
    method: "GET",
    credentials: "same-origin",
    headers,
  });
  if (!res.ok) {
    throw new Error(`bootstrap failed: HTTP ${res.status}`);
  }
  const body = (await res.json()) as BootstrapResponse;
  if (!body.token || !body.ws_path) {
    throw new Error("bootstrap response missing token or ws_path");
  }
  return body;
}

/** Derive a WebSocket URL from the current window location and the server-provided path.
 *
 * Keeps the path segment exactly as the server registered it: the root ``/``
 * stays ``/`` and non-root paths are not given an extra trailing slash. This
 * matters because some WS servers dispatch handshakes based on the literal
 * path, not a normalised form.
 */
export function deriveWsUrl(wsPath: string, token: string): string {
  const path = wsPath && wsPath.startsWith("/") ? wsPath : `/${wsPath || ""}`;
  const query = `?token=${encodeURIComponent(token)}`;
  if (typeof window === "undefined") {
    return `ws://127.0.0.1:8765${path}${query}`;
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return `${scheme}://${host}${path}${query}`;
}
