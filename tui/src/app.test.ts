import { afterEach, describe, expect, test } from "bun:test"
import { CliRenderEvents, TextareaRenderable } from "@opentui/core"
import {
  MockTreeSitterClient,
  createTestRenderer,
  type TestRendererSetup,
} from "@opentui/core/testing"

import { NanobotTui, type AppOptions } from "./app"
import type { MessageOptions, SlashCommand } from "./protocol"

const options: AppOptions = {
  wsUrl: "ws://localhost.invalid/ws",
  apiUrl: "",
  apiToken: "",
  model: "test/model",
  modelPreset: "default",
  workspace: "/tmp/nanobot-workspace",
  version: "test",
  access: "workspace access",
  theme: "auto",
}

interface HiddenScrollBar {
  visible: boolean
  slider: { visible: boolean }
  startArrow: { visible: boolean }
  endArrow: { visible: boolean }
}

interface HiddenScrollBox {
  verticalScrollBar: HiddenScrollBar
  horizontalScrollBar: HiddenScrollBar
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

function client(
  sent: string[] = [],
  attached: string[] = [],
  newChats: string[] = [],
  sentOptions: MessageOptions[] = [],
  forks: Array<{ source: string; before: number; title?: string }> = [],
) {
  return {
    activeChatId: "chat",
    connect() {},
    close() {},
    send(content: string, options: MessageOptions = {}) {
      sent.push(content)
      sentOptions.push(options)
      return "turn"
    },
    attach(chatId: string) {
      attached.push(chatId)
    },
    newChat() {
      newChats.push("new")
    },
    forkChat(source: string, before: number, title?: string) {
      forks.push({ source, before, ...(title ? { title } : {}) })
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
    expect(frame).toContain("✓ Read  config.json")
    expect(frame).not.toContain("› Read")
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

  test("inserts a newline without sending and gives the composer breathing room", async () => {
    const sent: string[] = []
    setup = await createRenderer({
      width: 72,
      height: 20,
      screenMode: "alternate-screen",
      kittyKeyboard: true,
    })
    const app = mount(setup, sent)
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    const ui = app as unknown as {
      composer: TextareaRenderable
      composerFrame: { height: number }
    }

    await setup.mockInput.typeText("first")
    setup.mockInput.pressKey("j", { ctrl: true })
    await setup.mockInput.typeText("second")
    await setup.flush()

    expect(ui.composer.plainText).toBe("first\nsecond")
    expect(sent).toEqual([])
    expect(ui.composerFrame.height).toBeGreaterThanOrEqual(3)
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

  test("compacts large pastes in the composer without changing the sent text", async () => {
    const sent: string[] = []
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup, sent)
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      status: { plainText: string }
    }
    const pasted = Array.from({ length: 12 }, (_, index) => `line ${index + 1}`).join("\n")

    await setup.mockInput.pasteBracketedText(pasted)
    await setup.flush()
    expect(ui.composer.plainText).toBe("[Pasted 12 lines] ")
    expect(ui.status.plainText).toContain("Pasted 12 lines")

    ui.composer.submit()
    await waitUntil(() => sent.length === 1)
    expect(sent).toEqual([pasted])
    expect(ui.composer.plainText).toBe("")
  })

  test("steers with Enter, queues with Tab, and restores queued text with Alt+Up", async () => {
    const sent: string[] = []
    const sentOptions: MessageOptions[] = []
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      client(sent, [], [], sentOptions),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      ready: boolean
      composer: TextareaRenderable
      mentionCandidates: Array<Record<string, unknown>>
      queuePreview: { root: { visible: boolean } }
    }
    await waitUntil(() => ui.ready)
    ui.mentionCandidates = [{
      kind: "cli",
      name: "github",
      displayName: "GitHub",
      description: "CLI",
    }]

    ui.composer.setText("first")
    ui.composer.submit()
    await waitUntil(() => sent.length === 1)

    ui.composer.setText("ask @github next")
    ui.composer.submit()
    await waitUntil(() => sent.length === 2)
    expect(sentOptions[1]).toEqual({
      cliApps: [{ name: "github" }],
      mcpPresets: [],
      sessionMentions: [],
    })

    ui.composer.setText("after this turn")
    setup.mockInput.pressTab()
    await waitUntil(() => ui.composer.plainText === "")
    expect(sent).toHaveLength(2)
    expect(ui.queuePreview.root.visible).toBeTrue()

    setup.mockInput.pressArrow("up", { meta: true })
    expect(ui.composer.plainText).toBe("after this turn")
    expect(ui.queuePreview.root.visible).toBeFalse()
    setup.mockInput.pressTab()
    await waitUntil(() => ui.composer.plainText === "")

    app.accept({
      event: "error",
      chat_id: "chat",
      turn_id: "failed-steering",
      reason: "steering rejected",
    })
    expect((app as unknown as { activeTurn: boolean }).activeTurn).toBeTrue()

    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => ui.ready)
    app.accept({ event: "goal_status", chat_id: "chat", status: "running", turn_id: "turn" })
    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "turn" })
    await waitUntil(() => sent.length === 3)
    expect(sent[2]).toBe("after this turn")
    expect(ui.queuePreview.root.visible).toBeFalse()
    app.accept({ event: "goal_status", chat_id: "chat", status: "idle", turn_id: "prior" })
    expect((app as unknown as { activeTurn: boolean }).activeTurn).toBeTrue()
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
          model_preset: "Deep Research",
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
      titleText: { plainText: string }
      modelText: { plainText: string }
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
      expect(ui.titleText.plainText).toContain("Release checklist")
      expect(ui.modelText.plainText).toContain("Deep Research")
      expect(ui.modelText.plainText).not.toContain("test/model")

      app.accept({ event: "attached", chat_id: "other" })
      await Bun.sleep(1)
      ui.composer.setText("/new-chat")
      ui.composer.submit()
      await waitUntil(() => newChats.length === 1)
      expect(newChats).toEqual(["new"])
      expect(ui.titleText.plainText).toContain("New chat")
      expect(ui.modelText.plainText).toContain("test/model")
    } finally {
      globalThis.fetch = original
    }
  })

  test("tracks canonical presets without overwriting a session override", async () => {
    setup = await createRenderer({ width: 96, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const ui = app as unknown as { modelText: { plainText: string } }

    app.accept({ event: "attached", chat_id: "chat", model_preset: "Codex" })
    app.accept({
      event: "turn_model_updated",
      chat_id: "chat",
      model_name: "openai/gpt-5.6",
      model_preset: "Codex",
    })
    await setup.flush()
    expect(ui.modelText.plainText).toContain("Codex  ·  openai/gpt-5.6")

    app.accept({
      event: "runtime_model_updated",
      model_name: "deepseek/deepseek-chat",
      model_preset: "DeepSeek",
    })
    await setup.flush()
    expect(ui.modelText.plainText).toContain("Codex  ·  openai/gpt-5.6")
    expect(ui.modelText.plainText).not.toContain("DeepSeek")
  })

  test("returns a default-following chat to the canonical default preset", async () => {
    setup = await createRenderer({ width: 96, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, model: "openai/gpt-5.6", modelPreset: "Codex" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as { modelText: { plainText: string } }

    app.accept({ event: "attached", chat_id: "chat", model_preset: null })
    app.accept({
      event: "runtime_model_updated",
      model_name: "deepseek/deepseek-chat",
      model_preset: null,
    })
    await setup.flush()

    expect(ui.modelText.plainText).toContain("deepseek/deepseek-chat")
    expect(ui.modelText.plainText).not.toContain("Codex")
  })

  test("refreshes the canonical preset after the model command completes", async () => {
    setup = await createRenderer({ width: 96, height: 20, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      if (String(input).endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return Promise.resolve(new Response(JSON.stringify({
        sessions: [{ key: "websocket:chat", model_preset: "Deep Research" }],
      })))
    }) as typeof fetch
    const sent: string[] = []
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(sent),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as {
      composer: TextareaRenderable
      commandMenu: { setCommands(commands: SlashCommand[]): void }
      modelText: { plainText: string }
    }

    try {
      app.accept({ event: "attached", chat_id: "chat", model_preset: null })
      ui.commandMenu.setCommands([{
        command: "/model",
        title: "Model",
        description: "Show or switch model presets",
        argHint: "[preset]",
        lifecycle: "side_channel",
        acceptsArgs: true,
      }])
      ui.composer.setText("/model deep research")
      ui.composer.submit()
      await waitUntil(() => sent.length === 1)
      app.accept({
        event: "message",
        chat_id: "chat",
        text: "Switched model preset to Deep Research.",
        turn_id: "turn",
      })
      await waitUntil(() => ui.modelText.plainText.includes("Deep Research"))

      expect(sent).toEqual(["/model deep research"])
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
    globalThis.fetch = ((input: string | URL | Request) => {
      if (String(input).endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return new Promise<Response>((resolve) => {
        resolveFetch = resolve
      })
    }) as typeof fetch
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
    globalThis.fetch = ((input: string | URL | Request) => {
      if (String(input).endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return new Promise<Response>((resolve) => {
        resolveFetch = resolve
      })
    }) as typeof fetch
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
      await waitUntil(() => resolveFetch !== undefined)
      ui.composer.setText("release")
      resolveFetch!(new Response(JSON.stringify({
        sessions: [
          { key: "websocket:chat", title: "Current chat", preview: "Current work" },
          { key: "websocket:other", title: "Release checklist", preview: "Ship it" },
        ],
      })))
      await waitUntil(() => ui.sessionMenu.visible)
      await setup.flush()
      const frame = setup.captureCharFrame()
      expect(frame).toContain("Release checklist")
      expect(occurrences(frame, "Current chat")).toBe(1)
    } finally {
      globalThis.fetch = original
    }
  })

  test("explains the session-owned agent context without exposing private reasoning", async () => {
    setup = await createRenderer({ width: 96, height: 26, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      expect(String(input)).toContain("/api/sessions/websocket%3Achat/context")
      return Promise.resolve(new Response(JSON.stringify({
        total_messages: 24,
        archived_messages: 16,
        replay_messages: 10,
        estimated_replay_tokens: 2048,
        estimated_summary_tokens: 128,
        estimated_session_tokens: 2176,
        archived_summary: "The earlier turns agreed on a release plan.",
        archived_summary_at: "2026-08-13T10:00:00Z",
      })))
    }) as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      composer: TextareaRenderable
      contextPanel: { visible: boolean }
      modelText: { plainText: string }
    }

    try {
      ui.composer.setText("/context")
      ui.composer.submit()
      await waitUntil(() => ui.contextPanel.visible)
      await setup.flush()
      expect(ui.modelText.plainText).toContain("~2.2k ctx")
      const frame = setup.captureCharFrame()

      expect(frame).toContain("Agent context")
      expect(frame).toContain("~2.2k session tokens · 10 replay messages · 16 archived · summary active")
      expect(frame).toContain("The earlier turns agreed on a release plan.")
      expect(frame).toContain("memory, instructions, and skills are added separately")

      setup.resize(40, 10)
      await setup.renderOnce()
      const compact = setup.captureCharFrame()
      expect(occurrences(compact, "Agent context")).toBe(1)
      expect(occurrences(compact, "Ask nanobot anything")).toBe(1)

      setup.mockInput.pressEscape()
      await waitUntil(() => !ui.contextPanel.visible)
      expect(ui.contextPanel.visible).toBe(false)
    } finally {
      globalThis.fetch = original
    }
  })

  test("opens the latest turn diff as a full-screen, navigable view", async () => {
    setup = await createRenderer({ width: 96, height: 28, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    app.accept({ event: "message_accepted", chat_id: "chat", turn_id: "edit-turn" })
    app.accept({
      event: "file_edit",
      chat_id: "chat",
      edits: [{
        call_id: "edit-1",
        tool: "edit_file",
        path: "src/first.ts",
        status: "done",
        added: 2,
        deleted: 1,
        diff: {
          format: "unified",
          truncated: true,
          text: [
            "--- a/src/first.ts",
            "+++ b/src/first.ts",
            "@@ -1 +1,2 @@",
            "-const oldValue = 1",
            "+const newValue = 2",
            "+export { newValue }",
          ].join("\n"),
        },
      }, {
        call_id: "edit-2",
        tool: "write_file",
        path: "src/second.py",
        status: "done",
        added: 1,
        deleted: 0,
        diff: {
          format: "unified",
          text: [
            "--- a/src/second.py",
            "+++ b/src/second.py",
            "@@ -0,0 +1 @@",
            "+print('hello')",
          ].join("\n"),
        },
      }],
    })
    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "edit-turn" })
    const ui = app as unknown as {
      composer: TextareaRenderable
      diffViewer: {
        visible: boolean
        scroll: { getChildren(): Array<{ addedBg?: { toInts(): number[] } }> }
      }
    }

    ui.composer.setText("/diff")
    ui.composer.submit()
    await waitUntil(() => ui.diffViewer.visible)
    await setup.flush()
    let frame = setup.captureCharFrame()
    expect(frame).toContain("Diff · Last turn · 2 changes · +3 -1")
    expect(frame).toContain("1/2 · src/first.ts · +2 -1")
    expect(frame).toContain("const newValue = 2")
    expect(frame).toContain("Diff truncated by the gateway")
    expect(frame).not.toContain("Ask nanobot anything")

    setup.mockInput.pressArrow("right")
    await setup.flush()
    frame = setup.captureCharFrame()
    expect(frame).toContain("2/2 · src/second.py · +1 -0")
    expect(frame).toContain("print('hello')")

    setup.renderer.emit(CliRenderEvents.THEME_MODE, "light")
    await setup.flush()
    expect(ui.diffViewer.scroll.getChildren()[0]?.addedBg?.toInts().slice(0, 3)).toEqual([231, 246, 236])
    expect(setup.captureCharFrame()).toContain("print('hello')")

    setup.resize(52, 18)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("←/→ file · pgup/pgdn · esc")

    setup.mockInput.pressEscape()
    await waitUntil(() => !ui.diffViewer.visible)
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("Ask nanobot anything")
  })

  test("loads earlier transcript pages in place when PageUp reaches the top", async () => {
    setup = await createRenderer({ width: 80, height: 22, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    const requests: string[] = []
    globalThis.fetch = ((input: string | URL | Request) => {
      const url = String(input)
      requests.push(url)
      const older = url.includes("before=older-page")
      return Promise.resolve(new Response(JSON.stringify({
        messages: older
          ? [
              { role: "user", content: "oldest question" },
              { role: "assistant", content: "oldest answer" },
            ]
          : [
              { role: "user", content: "recent question" },
              { role: "assistant", content: "recent answer" },
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
      transcript: { root: HiddenScrollBox }
      diffViewer: { scroll: HiddenScrollBox }
    }
    const lines = setup.captureSpans().lines
    const spans = lines.flatMap((line) => line.spans)
    const brandedRows = lines.filter((line) => (
      line.spans.some((span) => span.bg.intent !== "default")
    ))

    expect(internals.shell.backgroundColor.intent).toBe("default")
    expect(internals.composerFrame.backgroundColor.intent).toBe("default")
    expect(internals.composer.backgroundColor.intent).toBe("default")
    expect(spans.length).toBeGreaterThan(0)
    expect(brandedRows).toHaveLength(0)
    for (const scrollBox of [internals.transcript.root, internals.diffViewer.scroll]) {
      for (const bar of [scrollBox.verticalScrollBar, scrollBox.horizontalScrollBar]) {
        expect(bar.visible).toBeFalse()
        expect(bar.slider.visible).toBeFalse()
        expect(bar.startArrow.visible).toBeFalse()
        expect(bar.endArrow.visible).toBeFalse()
      }
    }
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
      composerFrame: {
        backgroundColor: { intent: string; toInts(): number[] }
      }
      composer: {
        backgroundColor: { intent: string; toInts(): number[] }
        textColor: { toInts(): number[] }
      }
      transcript: {
        markdown: Set<{ syntaxStyle: object }>
        frames: Set<{ borderColor: { toInts(): number[] } }>
        userRows: Set<{ backgroundColor: { intent: string; toInts(): number[] } }>
        user(content: string): void
      }
    }
    internals.transcript.user("Existing question")
    const userRow = [...internals.transcript.userRows][0]
    const markdown = [...internals.transcript.markdown][0]
    const sessionFrame = [...internals.transcript.frames][0]
    const darkSyntax = markdown?.syntaxStyle

    expect(userRow?.backgroundColor.intent).toBe("default")

    setup.renderer.emit(CliRenderEvents.THEME_MODE, "light")
    await setup.flush()

    expect(internals.palette).toMatchObject({
      referenceBackground: "#FAFAFA",
      text: "#18181B",
      border: "#D4D4D8",
    })
    expect(internals.shell.backgroundColor.intent).toBe("default")
    expect(internals.composerFrame.backgroundColor.toInts().slice(0, 3)).toEqual([240, 240, 240])
    expect(internals.composer.backgroundColor.toInts().slice(0, 3)).toEqual([240, 240, 240])
    expect(internals.composer.textColor.toInts().slice(0, 3)).toEqual([24, 24, 27])
    expect(sessionFrame?.borderColor.toInts().slice(0, 3)).toEqual([212, 212, 216])
    expect(userRow?.backgroundColor.toInts().slice(0, 3)).toEqual([240, 240, 240])
    expect(markdown?.syntaxStyle).not.toBe(darkSyntax)
  })

  test("uses a quiet surface instead of a boxed composer", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, theme: "light" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const internals = app as unknown as {
      ready: boolean
      composerFrame: {
        border: boolean | string[]
        backgroundColor: { toInts(): number[] }
      }
      composer: { backgroundColor: { toInts(): number[] } }
    }

    expect(internals.composerFrame.border).toBeFalse()
    expect(internals.composerFrame.backgroundColor.toInts().slice(0, 3)).toEqual([240, 240, 240])
    expect(internals.composer.backgroundColor.toInts().slice(0, 3)).toEqual([240, 240, 240])

    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => internals.ready)
    await setup.renderOnce()

    const composerLine = setup.captureCharFrame().split("\n")
      .find((line) => line.includes("Ask nanobot anything")) || ""
    expect(composerLine).not.toContain("│")
  })

  test("uses asymmetric roles instead of chat bubbles", async () => {
    setup = await createRenderer({ width: 72, height: 24, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, theme: "dark" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
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

    const transcript = (app as unknown as {
      transcript: {
        userRows: Set<{ backgroundColor: { intent: string; toInts(): number[] } }>
        styledText: Array<{
          renderable: { id: string; fg: { toInts(): number[] } }
          tone: string
        }>
      }
    }).transcript
    const userRow = [...transcript.userRows][0]
    const assistantMarker = transcript.styledText.find(({ renderable, tone }) => (
      tone === "muted" && renderable.id.includes("role-marker")
    ))

    expect(userRow?.backgroundColor.intent).toBe("rgb")
    expect(userRow?.backgroundColor.toInts().slice(0, 3)).toEqual([43, 44, 46])
    expect(assistantMarker?.tone).toBe("muted")
    expect(assistantMarker?.renderable.fg.toInts().slice(0, 3)).toEqual([161, 161, 170])
  })

  test("keeps footer status and shortcuts visually separated", async () => {
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({
      event: "turn_end",
      chat_id: "chat",
      latency_ms: 1700,
      usage: { prompt_tokens: 1200, completion_tokens: 80, cached_tokens: 900 },
      context_window_tokens: 128_000,
    })
    await setup.flush()

    const footer = setup.captureCharFrame().split("\n").find((line) => line.includes("Ready · 1.7s")) || ""
    expect(footer).toContain("Ready · 1.7s")
    expect(footer).toContain("↑1.2k ↓80")
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

    const transcript = (app as unknown as {
      transcript: {
        userRows: Set<{ backgroundColor: { intent: string } }>
        user(content: string): void
      }
    }).transcript
    transcript.user("Unknown terminal background")

    expect(connected).toBe(true)
    expect((app as unknown as { palette: { referenceBackground: string } }).palette.referenceBackground).toBe("#0E0F11")
    expect([...transcript.userRows][0]?.backgroundColor.intent).toBe("default")
  })

  test("keeps semantic colors legible in both terminal appearances", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const internals = app as unknown as {
      palette: Record<string, string> & { referenceBackground: string; faint: string }
    }
    const assertContrast = () => {
      for (const tone of ["text", "muted", "accent", "link", "success", "error", "user", "warm", "cool"]) {
        expect(contrastRatio(internals.palette[tone] ?? "", internals.palette.referenceBackground)).toBeGreaterThanOrEqual(4.5)
      }
      expect(contrastRatio(internals.palette.faint, internals.palette.referenceBackground)).toBeGreaterThanOrEqual(3)
      const turnContrast = contrastRatio(
        internals.palette.userBackground ?? "",
        internals.palette.referenceBackground,
      )
      expect(turnContrast).toBeGreaterThan(1.05)
      expect(turnContrast).toBeLessThan(1.5)
    }

    assertContrast()
    expect(internals.palette.accent).toBe("#EF8E30")
    expect(internals.palette.user).toBe("#EF8E30")
    setup.renderer.emit(CliRenderEvents.THEME_MODE, "light")
    assertContrast()
    expect(internals.palette.accent).toBe("#B94D0B")
    expect(internals.palette.user).toBe("#B94D0B")
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

    expect(frame).toMatch(/Thinking\s+0s/u)
    expect(frame).not.toMatch(/[◐◓◑◒⠋⠙⠹⠸]/u)
    expect(frame).not.toContain("hidden reasoning")
    const status = (app as unknown as {
      status: {
        content: { chunks: Array<{ fg?: { toInts(): number[] } }> }
        plainText: string
      }
    }).status
    expect(status.plainText).toMatch(/^Thinking\s+0s/u)
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
    expect(frame).toContain("› Command  pwd")
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

  test("exits immediately when Ctrl+C is pressed on an idle empty composer", async () => {
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
