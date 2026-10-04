import { afterEach, describe, expect, test } from "bun:test"
import { BoxRenderable, CliRenderEvents, TextareaRenderable, TextRenderable } from "@opentui/core"
import { MockTreeSitterClient, createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"
import { NanobotTui } from "./app"
import { options, client, mount, waitUntil, occurrences } from "./test-support"

describe("NanobotTui transcript", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  const createRenderer = (rendererOptions: Parameters<typeof createTestRenderer>[0]) => (
    createTestRenderer(rendererOptions)
  )
  test("loads earlier transcript pages in place when PageUp reaches the top", async () => {
    setup = await createRenderer({ width: 80, height: 22, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    const requests: string[] = []
    globalThis.fetch = ((input: string | URL | Request) => {
      const url = String(input)
      requests.push(url)
      const older = url.includes("before=older-page")
      return Promise.resolve(new Response(JSON.stringify({
        schemaVersion: 3, projection: "events",
        events: older
          ? [
              { event: "user_message", chat_id: "chat", starts_turn: true, text: "oldest question" },
              { event: "stream_end", chat_id: "chat", text: "oldest answer" },
            ]
          : [
              { event: "user_message", chat_id: "chat", starts_turn: true, text: "recent question" },
              { event: "stream_end", chat_id: "chat", text: "recent answer" },
            ],
        page: older
          ? { has_more_before: false, before_cursor: null }
          : { has_more_before: true, before_cursor: "older-page" },
      })))
    }) as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret", chatId: "chat" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )

    try {
      app.accept({ event: "attached", chat_id: "chat" })
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
      setup.mockInput.pressKey("\u001B[5~")
      await waitUntil(() => requests.length === 2)
      await waitUntil(() => !(app as unknown as { historyLoadingOlder: boolean }).historyLoadingOlder)
      await setup.flush()
      const frame = setup.captureCharFrame()

      expect(frame.indexOf("oldest question")).toBeLessThan(frame.indexOf("recent question"))
      expect(frame.indexOf("oldest answer")).toBeLessThan(frame.indexOf("recent answer"))
      expect((app as unknown as { historyHasMore: boolean }).historyHasMore).toBe(false)

      const composer = (app as unknown as { composer: TextareaRenderable }).composer
      setup.mockInput.pressArrow("up")
      expect(composer.plainText).toBe("recent question")
      setup.mockInput.pressArrow("up")
      expect(composer.plainText).toBe("oldest question")
    } finally {
      globalThis.fetch = original
    }
  })

  test("replaces streamed drafts with canonical stream-end text", async () => {
    setup = await createRenderer({ width: 80, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "delta", chat_id: "chat", text: "draft signed://expired" })
    app.accept({
      event: "stream_end",
      chat_id: "chat",
      text: "canonical https://nanobot.test/signed/current",
      resuming: true,
      merge_next: true,
    })
    app.accept({ event: "delta", chat_id: "chat", text: " tail" })
    app.accept({
      event: "stream_end",
      chat_id: "chat",
      text: "final https://nanobot.test/signed/current tail",
    })
    app.accept({ event: "turn_end", chat_id: "chat" })
    await setup.flush()
    const frame = setup.captureCharFrame()

    expect(frame).toContain("final https://nanobot.test/signed/current tail")
    expect(frame).not.toContain("canonical https://nanobot.test/signed/current")
    expect(frame).not.toContain("draft signed://expired")
  })

  test("paints the first token immediately and coalesces the rest per frame", async () => {
    setup = await createRenderer({ width: 80, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "delta", chat_id: "chat", text: "first" })
    const transcript = (app as unknown as {
      transcript: {
        live: { markdown: { content: string; streaming: boolean } } | null
      }
    }).transcript
    const markdown = transcript.live?.markdown
    expect(markdown?.content).toBe("first")

    for (let index = 0; index < 1_000; index += 1) {
      app.accept({ event: "delta", chat_id: "chat", text: " token" })
    }
    expect(markdown?.content).toBe("first")

    app.accept({ event: "stream_end", chat_id: "chat" })
    expect(markdown?.content).toBe(`first${" token".repeat(1_000)}`)
    expect(markdown?.streaming).toBe(false)
  })

  test("copies full-screen selections through OSC 52", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    let copied = ""
    setup.renderer.copyToClipboardOSC52 = (text: string) => {
      copied = text
      return true
    }

    await setup.renderOnce()
    app.accept({ event: "delta", chat_id: "chat", text: "selected answer" })
    app.accept({ event: "stream_end", chat_id: "chat" })
    await setup.flush()
    const rows = setup.captureCharFrame().split("\n")
    const y = rows.findIndex((row) => row.includes("selected answer"))
    const x = rows[y]?.indexOf("selected answer") ?? -1
    expect(x).toBeGreaterThanOrEqual(0)
    expect(y).toBeGreaterThanOrEqual(0)

    await setup.mockMouse.drag(x, y, x + "selected answer".length, y)
    expect(setup.renderer.getSelection()?.getSelectedText()).toBe("selected answer")
    setup.mockInput.pressCtrlC()
    await Bun.sleep(10)
    await setup.flush()

    expect(copied).toBe("selected answer")
    expect(setup.renderer.getSelection()).toBeNull()
  })

  test("clears transcript selection when clicking non-content chrome", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const status = (app as unknown as { status: TextRenderable }).status
    app.accept({ event: "delta", chat_id: "chat", text: "selectable answer" })
    app.accept({ event: "stream_end", chat_id: "chat" })
    await setup.flush()

    const rows = setup.captureCharFrame().split("\n")
    const y = rows.findIndex((row) => row.includes("selectable answer"))
    const x = rows[y]?.indexOf("selectable answer") ?? -1
    await setup.mockMouse.drag(x, y, x + "selectable answer".length, y)
    expect(setup.renderer.getSelection()?.getSelectedText()).toBe("selectable answer")

    await setup.mockMouse.click(status.x, status.y)
    expect(setup.renderer.getSelection()).toBeNull()
  })

  test("keeps text input focus when the focusable transcript is clicked", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const ui = app as unknown as {
      composer: TextareaRenderable
      transcript: {
        root: { x: number; y: number; focused: boolean }
      }
    }
    app.accept({ event: "delta", chat_id: "chat", text: "clickable answer" })
    app.accept({ event: "stream_end", chat_id: "chat" })
    await setup.flush()

    await setup.mockMouse.click(ui.transcript.root.x + 1, ui.transcript.root.y + 1)

    expect(ui.composer.focused).toBe(true)
    expect(ui.transcript.root.focused).toBe(false)
  })

  test("animates one stable status line while the agent works", async () => {
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    setup.renderer.emit(CliRenderEvents.THEME_MODE, "dark")
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "reasoning_delta", chat_id: "chat", text: "hidden reasoning" })
    await Bun.sleep(130)
    await setup.renderOnce()
    let frame = setup.captureCharFrame()

    expect(frame).toMatch(/Thinking\s+0s/u)
    expect(frame).not.toMatch(/[◐◓◑◒⠋⠙⠹⠸]/u)
    expect(frame).not.toContain("hidden reasoning")
    const ui = app as unknown as {
      status: {
        content: { chunks: Array<{ fg?: { toInts(): number[] } }> }
        plainText: string
      }
      composer: TextareaRenderable
      composerFrame: BoxRenderable
    }
    const status = ui.status
    expect(status.plainText).toMatch(/^Thinking\s+0s/u)
    expect(ui.composer.placeholder).toBe("Enter send now · Tab send next")
    expect(ui.composerFrame.height).toBe(3)
    const shimmerColors = new Set(
      status.content.chunks
        .slice(0, "Thinking".length)
        .map((chunk) => chunk.fg?.toInts().join(",")),
    )
    expect(shimmerColors.size).toBeGreaterThan(1)
    expect([...shimmerColors].some((value) => value?.startsWith("239,142,48"))).toBe(true)

    app.accept({
      event: "message",
      chat_id: "chat",
      text: "running shell",
      kind: "tool_hint",
      tool_events: [{ phase: "start", name: "exec", arguments: { cmd: "pwd" } }],
    })
    await Bun.sleep(130)
    await setup.renderOnce()
    frame = setup.captureCharFrame()

    expect(frame).toMatch(/Working\s+0s/u)
    expect(frame).not.toMatch(/[◐◓◑◒⠋⠙⠹⠸]/u)
    expect(frame).toContain("› Running  pwd")
    expect(occurrences(frame, "pwd")).toBe(1)
    expect(status.plainText).not.toContain("pwd")
    app.accept({ event: "turn_end", chat_id: "chat" })
    await setup.flush()
    expect(ui.composer.placeholder).toBe("Ask nanobot anything")
  })

  test("updates retry state in place and ends failed turns explicitly", async () => {
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({
      event: "goal_status",
      chat_id: "chat",
      status: "running",
      turn_id: "turn-1",
    })
    const ui = app as unknown as { status: { plainText: string } }

    app.accept({
      event: "retry_status",
      chat_id: "chat",
      turn_id: "turn-1",
      state: "waiting",
      attempt: 1,
      max_attempts: 4,
      error_kind: "connection",
      retry_after_s: 5,
    })
    expect(ui.status.plainText).toMatch(
      /^Could not connect to the model provider · retrying in [45]s · attempt 1\/4/u,
    )

    app.accept({
      event: "retry_status",
      chat_id: "chat",
      turn_id: "turn-1",
      state: "waiting",
      attempt: 2,
      max_attempts: 4,
      error_kind: "connection",
      retry_after_s: 3,
    })
    expect(ui.status.plainText).toContain("attempt 2/4")

    app.accept({
      event: "retry_status",
      chat_id: "chat",
      turn_id: "turn-1",
      state: "cleared",
      attempt: 2,
      max_attempts: 4,
      error_kind: "connection",
    })
    expect(ui.status.plainText).not.toContain("retrying")

    app.accept({
      event: "turn_end",
      chat_id: "chat",
      turn_id: "turn-1",
      outcome: "failed",
      failure_kind: "model",
      failure_error_kind: "connection",
      failure_attempts: 4,
      failure_message: "Unlocalized server failure",
    })
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    const terminalFailure = "Could not connect to the model provider. The request still failed "
      + "on attempt 4, so retries stopped. Check the provider configuration or service status, "
      + "then try again."
    expect(frame).toContain("Could not connect to the model provider.")
    expect(frame.replace(/\s+/gu, " ")).toContain(terminalFailure)
    expect(frame).not.toContain("Unlocalized server failure")
    expect(frame).not.toContain("Last turn failed")
    expect(ui.status.plainText).toBe("Ready")
  })

  test("folds long tool traces without discarding their details", async () => {
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({
      event: "message",
      chat_id: "chat",
      text: "tool progress",
      kind: "tool_hint",
      tool_events: Array.from({ length: 10 }, (_, index) => ({
        phase: "end",
        call_id: `call-${index}`,
        name: `tool_${index}`,
      })),
    })
    await setup.renderOnce()
    let frame = setup.captureCharFrame()

    expect(frame).toContain("7 earlier steps · Ctrl+O expand")
    expect(frame).not.toContain("tool_0")
    expect(frame).toContain("tool_7")
    expect(frame).toContain("tool_9")

    setup.mockInput.pressKey("O", { ctrl: true })
    await setup.renderOnce()
    frame = setup.captureCharFrame()

    expect(frame).not.toContain("earlier steps")
    expect(frame).toContain("tool_0")
    expect(frame).toContain("tool_9")

    app.accept({ event: "turn_end", chat_id: "chat" })
    app.accept({
      event: "message",
      chat_id: "chat",
      text: "second tool group",
      kind: "tool_hint",
      tool_events: Array.from({ length: 8 }, (_, index) => ({
        phase: "end",
        call_id: `later-${index}`,
        name: `later_${index}`,
      })),
    })
    setup.mockInput.pressKey("O", { ctrl: true })
    await setup.renderOnce()
    const activities = [...(app as unknown as {
      transcript: { activities: Set<{ expanded: boolean }> }
    }).transcript.activities]

    expect(activities.map((activity) => activity.expanded)).toEqual([true, true])
    setup.mockInput.pressKey("O", { ctrl: true })
    await setup.renderOnce()
    expect(activities.map((activity) => activity.expanded)).toEqual([true, false])
    app.accept({ event: "turn_end", chat_id: "chat" })
  })

  test("groups consecutive file activity only in the collapsed preview", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({
      event: "message",
      chat_id: "chat",
      text: "file progress",
      kind: "tool_hint",
      tool_events: Array.from({ length: 6 }, (_, index) => ({
        phase: "end" as const,
        call_id: `read-${index}`,
        name: "read_file",
        arguments: { path: `/tmp/nanobot-workspace/src/file-${index}.ts` },
      })),
    })
    await setup.renderOnce()
    let frame = setup.captureCharFrame()

    expect(frame).toContain("6 steps · Ctrl+O expand")
    expect(frame).toContain("✓ Read 6 files")
    expect(frame).not.toContain("src/file-0.ts")

    setup.mockInput.pressKey("O", { ctrl: true })
    await setup.renderOnce()
    frame = setup.captureCharFrame()

    expect(frame).not.toContain("Read 6 files")
    expect(frame).toContain("src/file-0.ts")
    expect(frame).toContain("src/file-5.ts")
  })

  test("supports keyboard transcript navigation without rebuilding the layout", async () => {
    setup = await createRenderer({ width: 64, height: 16, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    for (let index = 0; index < 24; index += 1) {
      app.accept({ event: "delta", chat_id: "chat", text: `answer ${index}` })
      app.accept({ event: "stream_end", chat_id: "chat" })
    }
    await setup.flush()
    const internals = app as unknown as {
      status: { plainText: string }
      transcript: {
        root: {
          scrollTop: number
          scrollHeight: number
          height: number
          verticalScrollBar: { visible: boolean }
        }
      }
    }
    const scroll = internals.transcript.root

    setup.mockInput.pressKey("HOME", { ctrl: true })
    await setup.renderOnce()
    expect(scroll.scrollTop).toBe(0)

    app.accept({ event: "delta", chat_id: "chat", text: "new answer while reading above" })
    app.accept({ event: "stream_end", chat_id: "chat" })
    await setup.renderOnce()
    expect(scroll.scrollTop).toBe(0)
    expect(scroll.verticalScrollBar.visible).toBe(false)
    expect(internals.status.plainText).toContain("Ctrl+End latest")

    setup.mockInput.pressKey("\u001B[6~")
    await setup.renderOnce()
    expect(scroll.scrollTop).toBeGreaterThan(0)

    setup.mockInput.pressKey("END", { ctrl: true })
    await setup.renderOnce()
    expect(scroll.scrollTop).toBeGreaterThanOrEqual(scroll.scrollHeight - scroll.height)
    expect(scroll.verticalScrollBar.visible).toBe(false)
    expect(internals.status.plainText).not.toContain("Ctrl+End latest")

    setup.mockInput.pressKey("HOME", { ctrl: true })
    await waitUntil(() => internals.status.plainText.includes("Ctrl+End latest"))
    expect(scroll.verticalScrollBar.visible).toBe(false)
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    await setup.renderOnce()
    expect(scroll.verticalScrollBar.visible).toBe(false)
    expect(internals.status.plainText).not.toContain("Ctrl+End latest")
  })
})
