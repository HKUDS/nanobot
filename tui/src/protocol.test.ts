import { describe, expect, test } from "bun:test"

import {
  NanobotClient,
  GatewayConnectionError,
  connectionEndpoint,
  fetchAvailableSkills,
  fetchGatewayConnection,
  fetchGatewayHealth,
  fetchHistory,
  fetchMentionCandidates,
  fetchRuntimeControls,
  fetchSessionContext,
  fetchSessions,
  fetchSlashCommands,
  sanitizeConnectionFailure,
  type ConnectionStatus,
  type ConnectionStatusInfo,
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

async function waitUntil(predicate: () => boolean, timeout = 1_000): Promise<void> {
  const deadline = Date.now() + timeout
  while (!predicate() && Date.now() < deadline) await Bun.sleep(2)
  if (!predicate()) throw new Error(`condition was not met within ${timeout}ms`)
}

describe("gateway protocol", () => {
  test("bootstraps fresh websocket and API credentials", async () => {
    const original = globalThis.fetch
    let headers: Headers | undefined
    globalThis.fetch = (async (_input: string | URL | Request, init?: RequestInit) => {
      headers = new Headers(init?.headers)
      return new Response(JSON.stringify({
        ws_url: "ws://nanobot.test/ws?mode=local",
        token: "socket token",
        api_token: "api-token",
      }))
    }) as typeof fetch

    try {
      const connection = await fetchGatewayConnection(
        "http://nanobot.test/webui/bootstrap",
        "bootstrap-secret",
        "http://nanobot.test",
        "tui-42",
      )
      expect(headers?.get("X-Nanobot-Auth")).toBe("bootstrap-secret")
      expect(connection).toEqual({
        wsUrl: "ws://nanobot.test/ws?mode=local&token=socket+token&client_id=tui-42",
        apiUrl: "http://nanobot.test",
        apiToken: "api-token",
      })
    } finally {
      globalThis.fetch = original
    }
  })

  test("classifies gateway health without sending credentials", async () => {
    const original = globalThis.fetch
    const requests: Array<{ url: string; headers: Headers }> = []
    const responses = [
      new Response(JSON.stringify({
        status: "degraded",
        process: "alive",
        ready: false,
        websocket: "unavailable",
      }), { status: 503 }),
      new Response(JSON.stringify({
        status: "ok",
        process: "alive",
        ready: true,
        websocket: "running",
      })),
      new Response("not json"),
    ]
    globalThis.fetch = ((input: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(input), headers: new Headers(init?.headers) })
      return Promise.resolve(responses.shift() || new Response("missing", { status: 500 }))
    }) as typeof fetch

    try {
      const healthUrl = "http://127.0.0.1:18790/health"
      expect(await fetchGatewayHealth(healthUrl)).toBe("degraded")
      expect(await fetchGatewayHealth(healthUrl)).toBe("ready")
      expect(await fetchGatewayHealth(healthUrl)).toBe("unreachable")
      expect(requests.map(({ url }) => url)).toEqual([healthUrl, healthUrl, healthUrl])
      expect(requests.every(({ headers }) => [...headers].length === 0)).toBe(true)
    } finally {
      globalThis.fetch = original
    }
  })

  test("rejects malformed bootstrap responses without retrying", async () => {
    const original = globalThis.fetch
    globalThis.fetch = (() => Promise.resolve(new Response("not json"))) as unknown as typeof fetch

    try {
      await expect(fetchGatewayConnection(
        "http://nanobot.test/webui/bootstrap",
        "bootstrap-secret",
        "http://nanobot.test",
        "tui-42",
      )).rejects.toMatchObject({
        message: "gateway bootstrap response is invalid",
        retryable: false,
      })
    } finally {
      globalThis.fetch = original
    }
  })

  test("retries an API request only once after reauthentication", async () => {
    const original = globalThis.fetch
    const authorizations: Array<string | null> = []
    let reauthenticationRequests = 0
    globalThis.fetch = ((_input: string | URL | Request, init?: RequestInit) => {
      authorizations.push(new Headers(init?.headers).get("Authorization"))
      return Promise.resolve(new Response("Unauthorized", { status: 401 }))
    }) as typeof fetch

    try {
      await expect(fetchSlashCommands(
        "http://nanobot.test",
        "expired-api-token",
        async (rejectedApiToken) => {
          expect(rejectedApiToken).toBe("expired-api-token")
          reauthenticationRequests += 1
          return { apiUrl: "http://nanobot.test", apiToken: "fresh-api-token" }
        },
      )).rejects.toMatchObject({ message: "command request failed: HTTP 401" })
      expect(reauthenticationRequests).toBe(1)
      expect(authorizations).toEqual([
        "Bearer expired-api-token",
        "Bearer fresh-api-token",
      ])
    } finally {
      globalThis.fetch = original
    }
  })

  test("waits for bootstrap before opening the websocket", async () => {
    const original = globalThis.WebSocket
    let resolveConnection: ((value: {
      wsUrl: string
      apiUrl: string
      apiToken: string
    }) => void) | undefined
    let requestedUrl = ""
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: class extends FakeSocket {
        constructor(url: string) {
          super()
          requestedUrl = url
        }
      },
    })

    try {
      const connections: string[] = []
      let healthChecks = 0
      const client = new NanobotClient({
        resolveConnection: () => new Promise((resolve) => { resolveConnection = resolve }),
        checkHealth: async () => {
          healthChecks += 1
          return "ready"
        },
        onConnection: (connection) => connections.push(connection.apiToken),
        onEvent: () => undefined,
        onStatus: () => undefined,
      })
      client.connect()
      await Bun.sleep(1)
      expect(requestedUrl).toBe("")
      resolveConnection?.({
        wsUrl: "ws://nanobot.test/ws?token=fresh",
        apiUrl: "http://nanobot.test",
        apiToken: "fresh-api-token",
      })
      await Bun.sleep(1)
      expect(requestedUrl).toBe("ws://nanobot.test/ws?token=fresh")
      expect(connections).toEqual(["fresh-api-token"])
      expect(healthChecks).toBe(0)
      client.close()
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("retries bootstrap while the local gateway starts", async () => {
    const original = globalThis.WebSocket
    let attempts = 0
    let requestedUrl = ""
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: class extends FakeSocket {
        constructor(url: string) {
          super()
          requestedUrl = url
        }
      },
    })

    try {
      const client = new NanobotClient({
        resolveConnection: async () => {
          attempts += 1
          if (attempts === 1) throw new Error("gateway is still starting")
          return {
            wsUrl: "ws://nanobot.test/ws?token=second",
            apiUrl: "http://nanobot.test",
            apiToken: "second-api-token",
          }
        },
        reconnectDelayMs: 1,
        onEvent: () => undefined,
        onStatus: () => undefined,
      })
      client.connect()
      for (let index = 0; index < 20 && !requestedUrl; index += 1) await Bun.sleep(2)
      expect(attempts).toBe(2)
      expect(requestedUrl).toBe("ws://nanobot.test/ws?token=second")
      client.close()
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("escalates a refused bootstrap with safe endpoint and retry diagnostics", async () => {
    const original = globalThis.fetch
    const bootstrapUrl = "http://bootstrap-user:bootstrap-pass@127.0.0.1:8769"
      + "/webui/bootstrap?token=socket-secret"
    const bootstrapSecret = "bootstrap-secret"
    const statuses: Array<{
      status: ConnectionStatus
      detail?: string
      info?: ConnectionStatusInfo
    }> = []
    const refused = new TypeError(
      `fetch failed for ${bootstrapUrl}&api_token=api-secret`,
      {
        cause: Object.assign(new Error("connect ECONNREFUSED 127.0.0.1:8769"), {
          code: "ECONNREFUSED",
        }),
      },
    )
    globalThis.fetch = (() => Promise.reject(refused)) as unknown as typeof fetch
    const client = new NanobotClient({
      resolveConnection: () => fetchGatewayConnection(
        bootstrapUrl,
        bootstrapSecret,
        "http://127.0.0.1:8769",
        "tui-42",
      ),
      targetEndpoint: connectionEndpoint(bootstrapUrl),
      checkHealth: async () => "degraded",
      startupFailureDelayMs: 8,
      reconnectDelayMs: 100,
      onEvent: () => undefined,
      onStatus: (status, detail, info) => statuses.push({ status, detail, info }),
    })

    try {
      client.connect()
      await waitUntil(() => statuses.some(({ status }) => status === "unavailable"))
      const failure = [...statuses].reverse().find(({ status }) => status === "unavailable")

      expect(statuses[0]?.status).toBe("starting")
      expect(failure?.detail).toBe("connection refused")
      expect(failure?.info).toMatchObject({
        endpoint: "127.0.0.1:8769",
        attempt: 1,
        elapsedMs: expect.any(Number),
        health: "degraded",
      })
      const visible = JSON.stringify(statuses)
      expect(visible).not.toContain("bootstrap-user")
      expect(visible).not.toContain("bootstrap-pass")
      expect(visible).not.toContain(bootstrapSecret)
      expect(visible).not.toContain("socket-secret")
      expect(visible).not.toContain("api-secret")
      expect(visible).not.toContain("/webui/bootstrap")
    } finally {
      client.close()
      globalThis.fetch = original
    }
  })

  test("recovers after sustained bootstrap failures without hiding the outage", async () => {
    const original = globalThis.WebSocket
    const sockets: FakeSocket[] = []
    let available = false
    let attempts = 0
    const statuses: ConnectionStatus[] = []
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: class extends FakeSocket {
        constructor() {
          super()
          sockets.push(this)
        }
      },
    })
    const client = new NanobotClient({
      resolveConnection: async () => {
        attempts += 1
        if (!available) {
          throw Object.assign(new Error("connect ECONNREFUSED"), { code: "ECONNREFUSED" })
        }
        return {
          wsUrl: "ws://127.0.0.1:8769/ws?token=fresh",
          apiUrl: "http://127.0.0.1:8769",
          apiToken: "fresh-api-token",
        }
      },
      targetEndpoint: "127.0.0.1:8769",
      checkHealth: async () => available ? "ready" : "degraded",
      startupFailureDelayMs: 8,
      reconnectDelayMs: 2,
      startupRetryMaxDelayMs: 2,
      onEvent: () => undefined,
      onStatus: (status) => statuses.push(status),
    })

    try {
      client.connect()
      await waitUntil(() => statuses.includes("unavailable"))
      available = true
      await waitUntil(() => sockets.length === 1)
      sockets[0]?.emit("open")
      await waitUntil(() => statuses.at(-1) === "connected")

      expect(attempts).toBeGreaterThan(1)
      expect(statuses.indexOf("starting")).toBeLessThan(statuses.indexOf("unavailable"))
      expect(statuses.indexOf("unavailable")).toBeLessThan(statuses.lastIndexOf("connected"))
    } finally {
      client.close()
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("sanitizes arbitrary connection errors and authenticated URLs", () => {
    const authenticated = "wss://user:password@127.0.0.1:8769/ws"
      + "?token=socket-secret&api_token=api-secret"
    const unknown = new Error(`could not reach ${authenticated}`)
    const refused = Object.assign(new Error(`ECONNREFUSED ${authenticated}`), {
      code: "ECONNREFUSED",
    })

    expect(connectionEndpoint(authenticated)).toBe("127.0.0.1:8769")
    expect(sanitizeConnectionFailure(unknown)).toBe("connection failed")
    expect(sanitizeConnectionFailure(refused)).toBe("connection refused")
    expect(sanitizeConnectionFailure(unknown)).not.toContain("socket-secret")
  })

  test("reports a permanent bootstrap rejection without retrying", async () => {
    let attempts = 0
    const statuses: string[] = []
    const client = new NanobotClient({
      resolveConnection: async () => {
        attempts += 1
        throw new GatewayConnectionError("gateway bootstrap failed: HTTP 401", false)
      },
      reconnectDelayMs: 1,
      onEvent: () => undefined,
      onStatus: (status, detail) => statuses.push(`${status}:${detail || ""}`),
    })
    client.connect()
    await Bun.sleep(5)
    expect(attempts).toBe(1)
    expect(statuses.at(-1)).toBe("error:gateway bootstrap failed: HTTP 401")
    client.close()
  })

  test("represents lifecycle frames without browser state", () => {
    const events: InboundEvent[] = [
      {
        event: "user_message",
        chat_id: "one",
        text: "question",
        turn_id: "turn-one",
        active_turn_id: "turn-one",
        starts_turn: true,
        media_urls: [{ kind: "file", url: "/api/media/sig/file", name: "report.pdf" }],
      },
      { event: "delta", chat_id: "one", text: "hello" },
      { event: "stream_end", chat_id: "one", resuming: false },
      { event: "turn_end", chat_id: "one", latency_ms: 12 },
    ]
    expect(events.map((event) => event.event)).toEqual([
      "user_message",
      "delta",
      "stream_end",
      "turn_end",
    ])
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
        initialWorkspaceScope: {
          project_path: "/tmp/project",
          access_mode: "restricted",
        },
        onEvent: (event) => events.push(event),
        onStatus: () => undefined,
      })
      client.connect()
      if (!socket) throw new Error("socket was not created")
      socket.emit("message", {
        data: JSON.stringify({ event: "ready", chat_id: "", client_id: "client" }),
      })
      socket.emit("message", {
        data: JSON.stringify({
          event: "attached",
          chat_id: "terminal",
          model_preset: "Deep Research",
        }),
      })
      client.send("hello", {
        media: [{ data_url: "data:image/png;base64,AAAA", name: "clipboard-image-1.png" }],
        cliApps: [{ name: "github" }],
        sessionMentions: [{ name: "plan", session_key: "websocket:plan" }],
        userShell: true,
      })
      client.attach("other-chat")
      client.newChat()
      client.forkChat("terminal", 3, "Alternative")
      client.setWorkspaceScope({
        project_path: "/tmp/project",
        access_mode: "restricted",
      })

      const outbound = socket.sent.map((value) => JSON.parse(value) as Record<string, unknown>)
      expect(outbound[0]).toEqual({ type: "attach", chat_id: "terminal" })
      expect(outbound[1]?.type).toBe("message")
      expect(outbound[1]?.chat_id).toBe("terminal")
      expect(outbound[1]?.content).toBe("hello")
      expect(outbound[1]?.user_shell).toBe(true)
      expect(outbound[1]?.media).toEqual([
        { data_url: "data:image/png;base64,AAAA", name: "clipboard-image-1.png" },
      ])
      expect(outbound[1]?.cli_apps).toEqual([{ name: "github" }])
      expect(outbound[1]?.session_mentions).toEqual([
        { name: "plan", session_key: "websocket:plan" },
      ])
      expect(outbound[2]).toEqual({ type: "attach", chat_id: "other-chat" })
      expect(outbound[3]).toEqual({ type: "new_chat" })
      expect(outbound[4]).toEqual({
        type: "fork_chat",
        source_chat_id: "terminal",
        before_user_index: 3,
        title: "Alternative",
      })
      expect(outbound[5]).toEqual({
        type: "set_workspace_scope",
        chat_id: "terminal",
        workspace_scope: {
          project_path: "/tmp/project",
          access_mode: "restricted",
        },
      })
      expect(events.map((event) => event.event)).toEqual(["ready", "attached"])
      expect(events[1]).toEqual({
        event: "attached",
        chat_id: "terminal",
        model_preset: "Deep Research",
      })
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("starts a fresh chat in the launch workspace", () => {
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
      const client = new NanobotClient({
        url: "ws://nanobot.test/ws",
        initialWorkspaceScope: {
          project_path: "/tmp/launch-project",
          access_mode: "restricted",
        },
        onEvent: () => undefined,
        onStatus: () => undefined,
      })
      client.connect()
      if (!socket) throw new Error("socket was not created")
      socket.emit("message", {
        data: JSON.stringify({ event: "ready", chat_id: "", client_id: "client" }),
      })
      socket.emit("message", {
        data: JSON.stringify({ event: "attached", chat_id: "draft-chat" }),
      })
      // A gateway restart re-sends ready while the TUI keeps the draft chat alive.
      socket.emit("message", {
        data: JSON.stringify({ event: "ready", chat_id: "", client_id: "client" }),
      })
      client.send("hello")

      expect(socket.sent.map((value) => JSON.parse(value))).toEqual([
        {
          type: "new_chat",
          workspace_scope: {
            project_path: "/tmp/launch-project",
            access_mode: "restricted",
          },
        },
        { type: "attach", chat_id: "draft-chat" },
        expect.objectContaining({
          type: "message",
          chat_id: "draft-chat",
          content: "hello",
          workspace_scope: {
            project_path: "/tmp/launch-project",
            access_mode: "restricted",
          },
        }),
      ])
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("loads runtime model and access controls from canonical APIs", async () => {
    const original = globalThis.fetch
    globalThis.fetch = (async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/settings")) return new Response(JSON.stringify({
        model_presets: [
          { name: "Codex", model: "openai-codex/gpt-5.6" },
          { name: "broken" },
        ],
      }))
      return new Response(JSON.stringify({ controls: { can_use_full_access: true } }))
    }) as typeof fetch

    try {
      expect(await fetchRuntimeControls("http://nanobot.test", "secret")).toEqual({
        modelPresets: [{ name: "Codex", model: "openai-codex/gpt-5.6" }],
        canUseFullAccess: true,
      })
    } finally {
      globalThis.fetch = original
    }
  })

  test("keeps model selection available when workspace controls are unavailable", async () => {
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => Promise.resolve(
      String(input).endsWith("/api/settings")
        ? new Response(JSON.stringify({
          model_presets: [{ name: "fast", model: "openai/gpt-5.6" }],
        }))
        : new Response("", { status: 404 }),
    )) as typeof fetch
    try {
      expect(await fetchRuntimeControls("http://nanobot.test", "secret")).toEqual({
        modelPresets: [{ name: "fast", model: "openai/gpt-5.6" }],
        canUseFullAccess: false,
      })
    } finally {
      globalThis.fetch = original
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
          event: "user_message",
          chat_id: "one",
          text: "missing lifecycle",
        }),
      })
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
        data: JSON.stringify({
          event: "user_message",
          chat_id: "one",
          text: "bad media",
          starts_turn: false,
          media_urls: [{ kind: "archive", url: "/api/media/sig/file" }],
        }),
      })
      socket.emit("message", {
        data: JSON.stringify({ event: "attached", chat_id: "one", model_preset: 42 }),
      })
      socket.emit("message", {
        data: JSON.stringify({ event: "turn_end", chat_id: "one", goal_state: [] }),
      })
      socket.emit("message", {
        data: JSON.stringify({ event: "session_updated", chat_id: "one", scope: "metadata" }),
      })
      socket.emit("message", {
        data: JSON.stringify({
          event: "turn_end",
          chat_id: "one",
          goal_state: { active: false, status: "blocked", ui_summary: "Approval required" },
        }),
      })
      socket.emit("message", { data: JSON.stringify({ event: "future_gateway_event" }) })
      socket.emit("message", { data: JSON.stringify({ event: "error", detail: "global failure" }) })
      expect(statuses).toContain("error:gateway sent an invalid event")
      expect(statuses.filter((status) => status.includes("invalid event"))).toHaveLength(9)
      expect(events).toContainEqual({
        event: "session_updated",
        chat_id: "one",
        scope: "metadata",
      })
      expect(events).toContainEqual({ event: "error", detail: "global failure" })
      expect(events).toContainEqual({
        event: "turn_end",
        chat_id: "one",
        goal_state: { active: false, status: "blocked", ui_summary: "Approval required" },
      })
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("receives compaction phases and rejects malformed compaction events", () => {
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
    const events: InboundEvent[] = []
    const statuses: string[] = []
    const client = new NanobotClient({
      url: "ws://nanobot.test/ws",
      onEvent: (event) => events.push(event),
      onStatus: (status, detail) => statuses.push(`${status}:${detail || ""}`),
    })
    try {
      client.connect()
      if (!socket) throw new Error("socket was not created")
      const base = { event: "context_compaction", chat_id: "chat", compaction_id: "compact-1" }
      for (const phase of ["started", "succeeded", "failed", "cancelled"]) {
        socket.emit("message", { data: JSON.stringify({
          ...base, phase,
        }) })
      }
      for (const invalid of [
        { phase: "unknown" },
        { phase: "started", compaction_id: "" },
        { phase: "started", compaction_id: 42 },
        { phase: "started", compaction_id: undefined },
        { phase: "started", chat_id: undefined },
      ]) {
        socket.emit("message", { data: JSON.stringify({ ...base, ...invalid }) })
      }
      expect(events.map((event) => event.event)).toEqual(Array(4).fill("context_compaction"))
      expect(events.map((event) => "phase" in event ? event.phase : null)).toEqual([
        "started", "succeeded", "failed", "cancelled",
      ])
      expect(statuses.filter((status) => status.includes("invalid event"))).toHaveLength(5)
    } finally {
      client.close()
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

  test("validates structured retry and failed turn events", () => {
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
        event: "retry_status",
        chat_id: "chat",
        turn_id: "turn-1",
        state: "waiting",
        attempt: 2,
        max_attempts: 4,
        error_kind: "connection",
        retry_after_s: 3.5,
      }) })
      socket.emit("message", { data: JSON.stringify({
        event: "retry_status",
        chat_id: "chat",
        turn_id: "turn-1",
        state: "cleared",
        attempt: 4,
        max_attempts: 4,
        error_kind: "connection",
      }) })
      socket.emit("message", { data: JSON.stringify({
        event: "turn_end",
        chat_id: "chat",
        turn_id: "turn-1",
        outcome: "failed",
        failure_kind: "model",
        failure_error_kind: "connection",
        failure_attempts: 4,
        failure_message: "Model provider request failed.",
      }) })
      socket.emit("message", { data: JSON.stringify({
        event: "retry_status",
        chat_id: "chat",
        state: "waiting",
        attempt: 0,
        error_kind: "connection",
      }) })
      socket.emit("message", { data: JSON.stringify({
        event: "turn_end",
        chat_id: "chat",
        outcome: "failed",
        failure_kind: "model",
        failure_attempts: 0,
      }) })

      expect(events).toHaveLength(3)
      expect(events[0]?.event).toBe("retry_status")
      expect(events[1]?.event).toBe("retry_status")
      expect(events[2]?.event).toBe("turn_end")
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
      const statuses: Array<{
        status: ConnectionStatus
        detail?: string
        info?: ConnectionStatusInfo
      }> = []
      const client = new NanobotClient({
        url: "ws://nanobot.test/ws",
        reconnectDelayMs: 1,
        onEvent: () => undefined,
        onStatus: (status, detail, info) => statuses.push({ status, detail, info }),
      })
      client.connect()
      sockets[0]?.emit("open")
      sockets[0]?.emit("message", {
        data: JSON.stringify({ event: "ready", chat_id: "", client_id: "client" }),
      })
      sockets[0]?.emit("message", {
        data: JSON.stringify({ event: "attached", chat_id: "generated-chat" }),
      })
      sockets[0]?.emit("close")
      await Bun.sleep(5)

      expect(sockets).toHaveLength(2)
      const reconnecting = [...statuses].reverse().find(
        ({ status }) => status === "reconnecting",
      )
      expect(reconnecting).toMatchObject({
        status: "reconnecting",
        detail: "connection closed",
        info: { endpoint: "nanobot.test", attempt: 1 },
      })
      sockets[1]?.emit("open")
      sockets[1]?.emit("message", {
        data: JSON.stringify({ event: "ready", chat_id: "", client_id: "client-2" }),
      })
      const outbound = sockets[1]?.sent.map((value) => JSON.parse(value)) || []
      expect(outbound).toEqual([{ type: "attach", chat_id: "generated-chat" }])
      expect(statuses.at(-1)?.status).toBe("connected")
      client.close()
    } finally {
      Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: original })
    }
  })

  test("sends stale-safe recovery mutations and validates their response", async () => {
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

      const result = client.updateRecovery("continue", "chat", "recovery-1")
      const request = JSON.parse(socket.sent.at(-1) || "{}") as {
        request_id: string
        action: string
        payload: Record<string, string>
      }
      expect(request).toMatchObject({
        type: "webui_request",
        action: "recovery.continue",
        payload: { chat_id: "chat", recovery_id: "recovery-1" },
      })
      socket.emit("message", { data: JSON.stringify({
        event: "webui_response",
        request_id: request.request_id,
        ok: true,
        result: { status: "resuming", recovery_id: "recovery-1", attempts: 1 },
      }) })
      expect(await result).toEqual({
        status: "resuming",
        recovery_id: "recovery-1",
        attempts: 1,
      })
      expect(statuses).not.toContain("error:gateway sent an invalid event")

      const interrupted = client.updateRecovery("dismiss", "chat", "recovery-2")
      socket.emit("close")
      await expect(interrupted).rejects.toThrow("gateway connection closed")
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
          { role: "user", content: "hello", turnId: "turn-1" },
          {
            role: "user",
            content: "",
            turnId: "turn-image",
            media: [{ kind: "image", url: "/api/media/sig/image", name: "shot.png" }],
          },
          {
            role: "tool",
            kind: "trace",
            content: "read_file",
            traces: ["read_file"],
            toolEvents: [{ phase: "end", call_id: "read-1", name: "read_file" }],
          },
          { role: "assistant", kind: "reasoning", content: "private thought" },
          { role: "assistant", content: "hi", forkIndex: 2 },
        ],
        page: { has_more_before: true, before_cursor: "older-1" },
      })))
    }) as typeof fetch

    try {
      const history = await fetchHistory("http://nanobot.test", "token", "chat", "newer-page")
      expect(history).toEqual({
        messages: [
          { role: "user", content: "hello", turnId: "turn-1" },
          {
            role: "user",
            content: "",
            turnId: "turn-image",
            media: [{ kind: "image", url: "/api/media/sig/image", name: "shot.png" }],
          },
          {
            role: "activity",
            content: "read_file",
            toolEvents: [{ phase: "end", call_id: "read-1", name: "read_file" }],
          },
          { role: "assistant", content: "hi", forkIndex: 2 },
        ],
        hasMoreBefore: true,
        beforeCursor: "older-1",
        userMessageOffset: 0,
      })
      expect(requested).toContain("before=newer-page")
    } finally {
      globalThis.fetch = original
    }
  })

  test("loads compaction history as activity rows", async () => {
    const original = globalThis.fetch
    globalThis.fetch = Object.assign(async () => Response.json({
      messages: [
        { role: "assistant", content: "before" },
        ...["started", "succeeded", "failed", "cancelled"].map((phase) => ({
          role: "assistant",
          kind: "compaction",
          content: "",
          compaction: { id: phase, phase },
        })),
        { role: "assistant", kind: "compaction", content: "invalid", compaction: null },
        {
          role: "assistant", kind: "compaction", content: "invalid",
          compaction: { id: "", phase: "succeeded" },
        },
        {
          role: "assistant", kind: "compaction", content: "invalid",
          compaction: { id: "unknown", phase: "unknown" },
        },
        { role: "assistant", content: "after" },
      ],
    }), { preconnect: original.preconnect })
    try {
      const history = await fetchHistory("http://nanobot.test", "token", "chat")
      expect(history.messages).toEqual([
        { role: "assistant", content: "before", forkIndex: 0 },
        ...(["started", "succeeded", "failed", "cancelled"] as const).map((phase) => ({
          role: "activity" as const, content: "", compaction: { id: phase, phase },
        })),
        { role: "assistant", content: "after", forkIndex: 0 },
      ])
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
      last_usage: {
        prompt_tokens: 1200,
        completion_tokens: 80,
        total_tokens: 1280,
        context_tokens: 1200,
        cached_tokens: 900,
        request_count: 1,
        estimated_tokens: 0,
        generation_ms: 4000,
        measured_completion_tokens: 80,
        ttft_ms: 250,
        timed_requests: 1,
      },
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
        lastUsage: {
          prompt_tokens: 1200,
          completion_tokens: 80,
          total_tokens: 1280,
          context_tokens: 1200,
          cached_tokens: 900,
          request_count: 1,
          estimated_tokens: 0,
          generation_ms: 4000,
          measured_completion_tokens: 80,
          ttft_ms: 250,
          timed_requests: 1,
        },
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

  test("loads only enabled and available skills", async () => {
    const original = globalThis.fetch
    let authorization = ""
    globalThis.fetch = ((_: string | URL | Request, init?: RequestInit) => {
      authorization = new Headers(init?.headers).get("Authorization") || ""
      return Promise.resolve(new Response(JSON.stringify({
        skills: [
          {
            name: "verify",
            description: "Verify public behavior",
            source: "builtin",
            enabled: true,
            available: true,
          },
          {
            name: "disabled",
            description: "Disabled skill",
            source: "workspace",
            enabled: false,
            available: true,
          },
          {
            name: "unavailable",
            description: "Missing dependency",
            source: "builtin",
            enabled: true,
            available: false,
          },
          { name: "my skill", enabled: true, available: true },
          { name: "技能", enabled: true, available: true },
          { enabled: true, available: true },
        ],
      })))
    }) as typeof fetch

    try {
      expect(await fetchAvailableSkills("http://nanobot.test", "secret")).toEqual([{
        name: "verify",
        description: "Verify public behavior",
        source: "builtin",
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
            model_preset: "Deep Research",
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
        modelPreset: "Deep Research",
        pinned: true,
        archived: false,
      }])
    } finally {
      globalThis.fetch = original
    }
  })

  test("combines installed tools and saved sessions in one mention namespace", async () => {
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      const url = String(input)
      if (url.includes("cli-apps")) {
        return Promise.resolve(new Response(JSON.stringify({
          apps: [{ name: "github", display_name: "GitHub", description: "Repository tools", installed: true }],
        })))
      }
      if (url.includes("mcp-presets")) {
        return Promise.resolve(new Response(JSON.stringify({
          presets: [{
            name: "linear",
            display_name: "Linear",
            description: "Issue tracker",
            installed: true,
            configured: true,
          }],
        })))
      }
      if (url.includes("sidebar-state")) return Promise.resolve(new Response("{}"))
      return Promise.resolve(new Response(JSON.stringify({
        sessions: [{ key: "websocket:plan", title: "Release plan", preview: "Ship it" }],
      })))
    }) as typeof fetch

    try {
      expect(await fetchMentionCandidates("http://nanobot.test", "secret")).toEqual([
        {
          kind: "cli",
          name: "github",
          displayName: "GitHub",
          description: "Repository tools",
        },
        {
          kind: "mcp",
          name: "linear",
          displayName: "Linear",
          description: "Issue tracker",
        },
        {
          kind: "session",
          name: "Release-plan",
          displayName: "Release plan",
          description: "Ship it",
          session: {
            name: "Release-plan",
            session_key: "websocket:plan",
            title: "Release plan",
          },
        },
      ])
    } finally {
      globalThis.fetch = original
    }
  })
})
