import type { BootstrapResponse } from "./types";
import { fetchWithTimeout } from "./http";

const SECRET_STORAGE_KEY = "nanobot-webui.bootstrap-secret";
const URL_SECRET_PARAM = "bootstrapSecret";

export class BootstrapAuthRequiredError extends Error {
  constructor(message = "bootstrap authentication required") {
    super(message);
    this.name = "BootstrapAuthRequiredError";
  }
}

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

export function consumeUrlBootstrapSecret(): string {
  if (typeof window === "undefined") return "";
  const hash = window.location.hash || "";
  const queryStart = hash.indexOf("?");
  if (queryStart < 0) return "";

  const path = hash.slice(0, queryStart) || "#/";
  const query = hash.slice(queryStart + 1);
  const params = new URLSearchParams(query);
  const secret = params.get(URL_SECRET_PARAM)?.trim() || "";
  if (!secret) return "";

  params.delete(URL_SECRET_PARAM);
  const nextQuery = params.toString();
  const nextHash = `${path}${nextQuery ? `?${nextQuery}` : ""}`;
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${nextHash}`,
  );
  return secret;
}

/**
 * Fetch a short-lived token + the WebSocket path from the gateway's
 * ``/webui/bootstrap`` endpoint.
 */
export async function fetchBootstrap(
  baseUrl: string = "",
  secret: string = "",
  timeoutMs?: number,
): Promise<BootstrapResponse> {
  const headers: Record<string, string> = {};
  if (secret) {
    headers["X-Nanobot-Auth"] = secret;
  }
  const res = await fetchWithTimeout(`${baseUrl}/webui/bootstrap`, {
    method: "GET",
    credentials: "same-origin",
    headers,
  }, timeoutMs);
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      throw new BootstrapAuthRequiredError(`bootstrap failed: HTTP ${res.status}`);
    }
    throw new Error(`bootstrap failed: HTTP ${res.status}`);
  }
  const body = (await res.json()) as BootstrapResponse;
  if (!body.token || !body.ws_path) {
    throw new Error("bootstrap response missing token or ws_path");
  }
  if (!body.api_token) {
    throw new BootstrapAuthRequiredError(
      "bootstrap authentication required: missing api_token",
    );
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
export function deriveWsUrl(
  wsPath: string,
  token: string,
  wsUrl?: string | null,
): string {
  const query = `?token=${encodeURIComponent(token)}`;
  const path = wsPath && wsPath.startsWith("/") ? wsPath : `/${wsPath || ""}`;
  if (typeof window !== "undefined" && window.location.port === "5173") {
    const host = window.location.hostname.includes(":")
      ? `[${window.location.hostname}]`
      : window.location.hostname;
    return `ws://${host}:8765${path}${query}`;
  }
  if (wsUrl && /^(wss?|nanobot-host):\/\//i.test(wsUrl)) {
    const join = wsUrl.includes("?") ? "&" : "?";
    return `${wsUrl}${join}token=${encodeURIComponent(token)}`;
  }
  if (typeof window === "undefined") {
    return `ws://127.0.0.1:8765${path}${query}`;
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return `${scheme}://${host}${path}${query}`;
}
