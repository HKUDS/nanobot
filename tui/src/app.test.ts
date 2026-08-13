import { afterEach, describe, expect, test } from "bun:test"
import { CliRenderEvents, TextareaRenderable } from "@opentui/core"
import {
  MockTreeSitterClient,
  createTestRenderer,
  type TestRendererSetup,
} from "@opentui/core/testing"

import { NanobotTui, type AppOptions } from "./app"
import type { SlashCommand } from "./protocol"

const options: AppOptions = {
  wsUrl: "ws://localhost.invalid/ws",
  apiUrl: "",
  apiToken: "",
  model: "test/model",
  workspace: "/tmp/nanobot-workspace",
  version: "test",
  access: "workspace access",
  theme: "auto",
}

function occurrences(frame: string, value: string): number {
  return frame.split(value).length - 1
}

function contrastRatio(foreground: string, background: string): number {
  const luminance = (color: string) => {
    const channel = (offset: number) => {
      const value = Number.parseInt(color.slice(offset, offset + 2), 16) / 255
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
  }
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
  return ((lighter ?? 0) + 0.05) / ((darker ?? 0) + 0.05)
}

async function waitUntil(predicate: () => boolean, timeout = 1_000): Promise<void> {
  const deadline = Date.now() + timeout
  while (!predicate() && Date.now() < deadline) await Bun.sleep(5)
  if (!predicate()) throw new Error(`condition was not met within ${timeout}ms`)
}

function client(sent: string[] = [], attached: string[] = [], newChats: string[] = []) {
  return {
    activeChatId: "chat",
    connect() {},
    close() {},
    send(content: string) {
      sent.push(content)
      return "turn"
    },
    attach(chatId: string) {
      attached.push(chatId)
    },
    newChat() {
      newChats.push("new")
    },
  }
}

const mount = (setup: TestRendererSetup, sent: string[] = []) => NanobotTui.mount(
  setup.renderer,
  options,
  client(sent),
  new MockTreeSitterClient({ autoResolveTimeout: 0 }),
)

describe("NanobotTui layout", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  const createRenderer = (options: Parameters<typeof createTestRenderer>[0]) => createTestRenderer(options)

  test("reflows a single retained layout across terminal resizes", async () => {
    setup = await createRenderer({
      width: 100,
      height: 30,
      screenMode: "alternate-screen",
      consoleMode: "disabled",
    })
    const app = mount(setup)

    for (const [width, height] of [[100, 30], [56, 18], [118, 36]] as const) {
      setup.resize(width, height)
      await setup.renderOnce()
      const frame = setup.captureCharFrame()

      expect(setup.renderer.width).toBe(width)
      expect(setup.renderer.height).toBe(height)
      expect(occurrences(frame, "Ask nanobot anything")).toBe(1)
      expect(occurrences(frame, "Ready")).toBe(0)
      expect(occurrences(frame, "Connecting…")).toBe(1)
      expect(occurrences(frame, "nanobot  ·  test/model")).toBe(1)
    }

    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "delta", chat_id: "chat", text: "First **answer**." })
    app.accept({ event: "stream_end", chat_id: "chat", resuming: true })
    app.accept({
      event: "message",
      chat_id: "chat",
      text: "read_file(config.json)",
      kind: "tool_hint",
      tool_events: [
        { phase: "start", call_id: "read-1", name: "read_file", arguments: { path: "config.json" } },
        { phase: "end", call_id: "read-1", name: "read_file" },
      ],
    })
    app.accept({ event: "reasoning_delta", chat_id: "chat", text: "private chain of thought" })
    app.accept({ event: "reasoning_end", chat_id: "chat" })
    app.accept({ event: "delta", chat_id: "chat", text: "Second answer." })
    app.accept({ event: "stream_end", chat_id: "chat" })
    app.accept({ event: "turn_end", chat_id: "chat", latency_ms: 1200 })
    await setup.flush()
    const frame = setup.captureCharFrame()

    expect(occurrences(frame, "First **answer**.")).toBe(1)
    expect(occurrences(frame, "Second answer.")).toBe(1)
    expect(frame).toContain("✓ read_file")
    expect(frame).not.toContain("› read_file")
    expect(frame).not.toContain("private chain of thought")
    expect(frame).toContain("Ready · 1.2s")
  })

  test("waits for an IME commit before reading the submitted text", async () => {
    const sent: string[] = []
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup, sent)
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const composer = (app as unknown as { composer: TextareaRenderable }).composer

    composer.setText("你")
    composer.submit()
    setTimeout(() => composer.setText("你好"), 0)
    await waitUntil(() => sent.length > 0)

    expect(sent).toEqual(["你好"])
  })

  test("clears the placeholder on the first typed character", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const composer = (app as unknown as { composer: TextareaRenderable }).composer
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Ask nanobot anything")

    setup.mockInput.typeText("bu")
    await setup.flush()
    const frame = setup.captureCharFrame()

    expect(composer.plainText).toBe("bu")
    expect(composer.placeholder).toBeNull()
    expect(frame).toContain("bu")
    expect(frame).not.toContain("Ask nanobot anything")
    expect(frame).not.toContain("buAsk nanobot anything")

    setup.mockInput.pressBackspace()
    setup.mockInput.pressBackspace()
    await setup.flush()
    expect(composer.placeholder).toBe("Ask nanobot anything")
    expect(setup.captureCharFrame()).toContain("Ask nanobot anything")
  })

  test("recalls submitted prompts without stealing multiline cursor movement", async () => {
    const sent: string[] = []
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup, sent)
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const composer = (app as unknown as { composer: TextareaRenderable }).composer
    for (const [index, value] of ["first prompt", "second prompt"].entries()) {
      composer.setText(value)
      composer.submit()
      await waitUntil(() => sent.length === index + 1)
      app.accept({ event: "turn_end", chat_id: "chat" })
    }

    setup.mockInput.pressArrow("up")
    expect(composer.plainText).toBe("second prompt")
    setup.mockInput.pressArrow("up")
    expect(composer.plainText).toBe("first prompt")
    setup.mockInput.pressArrow("down")
    expect(composer.plainText).toBe("first prompt")
    setup.mockInput.pressArrow("down")
    expect(composer.plainText).toBe("second prompt")
    setup.mockInput.pressArrow("down")
    expect(composer.plainText).toBe("")

    setup.resize(36, 20)
    const wrapped = "这是一段会在狭窄输入框中自动换行而不是显式换行的中文内容"
    composer.setText(wrapped)
    composer.cursorOffset = wrapped.length
    await setup.renderOnce()
    expect(composer.virtualLineCount).toBeGreaterThan(1)

    setup.mockInput.pressArrow("up")
    expect(composer.plainText).toBe(wrapped)
  })

  test("discovers and completes gateway slash commands without sending them", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const sent: string[] = []
    const app = mount(setup, sent)
    const ui = app as unknown as {
      composer: TextareaRenderable
      commandMenu: {
        visible: boolean
        setCommands(commands: SlashCommand[]): void
      }
    }
    ui.commandMenu.setCommands([{
      command: "/history",
      title: "History",
      description: "Show recent messages",
      argHint: "[n]",
      lifecycle: "side_channel",
      acceptsArgs: true,
    }])

    await setup.mockInput.typeText("/h")
    expect(ui.commandMenu.visible).toBe(true)
    setup.mockInput.pressTab()

    expect(ui.composer.plainText).toBe("/history ")
    expect(ui.commandMenu.visible).toBe(false)
    expect(sent).toEqual([])
  })

  test("switches and creates gateway chats without replacing core slash commands", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    globalThis.fetch = (() => Promise.resolve(new Response(JSON.stringify({
      sessions: [
        {
          key: "websocket:chat",
          title: "Current chat",
          preview: "Current work",
          updated_at: "2026-08-13T10:00:00Z",
        },
        {
          key: "websocket:other",
          title: "Release checklist",
          preview: "Prepare stable release",
          updated_at: "2026-08-12T10:00:00Z",
        },
      ],
    })))) as unknown as typeof fetch
    const attached: string[] = []
    const newChats: string[] = []
    const transport = client([], attached, newChats)
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
    }

    try {
      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionMenu.visible)
      expect(ui.composer.placeholder).toBe("Search sessions")

      ui.composer.setText("release")
      ui.composer.submit()
      await waitUntil(() => attached.length === 1)
      expect(attached).toEqual(["other"])

      app.accept({ event: "attached", chat_id: "other" })
      await Bun.sleep(1)
      ui.composer.setText("/new-chat")
      ui.composer.submit()
      await waitUntil(() => newChats.length === 1)
      expect(newChats).toEqual(["new"])
    } finally {
      globalThis.fetch = original
    }
  })

  test("preserves gateway slash lifecycle while local navigation stays in the same menu", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const sent: string[] = []
    const app = mount(setup, sent)
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      commandMenu: {
        setCommands(commands: SlashCommand[]): void
      }
      activeTurn: boolean
    }
    ui.commandMenu.setCommands([{
      command: "/new",
      title: "New chat",
      description: "Reset this chat",
      argHint: "",
      lifecycle: "finalize_active_turn",
      acceptsArgs: false,
    }, {
      command: "/status",
      title: "Status",
      description: "Show status",
      argHint: "",
      lifecycle: "side_channel",
      acceptsArgs: false,
    }])

    app.accept({ event: "goal_status", chat_id: "chat", status: "running" })
    ui.composer.setText("/status")
    ui.composer.submit()
    await waitUntil(() => sent.includes("/status"))
    expect(ui.activeTurn).toBe(true)
    app.accept({
      event: "message",
      chat_id: "chat",
      text: "Runtime healthy",
      turn_id: "turn",
    })
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("Runtime healthy")

    ui.composer.setText("/new")
    ui.composer.submit()
    await waitUntil(() => sent.includes("/new"))
    expect(ui.activeTurn).toBe(false)
    expect(sent).toEqual(["/status", "/new"])
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("/new")
  })

  test("blocks sends and ignores late session results after closing the picker", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let resolveFetch: ((response: Response) => void) | undefined
    globalThis.fetch = (() => new Promise<Response>((resolve) => {
      resolveFetch = resolve
    })) as unknown as typeof fetch
    const sent: string[] = []
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(sent),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
      sessionLoading: boolean
    }

    try {
      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionLoading)
      ui.composer.setText("do not send")
      ui.composer.submit()
      await Bun.sleep(10)
      expect(sent).toEqual([])

      setup.mockInput.pressEscape()
      await Bun.sleep(10)
      resolveFetch?.(new Response(JSON.stringify({ sessions: [] })))
      await Bun.sleep(10)
      expect(ui.sessionMenu.visible).toBe(false)
      expect(ui.composer.plainText).toBe("")
    } finally {
      globalThis.fetch = original
    }
  })

  test("applies a query typed while sessions are still loading", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let resolveFetch: ((response: Response) => void) | undefined
    globalThis.fetch = (() => new Promise<Response>((resolve) => {
      resolveFetch = resolve
    })) as unknown as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
    }

    try {
      ui.composer.setText("/sessions")
      ui.composer.submit()
      await Bun.sleep(10)
      ui.composer.setText("release")
      resolveFetch?.(new Response(JSON.stringify({
        sessions: [
          { key: "websocket:chat", title: "Current chat", preview: "Current work" },
          { key: "websocket:other", title: "Release checklist", preview: "Ship it" },
        ],
      })))
      await waitUntil(() => ui.sessionMenu.visible)
      await setup.flush()
      const frame = setup.captureCharFrame()
      expect(frame).toContain("Release checklist")
      expect(frame).not.toContain("Current chat")
    } finally {
      globalThis.fetch = original
    }
  })

  test("survives rapid narrow resizes with long CJK and code", async () => {
    setup = await createRenderer({ width: 100, height: 30, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({
      event: "delta",
      chat_id: "chat",
      text: [
        "中文、emoji 👨‍💻 and combining text é reflow with the terminal.",
        "https://nanobot.test/a-very-long-unbroken-path-that-must-not-break-the-layout",
        "```ts",
        "const greeting = '你好，nanobot'",
        "```",
      ].join("\n\n"),
    })
    app.accept({ event: "stream_end", chat_id: "chat" })

    for (const [width, height] of [
      [240, 80],
      [42, 12],
      [30, 9],
      [20, 6],
      [12, 4],
      [8, 3],
      [4, 2],
      [84, 24],
      [48, 14],
      [110, 32],
    ] as const) {
      setup.resize(width, height)
      await setup.renderOnce()
      const frame = setup.captureCharFrame()
      expect(setup.renderer.width).toBe(width)
      expect(setup.renderer.height).toBe(height)
      expect(frame).not.toContain("undefined")
      expect(occurrences(frame, "Ask nanobot anything")).toBeLessThanOrEqual(1)
      if (width >= 30 && height >= 9) {
        expect(occurrences(frame, "Ask nanobot anything")).toBe(1)
      }
      expect(occurrences(frame, "nanobot  ·  test/model")).toBe(height >= 14 ? 1 : 0)
    }
  })

  test("inherits the host background after long output fills the viewport", async () => {
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({
      event: "delta",
      chat_id: "chat",
      text: Array.from({ length: 80 }, (_, index) => (
        `### Section ${index + 1}\n中文长回答、**bold** and [link](https://nanobot.test/${index + 1})`
      )).join("\n\n"),
    })
    app.accept({ event: "stream_end", chat_id: "chat" })
    app.accept({ event: "turn_end", chat_id: "chat" })
    await setup.flush()

    const internals = app as unknown as {
      shell: { backgroundColor: { intent: string } }
      composerFrame: { backgroundColor: { intent: string } }
      composer: { backgroundColor: { intent: string } }
    }
    const spans = setup.captureSpans().lines.flatMap((line) => line.spans)

    expect(internals.shell.backgroundColor.intent).toBe("default")
    expect(internals.composerFrame.backgroundColor.intent).toBe("default")
    expect(internals.composer.backgroundColor.intent).toBe("default")
    expect(spans.length).toBeGreaterThan(0)
    expect(spans.every((span) => span.bg.intent === "default")).toBe(true)
  })

  test("rethemes the complete retained interface when the terminal appearance changes", async () => {
    setup = await createRenderer({ width: 80, height: 22, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "delta", chat_id: "chat", text: "# Existing answer" })
    app.accept({ event: "stream_end", chat_id: "chat" })
    app.accept({ event: "message", chat_id: "chat", text: "tool", kind: "tool_hint" })
    await setup.renderOnce()

    const internals = app as unknown as {
      palette: { referenceBackground: string; text: string; border: string }
      shell: { backgroundColor: { intent: string } }
      composer: { backgroundColor: { intent: string }; textColor: { toInts(): number[] } }
      transcript: {
        markdown: Set<{ syntaxStyle: object }>
        frames: Set<{ borderColor: { toInts(): number[] } }>
      }
    }
    const markdown = [...internals.transcript.markdown][0]
    const sessionFrame = [...internals.transcript.frames][0]
    const darkSyntax = markdown?.syntaxStyle

    setup.renderer.emit(CliRenderEvents.THEME_MODE, "light")
    await setup.flush()

    expect(internals.palette).toMatchObject({
      referenceBackground: "#FAFAFA",
      text: "#18181B",
      border: "#D4D4D8",
    })
    expect(internals.shell.backgroundColor.intent).toBe("default")
    expect(internals.composer.backgroundColor.intent).toBe("default")
    expect(internals.composer.textColor.toInts().slice(0, 3)).toEqual([24, 24, 27])
    expect(sessionFrame?.borderColor.toInts().slice(0, 3)).toEqual([212, 212, 216])
    expect(markdown?.syntaxStyle).not.toBe(darkSyntax)
  })

  test("uses asymmetric roles instead of chat bubbles", async () => {
    setup = await createRenderer({ width: 72, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "delta", chat_id: "chat", text: "Agent **answer**" })
    app.accept({ event: "stream_end", chat_id: "chat" })
    app.accept({ event: "turn_end", chat_id: "chat" })
    ;(app as unknown as { transcript: { user(content: string): void } }).transcript.user("User question")
    await setup.flush()

    const frame = setup.captureCharFrame()
    const userLine = frame.split("\n").find((line) => line.includes("User question")) || ""
    const agentLine = frame.split("\n").find((line) => line.includes("Agent **answer**")) || ""
    const headerLine = frame.split("\n").find((line) => line.includes(">_  nanobot")) || ""
    const headerBorder = frame.split("\n").find((line) => line.includes("╭")) || ""

    expect(userLine).toContain("› User question")
    expect(agentLine).toContain("• Agent **answer**")
    expect(userLine).not.toContain("│")
    expect(agentLine).not.toContain("│")
    expect(headerLine).toContain("│")
    expect(headerBorder.trim().length).toBeLessThanOrEqual(62)
  })

  test("keeps footer status and shortcuts visually separated", async () => {
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "turn_end", chat_id: "chat", latency_ms: 1700 })
    await setup.flush()

    const footer = setup.captureCharFrame().split("\n").find((line) => line.includes("Ready · 1.7s")) || ""
    expect(footer).toContain("Ready · 1.7s")
    expect(footer).toContain("enter send")
    expect(footer).not.toContain("1.7senter")

    app.accept({ event: "reasoning_delta", chat_id: "chat", text: "hidden" })
    await Bun.sleep(130)
    await setup.renderOnce()
    const activeFooter = setup.captureCharFrame().split("\n").find((line) => line.includes("Thinking")) || ""
    expect(activeFooter).toContain("ctrl+c stop")
    expect(activeFooter).not.toContain("enter send")
    app.accept({ event: "turn_end", chat_id: "chat" })
  })

  test("keeps an explicit theme stable when the terminal reports another mode", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, theme: "light" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const internals = app as unknown as { palette: { referenceBackground: string } }
    Object.defineProperty(setup.renderer, "themeMode", { configurable: true, value: "dark" })

    await app.start()

    setup.renderer.emit(CliRenderEvents.THEME_MODE, "dark")
    await setup.renderOnce()

    expect(internals.palette.referenceBackground).toBe("#FAFAFA")
  })

  test("waits for automatic terminal detection before connecting or painting", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    let connected = false
    let resolveMode: (mode: "light") => void = () => undefined
    setup.renderer.waitForThemeMode = () => new Promise((resolve) => {
      resolveMode = resolve
    })
    Object.defineProperty(setup.renderer, "themeMode", { configurable: true, value: "light" })
    const transport = client()
    transport.connect = () => { connected = true }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )

    const starting = app.start()
    await Bun.sleep(1)
    expect(connected).toBe(false)

    resolveMode("light")
    await starting
    expect(connected).toBe(true)
    expect((app as unknown as { palette: { referenceBackground: string } }).palette.referenceBackground).toBe("#FAFAFA")
  })

  test("falls back to the dark palette when terminal theme probing has no answer", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    let connected = false
    setup.renderer.waitForThemeMode = async () => null
    Object.defineProperty(setup.renderer, "themeMode", { configurable: true, value: null })
    const transport = client()
    transport.connect = () => { connected = true }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )

    await app.start()

    expect(connected).toBe(true)
    expect((app as unknown as { palette: { referenceBackground: string } }).palette.referenceBackground).toBe("#0E0F11")
  })

  test("keeps semantic colors legible in both terminal appearances", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const internals = app as unknown as {
      palette: Record<string, string> & { referenceBackground: string; faint: string }
    }
    const assertContrast = () => {
      for (const tone of ["text", "muted", "accent", "success", "error", "user", "warm", "cool"]) {
        expect(contrastRatio(internals.palette[tone] ?? "", internals.palette.referenceBackground)).toBeGreaterThanOrEqual(4.5)
      }
      expect(contrastRatio(internals.palette.faint, internals.palette.referenceBackground)).toBeGreaterThanOrEqual(3)
    }

    assertContrast()
    setup.renderer.emit(CliRenderEvents.THEME_MODE, "light")
    assertContrast()
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

  test("animates one stable status line while the agent works", async () => {
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "reasoning_delta", chat_id: "chat", text: "hidden reasoning" })
    await Bun.sleep(130)
    await setup.renderOnce()
    let frame = setup.captureCharFrame()

    expect(frame).toMatch(/[◐◓◑◒] Thinking\s+0s/u)
    expect(frame).not.toContain("hidden reasoning")

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

    expect(frame).toMatch(/[◐◓◑◒] Working\s+0s/u)
    expect(frame).toContain("› exec")
    app.accept({ event: "turn_end", chat_id: "chat" })
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

    expect(frame).toContain("5 earlier steps · Ctrl+O expand")
    expect(frame).not.toContain("tool_0")
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

  test("supports keyboard transcript navigation without rebuilding the layout", async () => {
    setup = await createRenderer({ width: 64, height: 16, screenMode: "alternate-screen" })
    const app = mount(setup)
    for (let index = 0; index < 24; index += 1) {
      app.accept({ event: "delta", chat_id: "chat", text: `answer ${index}` })
      app.accept({ event: "stream_end", chat_id: "chat" })
    }
    await setup.flush()
    const scroll = (app as unknown as {
      transcript: { root: { scrollTop: number; scrollHeight: number; height: number } }
    }).transcript.root

    setup.mockInput.pressKey("HOME", { ctrl: true })
    await setup.renderOnce()
    expect(scroll.scrollTop).toBe(0)

    app.accept({ event: "delta", chat_id: "chat", text: "new answer while reading above" })
    app.accept({ event: "stream_end", chat_id: "chat" })
    await setup.renderOnce()
    expect(scroll.scrollTop).toBe(0)

    setup.mockInput.pressKey("\u001B[6~")
    await setup.renderOnce()
    expect(scroll.scrollTop).toBeGreaterThan(0)

    setup.mockInput.pressKey("END", { ctrl: true })
    await setup.renderOnce()
    expect(scroll.scrollTop).toBeGreaterThanOrEqual(scroll.scrollHeight - scroll.height)
  })

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
        messages: [{ role: "assistant", content: "persisted before reconnect" }],
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
          messages: [{ role: "assistant", content: "initial history" }],
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
    const composer = (app as unknown as { composer: TextareaRenderable }).composer

    try {
      app.accept({ event: "attached", chat_id: "chat" })
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
      app.accept({ event: "attached", chat_id: "chat" })
      composer.setText("sent during reconnect")
      composer.submit()
      await Bun.sleep(5)

      expect(sent).toEqual([])
      expect(composer.plainText).toBe("sent during reconnect")

      resolveReconnect(new Response(JSON.stringify({
        messages: [{ role: "assistant", content: "restored history" }],
        page: { has_more_before: false },
      })))
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
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
      handleStatus(status: "connecting" | "connected", detail?: string): void
    }

    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    connection.handleStatus("connecting", "reconnecting")
    connection.handleStatus("connected")
    composer.setText("draft before attach")
    composer.submit()
    await Bun.sleep(5)

    expect(sent).toEqual([])
    expect(composer.plainText).toBe("draft before attach")

    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    composer.submit()
    await waitUntil(() => sent.length === 1)

    expect(sent).toEqual(["draft before attach"])
  })

  test("destroys the renderer and transport together", async () => {
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

    app.stop()

    expect(closed).toBe(true)
    expect(setup.renderer.isDestroyed).toBe(true)
  })
})

