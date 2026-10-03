import { describe, expect, test } from "bun:test"
import { desktopConnectionSource } from "./desktop"

const instanceId = "b370a67d-1dbb-4b7c-9b22-c5f72ad8f5f0"
const gatewayId = "a277eeea-a422-4691-aac5-2c7348a95140"
const connection = {
  protocolVersion: 1, gatewayId,
  apiUrl: "http://127.0.0.1:8765", wsUrl: "ws://127.0.0.1:8765/ws",
  wsToken: "test-ws-secret", apiToken: "test-api-secret",
}
function source(value: unknown = connection, exitCode = 0) {
  // This test helper uses synthetic values only. Production passes no tokens in argv.
  const script = `const input = JSON.parse(await Bun.stdin.text());
    if (input.instanceId !== ${JSON.stringify(instanceId)} || input.gatewayId !== ${JSON.stringify(gatewayId)}) process.exit(9);
    process.stdout.write(${JSON.stringify(JSON.stringify(value))}); process.exit(${exitCode});`
  return desktopConnectionSource({
    NANOBOT_TUI_DESKTOP_RESOLVER: JSON.stringify([process.execPath, "-e", script]),
    NANOBOT_TUI_DESKTOP_TARGET: JSON.stringify({ instanceId, gatewayId }),
  })!
}

describe("Desktop credential resolver", () => {
  test("does nothing for a normal Python TUI", () => {
    expect(desktopConnectionSource({})).toBeUndefined()
  })
  test("fails closed for incomplete launcher metadata", () => {
    expect(() => desktopConnectionSource({ NANOBOT_TUI_DESKTOP_TARGET: "{}" })).toThrow("Invalid Desktop")
  })
  test("refreshes through a pipe and pins the websocket to the chosen gateway", async () => {
    const resolver = source()
    for (let refresh = 0; refresh < 2; refresh++) {
      const result = await resolver.resolve()
      const ws = new URL(result.wsUrl)
      expect(ws.searchParams.get("terminal_instance")).toBe(gatewayId)
      expect(ws.searchParams.get("terminal_protocol")).toBe("1")
      expect(ws.searchParams.get("token")).toBe(connection.wsToken)
      expect(result.apiToken).toBe(connection.apiToken)
      expect(result.apiUrl).toBe(connection.apiUrl)
    }
  })
  test("accepts equivalent explicit and implicit HTTP default ports", async () => {
    const result = await source({ ...connection, apiUrl: "http://127.0.0.1:80", wsUrl: "ws://127.0.0.1/ws" }).resolve()
    expect(result.apiUrl).toBe("http://127.0.0.1")
  })
  for (const patch of [
    { protocolVersion: 2 }, { gatewayId: instanceId }, { apiToken: "" },
    { wsToken: "unsafe\nvalue" }, { wsUrl: "ws://external.example:8765/ws" },
    { apiUrl: "http://localhost:8765" }, { wsUrl: "ws://127.0.0.1:8766/ws" },
    { wsUrl: "ws://127.0.0.1:8765/ws?token=unexpected" },
    { apiUrl: "http://user:password@127.0.0.1:8765" },
    { apiUrl: "http://127.0.0.1:0" }, { apiUrl: "http://127.0.0.1:8765/api" },
  ]) {
    test(`rejects untrusted connection fields: ${Object.keys(patch)[0]} ${JSON.stringify(patch)}`, async () => {
      await expect(source({ ...connection, ...patch }).resolve()).rejects.toThrow("Selected Desktop is unavailable")
    })
  }
  test("does not expose malformed, oversized, or failed helper output", async () => {
    for (const resolver of [source("test-secret"), source("x".repeat(9000)), source(connection, 3)]) {
      await expect(resolver.resolve()).rejects.toThrow("Selected Desktop is unavailable")
    }
  })
})
