import type { GatewayConnection } from "./protocol"

type Environment = Record<string, string | undefined>

export interface DesktopConnectionSource {
  gatewayId: string
  resolve: () => Promise<GatewayConnection>
}

export function desktopConnectionSource(environment: Environment = process.env): DesktopConnectionSource | undefined {
  const rawCommand = environment.NANOBOT_TUI_DESKTOP_RESOLVER
  const rawTarget = environment.NANOBOT_TUI_DESKTOP_TARGET
  if (!rawCommand && !rawTarget) return undefined
  try {
    const command: unknown = JSON.parse(rawCommand || "")
    const target: unknown = JSON.parse(rawTarget || "")
    if (!Array.isArray(command) || command.length < 2
      || !command.every((part): part is string => typeof part === "string" && part.length > 0)
      || !record(target) || typeof target.instanceId !== "string"
      || !uuid(target.instanceId) || typeof target.gatewayId !== "string" || !uuid(target.gatewayId)) throw new Error()
    const gatewayId = target.gatewayId
    const request = JSON.stringify({ instanceId: target.instanceId, gatewayId }) + "\n"
    if (request.length > 8192) throw new Error()
    return { gatewayId, resolve: () => resolveDesktopConnection(command, request, gatewayId) }
  } catch {
    throw new Error("Invalid Desktop terminal launcher configuration")
  }
}

async function resolveDesktopConnection(command: string[], request: string, gatewayId: string): Promise<GatewayConnection> {
  const child = Bun.spawn(command, {
    stdin: "pipe", stdout: "pipe", stderr: "ignore",
  })
  const timer = setTimeout(() => child.kill(), 8_000)
  try {
    child.stdin.write(request)
    child.stdin.end()
    const reader = child.stdout.getReader()
    const chunks: Uint8Array[] = []
    let length = 0
    try {
      for (;;) {
        const next = await reader.read()
        if (next.done) break
        length += next.value.byteLength
        if (length > 8192) throw new Error()
        chunks.push(next.value)
      }
    } finally { reader.releaseLock() }
    if (await child.exited !== 0) throw new Error()
    const value: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"))
    if (!record(value) || value.protocolVersion !== 1 || value.gatewayId !== gatewayId) throw new Error()
    const api = endpoint(value.apiUrl, "http:")
    const ws = endpoint(value.wsUrl, "ws:")
    if (api.host !== ws.host || api.pathname !== "/"
      || !token(value.wsToken) || !token(value.apiToken)) throw new Error()
    ws.searchParams.set("token", value.wsToken)
    ws.searchParams.set("client_id", `tui-${process.pid}`)
    ws.searchParams.set("terminal_protocol", "1")
    ws.searchParams.set("terminal_instance", gatewayId)
    return { wsUrl: ws.toString(), apiUrl: api.origin, apiToken: value.apiToken }
  } catch {
    // The helper response contains secrets; never expose its raw errors/output.
    throw new Error("Selected Desktop is unavailable or incompatible; reconnect from the terminal")
  } finally {
    clearTimeout(timer)
    child.kill()
    await child.exited
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
function uuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu.test(value)
}
function token(value: unknown): value is string {
  return typeof value === "string" && /^[\x21-\x7e]{1,2048}$/u.test(value)
}
function endpoint(value: unknown, protocol: string): URL {
  if (typeof value !== "string" || /[\s\\\x00-\x1f\x7f]/u.test(value)) throw new Error()
  const url = new URL(value)
  if (url.protocol !== protocol || !["127.0.0.1", "[::1]"].includes(url.hostname)
    || url.port === "0" || url.username || url.password || url.search || url.hash) throw new Error()
  return url
}