if (process.platform !== "win32") {
  test("restores the terminal after SIGTERM", async () => {
    const child = Bun.spawn(["bun", "src/index.ts"], {
      cwd: import.meta.dir.replace(/\/src$/u, ""),
      env: {
        ...process.env,
        NANOBOT_TUI_WS_URL: "ws://127.0.0.1:9/ws",
        NANOBOT_TUI_API_URL: "",
        NANOBOT_TUI_API_TOKEN: "",
        NANOBOT_TUI_MODEL: "test/model",
        NANOBOT_TUI_WORKSPACE: "/tmp/nanobot-test",
        NANOBOT_TUI_VERSION: "test",
        NANOBOT_TUI_ACCESS: "workspace access",
        NANOBOT_TUI_THEME: "dark",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const decoder = new TextDecoder()
    let output = ""
    const collectOutput = (async () => {
      const reader = child.stdout.getReader()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        output += decoder.decode(value, { stream: true })
      }
      output += decoder.decode()
    })()

    // Slow Intel runners can spend more than 250 ms importing OpenTUI. Wait
    // for terminal setup, which happens after the signal handlers are
    // registered, before exercising shutdown.
    await waitUntil(() => output.includes("\x1b[?1049h"), 5_000)
    child.kill("SIGTERM")
    const exitCode = await child.exited
    await collectOutput
    const error = await new Response(child.stderr).text()

    expect(exitCode).toBe(0)
    expect(error).toBe("")
    expect(output).toContain("\x1b[?1049h")
    expect(output).toContain("\x1b[?1049l")
  })
}
