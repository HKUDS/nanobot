import type { GatewayConnection, GatewayHealthStatus } from "./types"
import { isRecord } from "./validation"

export class GatewayConnectionError extends Error {
  constructor(message: string, readonly retryable: boolean) {
    super(message)
    this.name = "GatewayConnectionError"
  }
}

/** Resolve fresh short-lived credentials once the local gateway is reachable. */
export async function fetchGatewayConnection(
  bootstrapUrl: string,
  bootstrapSecret: string,
  apiUrl: string,
  clientId: string,
): Promise<GatewayConnection> {
  const headers: Record<string, string> = {}
  if (bootstrapSecret) {
    if (/^[\x20-\x7e]*$/.test(bootstrapSecret)) {
      headers["X-Nanobot-Auth"] = bootstrapSecret
    } else {
      headers["X-Nanobot-Auth-Encoded"] = btoa(
        Array.from(new TextEncoder().encode(bootstrapSecret), (byte) => String.fromCharCode(byte)).join(""),
      )
    }
  }
  const response = await fetch(bootstrapUrl, {
    headers,
  })
  if (!response.ok) {
    const retryable = response.status === 408 || response.status === 429 || response.status >= 500
    throw new GatewayConnectionError(
      `gateway bootstrap failed: HTTP ${response.status}`,
      retryable,
    )
  }
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new GatewayConnectionError("gateway bootstrap response is invalid", false)
  }
  if (!isRecord(payload)) {
    throw new GatewayConnectionError("gateway bootstrap response is invalid", false)
  }
  if (typeof payload.ws_url !== "string" || !payload.ws_url.trim()) {
    throw new GatewayConnectionError("gateway bootstrap response is missing ws_url", false)
  }
  let wsUrl: URL
  try {
    wsUrl = new URL(payload.ws_url)
  } catch {
    throw new GatewayConnectionError("gateway bootstrap response has an invalid ws_url", false)
  }
  if (wsUrl.protocol !== "ws:" && wsUrl.protocol !== "wss:") {
    throw new GatewayConnectionError("gateway bootstrap response has an invalid ws_url", false)
  }
  if (typeof payload.token === "string" && payload.token) {
    wsUrl.searchParams.append("token", payload.token)
  }
  wsUrl.searchParams.append("client_id", clientId)
  return {
    wsUrl: wsUrl.toString(),
    apiUrl,
    apiToken: typeof payload.api_token === "string" ? payload.api_token : "",
  }
}

/** Read gateway readiness without sending bootstrap or API credentials. */
export async function fetchGatewayHealth(
  healthUrl: string,
  timeoutMs = 400,
): Promise<GatewayHealthStatus> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(healthUrl, { signal: controller.signal })
    if (response.status !== 200 && response.status !== 503) return "unreachable"
    const payload: unknown = await response.json()
    if (!isRecord(payload)) return "unreachable"
    if (
      response.status === 503
      && payload.status === "degraded"
      && payload.ready === false
      && payload.process === "alive"
    ) return "degraded"
    if (response.status === 200 && payload.status === "ok" && payload.ready !== false) {
      return "ready"
    }
    return "unreachable"
  } catch {
    return "unreachable"
  } finally {
    clearTimeout(timer)
  }
}

/** Return only the authority users can act on, never credentials or an authenticated path. */
export function connectionEndpoint(value: string | undefined): string {
  if (!value) return "local gateway"
  try {
    return new URL(value).host || "local gateway"
  } catch {
    return "local gateway"
  }
}

/** Reduce arbitrary fetch/WebSocket errors to a small set of credential-safe reasons. */
export function sanitizeConnectionFailure(error: unknown): string {
  const signals: string[] = []
  const seen = new Set<unknown>()
  const collect = (value: unknown): void => {
    if (value === null || value === undefined || seen.has(value)) return
    if (typeof value === "object") seen.add(value)
    if (typeof value === "string") {
      signals.push(value)
      return
    }
    if (value instanceof Error) {
      signals.push(value.name, value.message)
      collect(value.cause)
      if (value instanceof AggregateError) {
        for (const nested of value.errors) collect(nested)
      }
      return
    }
    if (!isRecord(value)) return
    if (typeof value.code === "string") signals.push(value.code)
    collect(value.cause)
    if (Array.isArray(value.errors)) {
      for (const nested of value.errors) collect(nested)
    }
  }
  collect(error)
  const signal = signals.join(" ")
  if (/ECONNREFUSED|connection refused/iu.test(signal)) return "connection refused"
  if (/ETIMEDOUT|timed? out|timeout/iu.test(signal)) return "connection timed out"
  if (/ENOTFOUND|EAI_AGAIN|name not resolved|host not found/iu.test(signal)) {
    return "host not found"
  }
  if (/certificate|TLS|SSL/iu.test(signal)) return "secure connection failed"
  const bootstrapStatus = signal.match(/gateway bootstrap failed:\s*HTTP\s*(\d{3})/iu)
  if (bootstrapStatus?.[1]) return `gateway bootstrap failed: HTTP ${bootstrapStatus[1]}`
  if (/bootstrap response is missing ws_url/iu.test(signal)) {
    return "gateway bootstrap response is missing ws_url"
  }
  if (/bootstrap response (?:has an invalid ws_url|is invalid)/iu.test(signal)) {
    return "gateway bootstrap response is invalid"
  }
  if (/gateway is still starting/iu.test(signal)) return "gateway is still starting"
  if (/fetch failed|failed to fetch|network error/iu.test(signal)) return "network request failed"
  return "connection failed"
}
