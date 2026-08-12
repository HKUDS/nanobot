import { describe, expect, test } from "bun:test"

import { NanobotClient, type InboundEvent } from "./protocol"

class FakeSocket {
  static readonly OPEN = 1
  readonly sent: string[] = []
  readyState = FakeSocket.OPEN
  private readonly listeners = new Map<string, Array<(event: { data?: string }) => void>>()

  addEventListener(name: string, listener: (event: { data?: string }) => void): void {
    const listeners = this.listeners.get(name) || []
    listeners.push(listener)
    this.listeners.set(name, listeners)
  }

  close(): void {
    this.readyState = 3
  }

  send(value: string): void {
    this.sent.push(value)
  }

  emit(name: string, event: { data?: string } = {}): void {
    for (const listener of this.listeners.get(name) || []) listener(event)
  }
}

describe("gateway protocol", () => {
  test("represents lifecycle frames without browser state", () => {
    const events: InboundEvent[] = [
      { event: "delta", chat_id: "one", text: "hello" },
      { event: "stream_end", chat_id: "one", resuming: false },
      { event: "turn_end", chat_id: "one", latency_ms: 12 },
    ]
    expect(events.map((event) => event.event)).toEqual(["delta", "stream_end", "turn_end"])
  })

  test("attaches and sends turns through the gateway envelope", () => {
    const original = globalThis.WebSocket
    let socket: FakeSocket | undefined
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: class extends FakeSocket {
        constructor() {
          super()
          socket = this
        }
      },
    })

    try {
      const events: InboundEvent[] = []
      const client = new NanobotClient({
        url: "ws://nanobot.test/ws",
        chatId: "terminal",
        onEvent: (event) => events.push(event),
        onStatus: () => undefined,
      })
      client.connect()
      if (!socket) throw new Error("socket was not created")
      socket.emit("message", {
        data: JSON.stringify({ event: "ready", chat_id: "", client_id: "client" }),
      })
      socket.emit("message", { data: JSON.stringify({ event: "attached", chat_id: "terminal" }) })
      client.send("hello")

      const outbound = socket.sent.map((value) => JSON.parse(value) as Record<string, unknown>)
      expect(outbound[0]).toEqual({ type: "attach", chat_id: "terminal" })
      expect(outbound[1]?.type).toBe("message")
      expect(outbound[1]?.chat_id).toBe("terminal")
      expect(outbound[1]?.content).toBe("hello")
      expect(events.map((event) => event.event)).toEqual(["ready", "attached"])
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("rejects malformed gateway events", () => {
    const original = globalThis.WebSocket
    let socket: FakeSocket | undefined
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: class extends FakeSocket {
        constructor() {
          super()
          socket = this
        }
      },
    })

    try {
      const statuses: string[] = []
      const client = new NanobotClient({
        url: "ws://nanobot.test/ws",
        onEvent: () => undefined,
        onStatus: (status, detail) => statuses.push(`${status}:${detail || ""}`),
      })
      client.connect()
      if (!socket) throw new Error("socket was not created")
      socket.emit("message", { data: "[]" })
      expect(statuses).toContain("error:gateway sent an invalid event")
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })
})
