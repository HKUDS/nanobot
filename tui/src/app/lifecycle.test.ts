import { afterEach, describe, expect, test } from "bun:test"
import { CliRenderEvents, TextareaRenderable, TextRenderable } from "@opentui/core"
import { MockTreeSitterClient, createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"
import { NanobotTui } from "./app"
import type { Transcript } from "../rendering/transcript"
import { options, client, mount, waitUntil, occurrences } from "./test-support"

describe("NanobotTui lifecycle", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  const createRenderer = (rendererOptions: Parameters<typeof createTestRenderer>[0]) => (
    createTestRenderer(rendererOptions)
  )
  test("reconciles active state from attach hydration after reconnect", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const state = () => (app as unknown as { activeTurn: boolean }).activeTurn
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "delta", chat_id: "chat", text: "stale partial response" })
    expect(state()).toBe(true)

    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    await setup.flush()
    expect(state()).toBe(false)
    const restored = setup.captureCharFrame()
    expect(restored).not.toContain("stale partial response")
    expect(occurrences(restored, ">_  nanobot")).toBe(1)
    app.accept({
      event: "goal_status",
      chat_id: "chat",
      status: "running",
      started_at: Date.now() / 1000 - 2,
    })
    expect(state()).toBe(true)
    app.accept({ event: "goal_status", chat_id: "chat", status: "idle" })
    expect(state()).toBe(false)
  })

  test("shows actionable connection states without implementation details", async () => {
    setup = await createRenderer({ width: 100, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const ui = app as unknown as {
      status: TextRenderable
      handleStatus(
        status: "starting" | "connecting" | "connected" | "reconnecting" | "unavailable" | "error",
        detail?: string,
        info?: {
          endpoint: string
          attempt: number
          elapsedMs: number
          health?: "ready" | "degraded" | "unreachable"
        },
      ): void
    }

    ui.handleStatus("starting", undefined, {
      endpoint: "127.0.0.1:8769",
      attempt: 1,
      elapsedMs: 0,
    })
    expect(ui.status.plainText).toBe("Getting ready…")

    ui.handleStatus("connecting")
    expect(ui.status.plainText).toBe("Getting ready…")

    ui.handleStatus("connected")
    expect(ui.status.plainText).toBe("Getting ready…")

    ui.handleStatus("error", "gateway sent an invalid event")
    expect(ui.status.plainText).toBe("Getting ready…")
    expect(ui.status.plainText).not.toContain("Unable")

    ui.handleStatus("reconnecting", "connection closed", {
      endpoint: "127.0.0.1:8769",
      attempt: 2,
      elapsedMs: 800,
    })
    expect(ui.status.plainText).toBe("Resuming…")

    ui.handleStatus("reconnecting", "connection closed", {
      endpoint: "127.0.0.1:8769",
      attempt: 2,
      elapsedMs: 900,
      health: "degraded",
    })
    expect(ui.status.plainText).toBe("Resuming…")

    ui.handleStatus("unavailable", "connection refused", {
      endpoint: "127.0.0.1:8769",
      attempt: 7,
      elapsedMs: 3_200,
      health: "degraded",
    })
    expect(ui.status.plainText).toBe("Still getting ready…")
    expect(ui.status.plainText).not.toContain("Unable")

    ui.handleStatus("unavailable", "connection refused", {
      endpoint: "127.0.0.1:8769",
      attempt: 8,
      elapsedMs: 3_500,
      health: "unreachable",
    })
    expect(ui.status.plainText).toBe("Nanobot is taking longer to respond…")
    expect(ui.status.plainText).not.toContain("Unable")

    ui.handleStatus("error", "gateway bootstrap failed: HTTP 401", {
      endpoint: "127.0.0.1:8769",
      attempt: 9,
      elapsedMs: 3_800,
    })
    expect(ui.status.plainText).toBe("Nanobot unavailable. Restart nanobot.")
    expect(ui.status.plainText).not.toContain("gateway")
    expect(ui.status.plainText).not.toContain("127.0.0.1")
    expect(ui.status.plainText).not.toContain("HTTP")
    expect(ui.status.plainText).not.toContain("attempt")
  })

  test.each([
    ["succeeded", "Conversation compacted"],
    ["cancelled", "Conversation compaction cancelled"],
  ] as const)("updates idle compaction in place to %s", async (phase, copy) => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    const ui = app as unknown as {
      activeTurn: boolean
      transcript: Transcript
      composer: TextareaRenderable
    }
    ui.composer.setText("unfinished draft")
    const event = { event: "context_compaction", chat_id: "chat", compaction_id: "idle" } as const
    app.accept({ ...event, phase: "started" })
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Compacting conversation…")
    const rows = ui.transcript.root.getChildren()
    app.accept({ ...event, phase })
    app.accept({ ...event, phase })
    app.accept({ ...event, phase: "started" })
    app.accept({ ...event, chat_id: "another-chat", compaction_id: "other", phase: "failed" })
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(occurrences(frame, copy)).toBe(1)
    expect(frame).not.toContain("Compacting conversation")
    expect(frame).not.toContain("Could not compact")
    expect(ui.transcript.root.getChildren()).toEqual(rows)
    expect(ui.activeTurn).toBe(false)
    expect(ui.composer.plainText).toBe("unfinished draft")
  })

  test("keeps compaction separate from progress and streamed answers", async () => {
    setup = await createRenderer({ width: 80, height: 30, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "delta", chat_id: "chat", text: "Answer before " })
    app.accept({ event: "message", chat_id: "chat", text: "First step", kind: "progress" })
    const event = { event: "context_compaction", chat_id: "chat", compaction_id: "capacity" } as const
    app.accept({ ...event, phase: "started" })
    app.accept({ event: "message", chat_id: "chat", text: "Second step", kind: "progress" })
    app.accept({ ...event, phase: "succeeded" })
    app.accept({ event: "delta", chat_id: "chat", text: "and after compaction" })
    expect((app as unknown as { activeTurn: boolean }).activeTurn).toBe(true)
    app.accept({ event: "stream_end", chat_id: "chat" })
    app.accept({ event: "turn_end", chat_id: "chat" })
    await setup.flush()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("Answer before and after compaction")
    expect(frame.indexOf("First step")).toBeLessThan(frame.indexOf("Conversation compacted"))
    expect(frame.indexOf("Conversation compacted")).toBeLessThan(frame.indexOf("Second step"))
    expect(occurrences(frame, "Conversation compacted")).toBe(1)
  })

  test("preserves compaction rows through pagination, theming, and session reset", async () => {
    setup = await createRenderer({ width: 80, height: 28, screenMode: "alternate-screen" })
    const app = mount(setup)
    const ui = app as unknown as {
      transcript: Transcript
      palette: { error: string }
    }
    ui.transcript.history([
      { role: "activity", content: "", compaction: { id: "recent", phase: "succeeded" } },
      { role: "assistant", content: "Recent answer" },
    ])
    await setup.flush()
    await ui.transcript.prependHistory([
      { role: "assistant", content: "Earlier answer" },
      { role: "activity", content: "", compaction: { id: "older", phase: "failed" } },
      { role: "activity", content: "", compaction: { id: "recent", phase: "started" } },
    ])
    await setup.flush()
    ui.transcript.scrollToEdge("top")
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(occurrences(frame, "Conversation compacted")).toBe(1)
    expect(frame).not.toContain("Compacting conversation")
    expect(frame).toContain("Earlier answer")
    expect(frame.indexOf("Earlier answer")).toBeLessThan(frame.indexOf("Could not compact conversation"))
    expect(frame).toContain("Recent answer")
    expect(frame.indexOf("Could not compact conversation")).toBeLessThan(frame.indexOf("Recent answer"))
    setup.renderer.emit(CliRenderEvents.THEME_MODE, "light")
    await setup.flush()
    const failure = ui.transcript.root.getChildren()
      .flatMap((row) => row.getChildren())
      .find((child) => child instanceof TextRenderable && child.plainText.includes("Could not compact"))
    expect(failure).toBeInstanceOf(TextRenderable)
    expect((failure as TextRenderable).fg.toInts().slice(0, 3)).toEqual([
      1, 3, 5,
    ].map((offset) => Number.parseInt(ui.palette.error.slice(offset, offset + 2), 16)))
    ui.transcript.reset({ workspace: "workspace", version: "test" })
    app.accept({ event: "context_compaction", chat_id: "chat", compaction_id: "recent", phase: "started" })
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Compacting conversation…")
    expect(setup.captureCharFrame()).not.toContain("Conversation compacted")
  })

  test("deduplicates compaction history against events queued during hydration", async () => {
    setup = await createRenderer({ width: 80, height: 22, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let resolveFetch: (value: Response) => void = () => undefined
    globalThis.fetch = (() => new Promise<Response>((resolve) => {
      resolveFetch = resolve
    })) as unknown as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "token", chatId: "chat" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    try {
      app.accept({ event: "attached", chat_id: "chat" })
      const event = { event: "context_compaction", chat_id: "chat", compaction_id: "idle" } as const
      app.accept({ ...event, phase: "started" })
      app.accept({ ...event, phase: "succeeded" })
      resolveFetch(Response.json({
        schemaVersion: 3, projection: "events",
        events: [{ event: "context_compaction", chat_id: "chat", compaction_id: "idle", phase: "succeeded" }],
      }))
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
      await setup.renderOnce()
      const frame = setup.captureCharFrame()
      expect(occurrences(frame, "Conversation compacted")).toBe(1)
      expect(frame).not.toContain("Compacting conversation")
      expect((app as unknown as { activeTurn: boolean }).activeTurn).toBe(false)
    } finally {
      globalThis.fetch = original
    }
  })

  test("replays events after asynchronous history hydration", async () => {
    setup = await createRenderer({ width: 80, height: 22, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let resolveFetch: (value: Response) => void = () => undefined
    globalThis.fetch = (() => new Promise<Response>((resolve) => {
      resolveFetch = resolve
    })) as unknown as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "token", chatId: "chat" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )

    try {
      app.accept({ event: "attached", chat_id: "chat" })
      app.accept({ event: "delta", chat_id: "chat", text: "live after reconnect" })
      expect((app as unknown as { activeTurn: boolean }).activeTurn).toBe(false)
      resolveFetch(new Response(JSON.stringify({
        schemaVersion: 3, projection: "events",
        events: [{ event: "stream_end", chat_id: "chat", text: "persisted before reconnect" }],
        page: { has_more_before: false },
      })))
      await Bun.sleep(5)
      await setup.flush()
      const frame = setup.captureCharFrame()

      expect(frame.indexOf("persisted before reconnect")).toBeLessThan(
        frame.indexOf("live after reconnect"),
      )
      expect((app as unknown as { activeTurn: boolean }).activeTurn).toBe(true)
      app.accept({ event: "turn_end", chat_id: "chat" })
    } finally {
      globalThis.fetch = original
    }
  })

  test("blocks submission until reconnect history is hydrated", async () => {
    const sent: string[] = []
    setup = await createRenderer({ width: 80, height: 22, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let request = 0
    let resolveReconnect: (value: Response) => void = () => undefined
    globalThis.fetch = (() => {
      request += 1
      if (request === 1) {
        return Promise.resolve(new Response(JSON.stringify({
          schemaVersion: 3, projection: "events",
        events: [{ event: "stream_end", chat_id: "chat", text: "initial history" }],
          page: { has_more_before: false },
        })))
      }
      return new Promise<Response>((resolve) => {
        resolveReconnect = resolve
      })
    }) as unknown as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "token", chatId: "chat" },
      client(sent),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as {
      composer: TextareaRenderable
      ready: boolean
      status: TextRenderable
    }
    const composer = ui.composer

    try {
      app.accept({ event: "attached", chat_id: "chat" })
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
      app.accept({ event: "attached", chat_id: "chat" })
      composer.setText("sent during reconnect")
      composer.submit()
      await waitUntil(() => ui.status.plainText.includes("Not sent"))

      expect(sent).toEqual([])
      expect(composer.plainText).toBe("sent during reconnect")
      expect(ui.status.plainText).toContain("Not sent.")
      expect(ui.status.plainText).toContain("Press Enter to retry when ready.")

      resolveReconnect(new Response(JSON.stringify({
        schemaVersion: 3, projection: "events",
        events: [{ event: "stream_end", chat_id: "chat", text: "restored history" }],
        page: { has_more_before: false },
      })))
      await waitUntil(() => ui.ready)
      expect(ui.status.plainText).toBe("Not sent. Press Enter to retry.")
      composer.submit()
      await waitUntil(() => sent.length === 1)
      await setup.flush()
      const frame = setup.captureCharFrame()

      expect(sent).toEqual(["sent during reconnect"])
      expect(frame.indexOf("restored history")).toBeLessThan(frame.indexOf("sent during reconnect"))
    } finally {
      globalThis.fetch = original
    }
  })

  test("preserves drafts while a reconnected socket waits to attach", async () => {
    const sent: string[] = []
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup, sent)
    const composer = (app as unknown as { composer: TextareaRenderable }).composer
    const connection = app as unknown as {
      ready: boolean
      submitPending: boolean
      handleStatus(
        status: "reconnecting" | "connected",
        detail?: string,
        info?: { endpoint: string; attempt: number; elapsedMs: number },
      ): void
    }

    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => connection.ready)
    connection.handleStatus("reconnecting", "connection closed", {
      endpoint: "127.0.0.1:8769",
      attempt: 1,
      elapsedMs: 0,
    })
    connection.handleStatus("connected")
    composer.setText("draft before attach")
    composer.submit()
    await waitUntil(() => !connection.submitPending)
    composer.submit()
    await waitUntil(() => !connection.submitPending)

    expect(sent).toEqual([])
    expect(composer.plainText).toBe("draft before attach")

    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => connection.ready)
    expect(sent).toEqual([])
    composer.submit()
    await waitUntil(() => sent.length === 1)
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(5)

    expect(sent).toEqual(["draft before attach"])
  })

  test("destroys the renderer and transport together", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    let closed = false
    const exited: string[] = []
    const transport = client()
    transport.close = () => { closed = true }
    const app = NanobotTui.mount(
      setup.renderer,
      {
        ...options,
        chatId: "original-chat",
        onExit: (chatId) => {
          expect(setup?.renderer.isDestroyed).toBe(true)
          exited.push(chatId)
        },
      },
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )

    app.stop()
    app.stop()

    expect(closed).toBe(true)
    expect(setup.renderer.isDestroyed).toBe(true)
    expect(exited).toEqual(["chat"])
  })

  test("exits after Ctrl+C input dispatch completes on an idle empty composer", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    let closed = false
    const transport = client()
    transport.close = () => { closed = true }
    NanobotTui.mount(
      setup.renderer,
      options,
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )

    setup.mockInput.pressCtrlC()

    expect(closed).toBe(false)
    expect(setup.renderer.isDestroyed).toBe(false)
    await waitUntil(() => closed)
    expect(setup.renderer.isDestroyed).toBe(true)
  })

  test("accepts the exit command before the gateway connection is ready", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    let closed = false
    const transport = client()
    transport.close = () => { closed = true }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const composer = (app as unknown as { composer: TextareaRenderable }).composer

    composer.setText("exit")
    composer.submit()
    await waitUntil(() => closed)

    expect(setup.renderer.isDestroyed).toBe(true)
  })

  test("discovers and runs the local /exit command", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const sent: string[] = []
    let closed = false
    const transport = client(sent)
    transport.close = () => { closed = true }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as {
      composer: TextareaRenderable
      commandMenu: { visible: boolean }
    }

    await setup.mockInput.typeText("/exit")
    await setup.flush()
    expect(ui.commandMenu.visible).toBe(true)
    expect(setup.captureCharFrame()).toContain("/exit")

    expect(ui.composer.plainText).toBe("/exit")
    ui.composer.submit()
    await waitUntil(() => closed)

    expect(sent).toEqual([])
    expect(setup.renderer.isDestroyed).toBe(true)
  })

  test("detaches without sending a message or reporting a normal exit", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const sent: string[] = []
    const detached: string[] = []
    const exited: string[] = []
    let closed = false
    const transport = client(sent)
    transport.close = () => { closed = true }
    const app = NanobotTui.mount(
      setup.renderer,
      {
        ...options,
        onDetach: (chatId) => { if (chatId) detached.push(chatId) },
        onExit: (chatId) => { exited.push(chatId) },
      },
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as {
      composer: TextareaRenderable
      commandMenu: { visible: boolean }
    }

    await setup.mockInput.typeText("/detach")
    await setup.flush()
    expect(ui.commandMenu.visible).toBe(true)
    expect(setup.captureCharFrame()).toContain("/detach")

    ui.composer.submit()
    await waitUntil(() => closed)

    expect(sent).toEqual([])
    expect(detached).toEqual(["chat"])
    expect(exited).toEqual([])
    expect(setup.renderer.isDestroyed).toBe(true)
  })

  test("detaches before the gateway assigns a chat ID", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    let detached = false
    const transport = { ...client(), activeChatId: "" }
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, onDetach: (chatId) => {
        expect(chatId).toBeUndefined()
        detached = true
      } },
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const composer = (app as unknown as { composer: TextareaRenderable }).composer

    composer.setText("/detach")
    composer.submit()
    await waitUntil(() => detached)

    expect(setup.renderer.isDestroyed).toBe(true)
  })
})
