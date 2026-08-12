import { describe, expect, test } from "bun:test"

import { NanobotClient, fetchHistory, type InboundEvent } from "./protocol"

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
      const events: InboundEvent[] = []
      const client = new NanobotClient({
        url: "ws://nanobot.test/ws",
        onEvent: (event) => events.push(event),
        onStatus: (status, detail) => statuses.push(`${status}:${detail || ""}`),
      })
      client.connect()
      if (!socket) throw new Error("socket was not created")
      socket.emit("message", { data: "[]" })
      socket.emit("message", { data: JSON.stringify({ event: "delta", chat_id: "one" }) })
      socket.emit("message", {
        data: JSON.stringify({
          event: "message",
          chat_id: "one",
          text: "bad tool",
          tool_events: [{ call_id: 42 }],
        }),
      })
      socket.emit("message", {
        data: JSON.stringify({ event: "stream_end", chat_id: "one", resuming: "yes" }),
      })
      socket.emit("message", { data: JSON.stringify({ event: "future_gateway_event" }) })
      socket.emit("message", { data: JSON.stringify({ event: "error", detail: "global failure" }) })
      expect(statuses).toContain("error:gateway sent an invalid event")
      expect(statuses.filter((status) => status.includes("invalid event"))).toHaveLength(4)
      expect(events).toContainEqual({ event: "error", detail: "global failure" })
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("reattaches the same generated chat after a transient disconnect", async () => {
    const original = globalThis.WebSocket
    const sockets: FakeSocket[] = []
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: class extends FakeSocket {
        constructor() {
          super()
          sockets.push(this)
        }
      },
    })

    try {
      const client = new NanobotClient({
        url: "ws://nanobot.test/ws",
        reconnectDelayMs: 1,
        onEvent: () => undefined,
        onStatus: () => undefined,
      })
      client.connect()
      sockets[0]?.emit("message", {
        data: JSON.stringify({ event: "ready", chat_id: "", client_id: "client" }),
      })
      sockets[0]?.emit("message", {
        data: JSON.stringify({ event: "attached", chat_id: "generated-chat" }),
      })
      sockets[0]?.emit("close")
      await Bun.sleep(5)

      expect(sockets).toHaveLength(2)
      sockets[1]?.emit("message", {
        data: JSON.stringify({ event: "ready", chat_id: "", client_id: "client-2" }),
      })
      const outbound = sockets[1]?.sent.map((value) => JSON.parse(value)) || []
      expect(outbound).toEqual([{ type: "attach", chat_id: "generated-chat" }])
      client.close()
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("reports when the bounded history snapshot omits earlier turns", async () => {
    const original = globalThis.fetch
    globalThis.fetch = (() => Promise.resolve(new Response(JSON.stringify({
      messages: [
        { role: "user", content: "hello" },
        {
          role: "tool",
          kind: "trace",
          content: "read_file",
          traces: ["read_file"],
          toolEvents: [{ phase: "end", call_id: "read-1", name: "read_file" }],
        },
        { role: "assistant", kind: "reasoning", content: "private thought" },
        { role: "assistant", content: "hi" },
      ],
      page: { has_more_before: true },
    })))) as unknown as typeof fetch

    try {
      const history = await fetchHistory("http://nanobot.test", "token", "chat")
      expect(history).toEqual({
        messages: [
          { role: "user", content: "hello" },
          {
            role: "activity",
            content: "read_file",
            toolEvents: [{ phase: "end", call_id: "read-1", name: "read_file" }],
          },
          { role: "assistant", content: "hi" },
        ],
        truncated: true,
      })
    } finally {
      globalThis.fetch = original
    }
  })
})
