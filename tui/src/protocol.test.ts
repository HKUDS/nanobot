import { describe, expect, test } from "bun:test"

import {
  NanobotClient,
  fetchHistory,
  fetchSessionContext,
  fetchSessions,
  fetchSlashCommands,
  type InboundEvent,
} from "./protocol"

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
      client.attach("other-chat")
      client.newChat()

      const outbound = socket.sent.map((value) => JSON.parse(value) as Record<string, unknown>)
      expect(outbound[0]).toEqual({ type: "attach", chat_id: "terminal" })
      expect(outbound[1]?.type).toBe("message")
      expect(outbound[1]?.chat_id).toBe("terminal")
      expect(outbound[1]?.content).toBe("hello")
      expect(outbound[2]).toEqual({ type: "attach", chat_id: "other-chat" })
      expect(outbound[3]).toEqual({ type: "new_chat" })
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
      socket.emit("message", {
        data: JSON.stringify({ event: "session_updated", chat_id: "one", scope: 42 }),
      })
      socket.emit("message", {
        data: JSON.stringify({ event: "session_updated", chat_id: "one", scope: "metadata" }),
      })
      socket.emit("message", { data: JSON.stringify({ event: "future_gateway_event" }) })
      socket.emit("message", { data: JSON.stringify({ event: "error", detail: "global failure" }) })
      expect(statuses).toContain("error:gateway sent an invalid event")
      expect(statuses.filter((status) => status.includes("invalid event"))).toHaveLength(5)
      expect(events).toContainEqual({
        event: "session_updated",
        chat_id: "one",
        scope: "metadata",
      })
      expect(events).toContainEqual({ event: "error", detail: "global failure" })
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("validates nested unified diff payloads at the websocket boundary", () => {
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
      const statuses: string[] = []
      const client = new NanobotClient({
        url: "ws://nanobot.test/ws",
        onEvent: (event) => events.push(event),
        onStatus: (status, detail) => statuses.push(`${status}:${detail || ""}`),
      })
      client.connect()
      if (!socket) throw new Error("socket was not created")
      socket.emit("message", { data: JSON.stringify({
        event: "file_edit",
        chat_id: "chat",
        edits: [{
          call_id: "edit-1",
          tool: "edit_file",
          path: "src/app.ts",
          status: "done",
          added: 1,
          deleted: 1,
          diff: { format: "unified", truncated: false, text: "--- a\n+++ b" },
        }],
      }) })
      socket.emit("message", { data: JSON.stringify({
        event: "file_edit",
        chat_id: "chat",
        edits: [{ diff: { format: "unified", text: ["not", "a", "string"] } }],
      }) })

      expect(events).toHaveLength(1)
      expect(events[0]?.event).toBe("file_edit")
      expect(statuses).toContain("error:gateway sent an invalid event")
      client.close()
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
    let requested = ""
    globalThis.fetch = ((input: string | URL | Request) => {
      requested = String(input)
      return Promise.resolve(new Response(JSON.stringify({
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
        page: { has_more_before: true, before_cursor: "older-1" },
      })))
    }) as typeof fetch

    try {
      const history = await fetchHistory("http://nanobot.test", "token", "chat", "newer-page")
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
        hasMoreBefore: true,
        beforeCursor: "older-1",
      })
      expect(requested).toContain("before=newer-page")
    } finally {
      globalThis.fetch = original
    }
  })

  test("loads the explainable session context projection", async () => {
    const original = globalThis.fetch
    globalThis.fetch = (() => Promise.resolve(new Response(JSON.stringify({
      total_messages: 24,
      archived_messages: 16,
      replay_messages: 10,
      estimated_replay_tokens: 2048,
      estimated_summary_tokens: 128,
      estimated_session_tokens: 2176,
      archived_summary: "Older work was compacted.",
      archived_summary_at: "2026-08-13T10:00:00Z",
    })))) as unknown as typeof fetch

    try {
      expect(await fetchSessionContext("http://nanobot.test", "secret", "chat")).toEqual({
        totalMessages: 24,
        archivedMessages: 16,
        replayMessages: 10,
        estimatedReplayTokens: 2048,
        estimatedSummaryTokens: 128,
        estimatedSessionTokens: 2176,
        archivedSummary: "Older work was compacted.",
        archivedSummaryAt: "2026-08-13T10:00:00Z",
      })
    } finally {
      globalThis.fetch = original
    }
  })

  test("loads the gateway-owned slash command catalog", async () => {
    const original = globalThis.fetch
    let authorization = ""
    globalThis.fetch = ((_: string | URL | Request, init?: RequestInit) => {
      authorization = new Headers(init?.headers).get("Authorization") || ""
      return Promise.resolve(new Response(JSON.stringify({
        commands: [
          {
            command: "/history",
            title: "History",
            description: "Show recent messages",
            arg_hint: "[n]",
            accepts_args: true,
            lifecycle: "side_channel",
          },
          { title: "invalid" },
        ],
      })))
    }) as typeof fetch

    try {
      expect(await fetchSlashCommands("http://nanobot.test", "secret")).toEqual([{
        command: "/history",
        title: "History",
        description: "Show recent messages",
        argHint: "[n]",
        lifecycle: "side_channel",
        acceptsArgs: true,
      }])
      expect(authorization).toBe("Bearer secret")
    } finally {
      globalThis.fetch = original
    }
  })

  test("drops slash commands with unknown lifecycle metadata", async () => {
    const original = globalThis.fetch
    globalThis.fetch = (() => Promise.resolve(new Response(JSON.stringify({
      commands: [{
        command: "/future",
        title: "Future",
        description: "Unknown lifecycle",
        lifecycle: "future_mode",
      }],
    })))) as unknown as typeof fetch

    try {
      expect(await fetchSlashCommands("http://nanobot.test", "secret")).toEqual([])
    } finally {
      globalThis.fetch = original
    }
  })

  test("loads and normalizes WebUI sessions", async () => {
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({
          pinned_keys: ["websocket:chat-1"],
          archived_keys: [],
          title_overrides: { "websocket:chat-1": "Pinned release" },
        })))
      }
      return Promise.resolve(new Response(JSON.stringify({
        sessions: [
          {
            key: "websocket:chat-1",
            title: "Release plan",
            preview: "Prepare the release",
            created_at: "2026-08-12T10:00:00Z",
            updated_at: "2026-08-13T10:00:00Z",
            run_started_at: 123,
          },
          { key: "cli:direct", title: "Not a WebUI session" },
          { key: 42 },
        ],
      })))
    }) as typeof fetch

    try {
      expect(await fetchSessions("http://nanobot.test", "secret")).toEqual([{
        chatId: "chat-1",
        title: "Pinned release",
        preview: "Prepare the release",
        createdAt: "2026-08-12T10:00:00Z",
        updatedAt: "2026-08-13T10:00:00Z",
        runStartedAt: 123,
        pinned: true,
        archived: false,
      }])
    } finally {
      globalThis.fetch = original
    }
  })
})
