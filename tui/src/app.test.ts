import { afterEach, describe, expect, test } from "bun:test"
import {
  BoxRenderable,
  CliRenderEvents,
  StyledText,
  TextareaRenderable,
  TextAttributes,
  TextRenderable,
} from "@opentui/core"
import {
  MockTreeSitterClient,
  createTestRenderer,
  type TestRendererSetup,
} from "@opentui/core/testing"

import { NanobotTui, sessionExitMessage, type AppOptions } from "./app"
import type {
  MessageOptions,
  RecoveryState,
  SkillCandidate,
  SlashCommand,
  WorkspaceScopePayload,
} from "./protocol"
import type { TuiHost } from "./host"
import type { ClipboardImageReader } from "./clipboard-image"
import { userMessageText, type Transcript } from "./transcript"

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

test("formats a reusable session ID after exit", () => {
  expect(sessionExitMessage("resume-chat")).toBe(
    "Resume with: nanobot agent --session websocket:resume-chat\n",
  )
})

test("projects image media as stable placeholders without exposing filenames", () => {
  expect(userMessageText("What is this?", [
    { name: "clipboard-image-2.png" },
    { kind: "image", name: "screenshot.png" },
    { kind: "file", name: "report.pdf" },
  ])).toBe([
    "What is this? [Image #2] [Image #1]",
    "Attachments: report.pdf",
  ].join("\n"))
  expect(userMessageText("What is this?", [
    { name: "clipboard-image-1.png" },
  ], "What is this? [Image #1]")).toBe("What is this? [Image #1]")
})

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
  scopes: WorkspaceScopePayload[] = [],
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
    newChat(_scope?: WorkspaceScopePayload) {
      newChats.push("new")
    },
    forkChat(source: string, before: number, title?: string) {
      forks.push({ source, before, ...(title ? { title } : {}) })
    },
    setWorkspaceScope(scope: WorkspaceScopePayload) {
      scopes.push(scope)
    },
    updateRecovery(
      _action: "continue" | "dismiss",
      _chatId: string,
      recoveryId: string,
    ): Promise<RecoveryState> {
      return Promise.resolve({ status: "recovered" as const, recovery_id: recoveryId })
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

  test("keeps short transcripts and the composer anchored at the top", async () => {
    setup = await createRenderer({
      width: 100,
      height: 18,
      screenMode: "alternate-screen",
      consoleMode: "disabled",
    })
    const app = mount(setup)
    const ui = app as unknown as {
      transcript: Transcript
      title: BoxRenderable
      status: TextRenderable
    }
    const positions = () => ({
      transcriptHeight: ui.transcript.root.height,
      titleY: ui.title.y,
      statusY: ui.status.y,
    })

    let anchoredPositions: ReturnType<typeof positions> | undefined
    for (const height of [18, 30, 36]) {
      setup.resize(100, height)
      await setup.renderOnce()
      expect(ui.title.y).toBe(ui.transcript.root.y + ui.transcript.root.height)
      expect(ui.status.y + ui.status.height).toBeLessThan(setup.renderer.height)
      if (!anchoredPositions) anchoredPositions = positions()
      else expect(positions()).toEqual(anchoredPositions)
    }

    ui.transcript.user("A short prompt")
    await setup.renderOnce()
    const promptPositions = positions()
    expect(promptPositions.titleY).toBeGreaterThan(anchoredPositions?.titleY || 0)

    setup.resize(100, 40)
    await setup.renderOnce()
    expect(positions()).toEqual(promptPositions)
  })

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
      expect(occurrences(frame, "Getting ready…")).toBe(1)
      expect(occurrences(frame, "default ▾")).toBe(1)
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

  test("keeps input typed immediately after Enter in the next draft", async () => {
    const sent: string[] = []
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup, sent)
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const composer = (app as unknown as { composer: TextareaRenderable }).composer

    composer.setText("first")
    setup.mockInput.pressEnter()
    for (const key of "next") setup.mockInput.pressKey(key)
    await waitUntil(() => sent.length > 0)

    expect(sent).toEqual(["first"])
    expect(composer.plainText).toBe("next")
  })

  test("inserts newlines with Shift+Enter and the universal Ctrl+J fallback", async () => {
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
    setup.mockInput.pressEnter({ shift: true })
    await setup.mockInput.typeText("second")
    setup.mockInput.pressKey("j", { ctrl: true })
    await setup.mockInput.typeText("third")
    await setup.flush()

    expect(ui.composer.plainText).toBe("first\nsecond\nthird")
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

  test("pastes clipboard images into removable placeholders and sends their data", async () => {
    const sent: string[] = []
    const sentOptions: MessageOptions[] = []
    let disposed = false
    const clipboard: ClipboardImageReader = {
      read: async () => ({
        mimeType: "image/png",
        dataUrl: "data:image/png;base64,AAEC/w==",
      }),
      dispose: async () => { disposed = true },
    }
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const transport = client(sent, [], [], sentOptions)
    const recordSend = transport.send
    transport.send = (content, messageOptions) => {
      recordSend(content, messageOptions)
      return `image-turn-${sent.length}`
    }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
      undefined,
      clipboard,
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    const ui = app as unknown as {
      composer: TextareaRenderable
      draft: { imageCount: number }
      promptHistory: string[]
      status: { plainText: string }
      transcript: {
        userMessages: Set<{ renderable: TextRenderable }>
      }
    }

    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => ui.composer.plainText === "[Image #1] ")
    expect(ui.status.plainText).toContain("Pasted Image #1")
    const placeholderStyle = ui.composer.syntaxStyle?.getStyle("image.placeholder")
    expect(placeholderStyle?.bold).toBeTrue()
    expect(placeholderStyle?.fg?.toInts().slice(0, 3)).toEqual([239, 142, 48])
    const placeholderStyleId = ui.composer.syntaxStyle?.getStyleId("image.placeholder")
    if (placeholderStyleId === null || placeholderStyleId === undefined) {
      throw new Error("image placeholder style was not registered")
    }
    expect(ui.composer.getLineHighlights(0)).toEqual([{
      start: 0,
      end: 10,
      styleId: placeholderStyleId,
      priority: 100,
      hlRef: 0,
    }])
    ui.composer.setText("")
    await waitUntil(() => ui.draft.imageCount === 0)
    expect(ui.composer.getLineHighlights(0)).toEqual([])

    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => ui.composer.plainText === "[Image #1] ")
    await setup.mockInput.typeText("[Image #1]")
    ui.composer.submit()
    await waitUntil(() => ui.status.plainText.includes("Duplicate image placeholder"))
    expect(sent).toEqual([])
    ui.composer.setText("[Image #1]")
    ui.composer.submit()
    await waitUntil(() => sent.length === 1)
    expect(sent).toEqual([""])
    expect(ui.promptHistory).toEqual([])
    expect(sentOptions[0]?.media).toEqual([{
      data_url: "data:image/png;base64,AAEC/w==",
      name: "clipboard-image-1.png",
    }])
    expect(sentOptions[0]).not.toHaveProperty("displayContent")
    await setup.flush()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("[Image #1]")
    expect(frame).not.toContain("clipboard-image-1.png")
    const userContent = [...ui.transcript.userMessages].at(-1)?.renderable.content
    expect(userContent).toBeInstanceOf(StyledText)
    const imageChunk = (userContent as StyledText).chunks.find(({ text }) => text === "[Image #1]")
    expect(imageChunk?.attributes).toBe(TextAttributes.BOLD)
    expect(imageChunk?.fg?.toInts().slice(0, 3)).toEqual([239, 142, 48])

    await setup.mockInput.typeText("这是什么？ ")
    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => ui.composer.plainText === "这是什么？ [Image #1] ")
    setup.mockInput.pressTab()
    expect(ui.status.plainText).toContain("Images cannot be queued")
    expect(ui.composer.plainText).toBe("这是什么？ [Image #1] ")
    ui.composer.submit()
    await waitUntil(() => sent.length === 2)
    expect(sent[1]).toBe("这是什么？")
    expect(sentOptions[1]?.media).toHaveLength(1)
    expect(sentOptions[1]).not.toHaveProperty("displayContent")
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("这是什么？ [Image #1]")

    setup.renderer.destroy()
    expect(disposed).toBeTrue()
  })

  test("keeps image placeholders atomic for cursor movement and deletion", async () => {
    const clipboard: ClipboardImageReader = {
      read: async () => ({
        mimeType: "image/png",
        dataUrl: "data:image/png;base64,AAEC/w==",
      }),
      dispose: async () => undefined,
    }
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
      undefined,
      clipboard,
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    const ui = app as unknown as {
      composer: TextareaRenderable
      draft: { imageCount: number }
      status: { plainText: string }
    }

    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => ui.composer.plainText === "[Image #1] ")
    await setup.flush()
    await setup.mockMouse.click(ui.composer.x + 5, ui.composer.y)
    expect(ui.composer.cursorOffset > 0 && ui.composer.cursorOffset < 10).toBeFalse()
    ui.composer.cursorOffset = 0
    setup.mockInput.pressArrow("right")
    await waitUntil(() => ui.composer.cursorOffset === 10)
    setup.mockInput.pressArrow("left")
    await waitUntil(() => ui.composer.cursorOffset === 0)

    setup.mockInput.pressArrow("right", { shift: true })
    await waitUntil(() => ui.composer.cursorOffset === 10)
    await setup.mockInput.typeText("replacement")
    await waitUntil(() => ui.draft.imageCount === 0)
    expect(ui.composer.plainText).toContain("replacement")
    expect(ui.composer.plainText).not.toContain("Image #1")

    ui.composer.setText("")
    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => ui.composer.plainText === "[Image #1] ")
    ui.composer.cursorOffset = 0
    setup.mockInput.pressKey("DELETE")
    await waitUntil(() => ui.draft.imageCount === 0)
    expect(ui.composer.plainText.trim()).toBe("")
    expect(ui.status.plainText).toContain("Removed Image #1")

    ui.composer.setText("")
    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => ui.composer.plainText === "[Image #1] ")
    ui.composer.cursorOffset = 10
    setup.mockInput.pressBackspace()
    await waitUntil(() => ui.draft.imageCount === 0)
    expect(ui.composer.plainText.trim()).toBe("")

    ui.composer.setText("")
    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => ui.composer.plainText === "[Image #1] ")
    ui.composer.setText("Image #1] ")
    await waitUntil(() => ui.draft.imageCount === 0)
    expect(ui.composer.plainText.trim()).toBe("")
  })

  test("keeps clipboard failures visible while an agent turn is active", async () => {
    const sent: string[] = []
    const clipboard: ClipboardImageReader = {
      read: async () => { throw new Error("No image in clipboard") },
      dispose: async () => undefined,
    }
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      client(sent),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
      undefined,
      clipboard,
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    const composer = (app as unknown as { composer: TextareaRenderable }).composer
    composer.setText("start")
    composer.submit()
    await waitUntil(() => sent.length === 1)

    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => setup?.captureCharFrame().includes("No image in clipboard") === true)
  })

  test("keeps image placeholders out of command arguments", async () => {
    const sent: string[] = []
    const clipboard: ClipboardImageReader = {
      read: async () => ({
        mimeType: "image/png",
        dataUrl: "data:image/png;base64,AAEC/w==",
      }),
      dispose: async () => undefined,
    }
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      client(sent),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
      undefined,
      clipboard,
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    const ui = app as unknown as {
      composer: TextareaRenderable
      status: { plainText: string }
      commandMenu: { setCommands(commands: SlashCommand[]): void }
    }
    ui.commandMenu.setCommands([{
      command: "/model",
      title: "Model",
      description: "Show or switch model presets",
      argHint: "[preset]",
      lifecycle: "side_channel",
      acceptsArgs: true,
    }])

    await setup.mockInput.typeText("/model ")
    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => ui.composer.plainText === "/model [Image #1] ")
    ui.composer.submit()
    await waitUntil(() => ui.status.plainText.includes("Images cannot be used with commands"))

    expect(sent).toEqual([])
    expect(ui.composer.plainText).toBe("/model [Image #1] ")
  })

  test("ignores a clipboard result that finishes after the renderer is destroyed", async () => {
    let resolveRead: ((image: {
      mimeType: "image/png"
      dataUrl: string
    }) => void) | undefined
    let disposed = false
    const clipboard: ClipboardImageReader = {
      read: () => new Promise((resolve) => { resolveRead = resolve }),
      dispose: async () => { disposed = true },
    }
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
      undefined,
      clipboard,
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)

    setup.mockInput.pressKey("v", { ctrl: true })
    await waitUntil(() => resolveRead !== undefined)
    setup.renderer.destroy()
    resolveRead?.({ mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" })
    await Bun.sleep(10)
    expect(disposed).toBeTrue()
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
      status: { plainText: string }
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
    expect(ui.composer.placeholder).toBe("Enter send now · Tab send next")

    ui.composer.setText("one more detail")
    await setup.flush()
    expect(ui.composer.placeholder).toBeNull()

    ui.composer.setText("ask @github next")
    ui.composer.submit()
    await waitUntil(() => sent.length === 2)
    expect(ui.status.plainText).not.toContain("Steering")
    expect(ui.composer.placeholder).toBe("Enter send now · Tab send next")
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

  test("projects user turns from another terminal without duplicating replayed history", async () => {
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)

    const first = {
      event: "user_message" as const,
      chat_id: "chat",
      text: "hello from terminal A",
      turn_id: "remote-turn",
      active_turn_id: "remote-turn",
      starts_turn: true,
      started_at: 1_700_000_000,
      media_urls: [{
        kind: "file" as const,
        url: "/api/media/sig/report",
        name: "report.pdf",
      }],
    }
    app.accept(first)
    app.accept(first)
    app.accept({
      event: "user_message",
      chat_id: "chat",
      text: "one more remote detail",
      turn_id: "remote-steer",
      active_turn_id: "remote-turn",
      starts_turn: false,
      media_urls: [{
        kind: "image",
        url: "/api/media/sig/image",
        name: "clipboard-image-2.png",
      }],
    })
    await setup.flush()

    const state = app as unknown as { activeTurn: boolean; activeTurnId: string | null }
    const frame = setup.captureCharFrame()
    expect(occurrences(frame, "hello from terminal A")).toBe(1)
    expect(occurrences(frame, "Attachments: report.pdf")).toBe(1)
    expect(occurrences(frame, "one more remote detail")).toBe(1)
    expect(occurrences(frame, "[Image #2]")).toBe(1)
    expect(frame).toContain("one more remote detail [Image #2]")
    expect(frame).not.toContain("clipboard-image-2.png")
    expect(state.activeTurn).toBeTrue()
    expect(state.activeTurnId).toBe("remote-turn")

    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "remote-turn" })
    expect(state.activeTurn).toBeFalse()
  })

  test("reconciles simultaneous submits to the gateway-owned turn", async () => {
    const sent: string[] = []
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup, sent)
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)

    const ui = app as unknown as {
      composer: TextareaRenderable
      activeTurn: boolean
      activeTurnId: string | null
    }
    ui.composer.setText("submitted from terminal B")
    ui.composer.submit()
    await waitUntil(() => sent.length === 1)
    expect(ui.activeTurnId).toBe("turn")

    app.accept({
      event: "message_accepted",
      chat_id: "chat",
      turn_id: "turn",
      active_turn_id: "terminal-a-turn",
      starts_turn: false,
      started_at: 1_700_000_000,
    })

    expect(ui.activeTurn).toBeTrue()
    expect(ui.activeTurnId).toBe("terminal-a-turn")
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

  test("completes available skills with arrows, Enter, Tab, and Escape", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const sent: string[] = []
    const app = mount(setup, sent)
    const ui = app as unknown as {
      ready: boolean
      composer: TextareaRenderable
      skillCandidates: SkillCandidate[]
      skillMenu: { visible: boolean }
    }
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => ui.ready)
    ui.skillCandidates = [
      { name: "simplify", description: "Simplify code", source: "workspace" },
      { name: "verify", description: "Verify public behavior", source: "builtin" },
    ]

    await setup.mockInput.typeText("$")
    expect(ui.skillMenu.visible).toBe(true)
    setup.mockInput.pressArrow("down")
    setup.mockInput.pressEnter()
    await waitUntil(() => ui.composer.plainText === "$verify ")
    expect(ui.skillMenu.visible).toBe(false)
    expect(sent).toEqual([])

    ui.composer.setText("")
    await setup.mockInput.typeText("please $sim")
    expect(ui.skillMenu.visible).toBe(true)
    setup.mockInput.pressTab()
    expect(ui.composer.plainText).toBe("please $simplify ")
    expect(ui.skillMenu.visible).toBe(false)

    ui.composer.setText("")
    await setup.mockInput.typeText("$")
    expect(ui.skillMenu.visible).toBe(true)
    setup.mockInput.pressEscape()
    await waitUntil(() => !ui.skillMenu.visible)
    expect(ui.skillMenu.visible).toBe(false)
    expect(ui.composer.plainText).toBe("$")

    ui.composer.setText("")
    await setup.mockInput.typeText("请用 $ver")
    expect(ui.skillMenu.visible).toBe(true)
    setup.mockInput.pressTab()
    expect(ui.composer.plainText).toBe("请用 $verify ")
    await setup.mockInput.typeText("now")
    expect(ui.composer.plainText).toBe("请用 $verify now")

    ui.composer.setText("use $verify later")
    ui.composer.cursorOffset = 8
    await waitUntil(() => ui.skillMenu.visible)
    ui.composer.cursorOffset = ui.composer.plainText.length
    await waitUntil(() => !ui.skillMenu.visible)

    ui.composer.setText("")
    await setup.mockInput.typeText("$missing")
    expect(ui.skillMenu.visible).toBe(true)
    ui.composer.submit()
    await waitUntil(() => sent.length === 1)
    expect(sent).toEqual(["$missing"])
    expect(ui.skillMenu.visible).toBe(false)
  })

  test("does not queue unmatched skill text when Tab dismisses completion", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const sent: string[] = []
    const app = mount(setup, sent)
    const ui = app as unknown as {
      ready: boolean
      composer: TextareaRenderable
      skillCandidates: SkillCandidate[]
      skillMenu: { visible: boolean }
      queuePreview: { root: { visible: boolean } }
    }
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => ui.ready)
    ui.skillCandidates = [{
      name: "verify",
      description: "Verify public behavior",
      source: "builtin",
    }]

    ui.composer.setText("start an active turn")
    ui.composer.submit()
    await waitUntil(() => sent.length === 1)

    await setup.mockInput.typeText("$missing")
    expect(ui.skillMenu.visible).toBe(true)
    setup.mockInput.pressTab()

    expect(ui.composer.plainText).toBe("$missing")
    expect(ui.skillMenu.visible).toBe(false)
    expect(ui.queuePreview.root.visible).toBe(false)

    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "turn" })
    await Bun.sleep(1)
    expect(sent).toEqual(["start an active turn"])
  })

  test("runs bang commands through the gateway without steering the agent", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const sent: string[] = []
    const sentOptions: MessageOptions[] = []
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      client(sent, [], [], sentOptions),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as { ready: boolean; composer: TextareaRenderable; activeTurn: boolean }
    await waitUntil(() => ui.ready)

    app.accept({ event: "goal_status", chat_id: "chat", status: "running" })
    ui.composer.setText("!pwd")
    ui.composer.submit()

    await waitUntil(() => sent.length === 1)
    expect(sent).toEqual(["!pwd"])
    expect(sentOptions).toEqual([{ userShell: true }])
    expect(ui.activeTurn).toBe(true)

    app.accept({ event: "message", chat_id: "chat", text: "/tmp/project", turn_id: "turn" })
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("/tmp/project")
    expect(ui.activeTurn).toBe(true)
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
      runtimeControls: { modelText: { plainText: string } }
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
      expect(ui.runtimeControls.modelText.plainText).toBe("Deep Research ▾")
      expect(ui.runtimeControls.modelText.plainText).not.toContain("test/model")

      app.accept({ event: "attached", chat_id: "other" })
      await Bun.sleep(1)
      ui.composer.setText("/new-chat")
      ui.composer.submit()
      await waitUntil(() => newChats.length === 1)
      expect(newChats).toEqual(["new"])
      expect(ui.runtimeControls.modelText.plainText).toBe("default ▾")
    } finally {
      globalThis.fetch = original
    }
  })

  test("switches away from a running session without losing its queued follow-ups", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/sessions")) {
        return Promise.resolve(new Response(JSON.stringify({
          sessions: [
            { key: "websocket:chat", title: "Running chat", run_started_at: 1_700_000_000 },
            { key: "websocket:other", title: "Other chat" },
          ],
        })))
      }
      if (url.endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return Promise.resolve(new Response(JSON.stringify({
        messages: [],
        page: { has_more_before: false },
      })))
    }) as typeof fetch
    const sent: string[] = []
    const attached: string[] = []
    let activeChatId = "chat"
    const base = client(sent, attached)
    const transport = {
      ...base,
      get activeChatId() { return activeChatId },
      attach(chatId: string) {
        attached.push(chatId)
        activeChatId = chatId
      },
    }
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as {
      ready: boolean
      activeTurn: boolean
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
      queuePreview: { root: { visible: boolean } }
      status: { plainText: string }
    }

    try {
      app.accept({ event: "attached", chat_id: "chat" })
      await waitUntil(() => ui.ready)
      app.accept({ event: "goal_status", chat_id: "chat", status: "running", turn_id: "turn" })
      ui.composer.setText("follow up in chat")
      setup.mockInput.pressTab()
      await waitUntil(() => ui.composer.plainText === "")
      expect(ui.queuePreview.root.visible).toBe(true)

      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionMenu.visible)
      await Bun.sleep(120)
      expect(ui.status.plainText).toContain("2 sessions")

      ui.composer.setText("other")
      ui.composer.submit()
      await waitUntil(() => attached.at(-1) === "other")
      app.accept({ event: "attached", chat_id: "other" })
      await waitUntil(() => ui.ready)
      expect(ui.activeTurn).toBe(false)
      expect(ui.queuePreview.root.visible).toBe(false)

      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionMenu.visible)
      ui.composer.setText("running")
      ui.composer.submit()
      await waitUntil(() => attached.at(-1) === "chat")
      app.accept({ event: "attached", chat_id: "chat" })
      app.accept({ event: "goal_status", chat_id: "chat", status: "running", turn_id: "turn" })
      await waitUntil(() => ui.ready && ui.activeTurn)
      expect(ui.queuePreview.root.visible).toBe(true)
      expect(sent).toEqual([])

      app.accept({ event: "turn_end", chat_id: "chat", turn_id: "turn" })
      await waitUntil(() => sent.length === 1)
      expect(sent).toEqual(["follow up in chat"])
    } finally {
      globalThis.fetch = original
    }
  })

  test("refreshes expired API credentials before opening sessions", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let bootstrapRequests = 0
    const sessionAuthorizations: Array<string | null> = []
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const authorization = new Headers(init?.headers).get("Authorization")
      if (url.endsWith("/webui/bootstrap")) {
        bootstrapRequests += 1
        return new Response(JSON.stringify({
          ws_url: "ws://nanobot.test/ws",
          token: "fresh-websocket-token",
          api_token: "fresh-api-token",
        }))
      }
      if (authorization === "Bearer expired-api-token") {
        return new Response("Unauthorized", { status: 401 })
      }
      if (url.endsWith("/api/sessions")) {
        sessionAuthorizations.push(authorization)
        return new Response(JSON.stringify({
          sessions: [{ key: "websocket:chat", title: "Current chat" }],
        }))
      }
      return new Response("{}")
    }) as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      {
        ...options,
        bootstrapUrl: "http://nanobot.test/webui/bootstrap",
        bootstrapSecret: "bootstrap-secret",
        apiUrl: "http://nanobot.test",
        apiToken: "expired-api-token",
      },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      ready: boolean
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
      status: { plainText: string }
    }

    try {
      await waitUntil(() => ui.ready)
      ui.composer.setText("/sessions")
      ui.composer.submit()

      await waitUntil(() => bootstrapRequests >= 1)
      await waitUntil(() => ui.sessionMenu.visible)
      expect(bootstrapRequests).toBe(1)
      expect(sessionAuthorizations.at(-1)).toBe("Bearer fresh-api-token")
      expect(ui.status.plainText).not.toContain("HTTP 401")
    } finally {
      globalThis.fetch = original
    }
  })

  test("tracks canonical presets without overwriting a session override", async () => {
    setup = await createRenderer({ width: 96, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const ui = app as unknown as { runtimeControls: { modelText: { plainText: string } } }

    app.accept({ event: "attached", chat_id: "chat", model_preset: "Codex" })
    app.accept({
      event: "turn_model_updated",
      chat_id: "chat",
      model_name: "openai/gpt-5.6",
      model_preset: "Codex",
    })
    await setup.flush()
    expect(ui.runtimeControls.modelText.plainText).toBe("Codex ▾")
    expect(ui.runtimeControls.modelText.plainText).not.toContain("openai/gpt-5.6")

    app.accept({
      event: "runtime_model_updated",
      model_name: "deepseek/deepseek-chat",
      model_preset: "DeepSeek",
    })
    await setup.flush()
    expect(ui.runtimeControls.modelText.plainText).toBe("Codex ▾")
    expect(ui.runtimeControls.modelText.plainText).not.toContain("DeepSeek")
  })

  test("returns a default-following chat to the canonical default preset", async () => {
    setup = await createRenderer({ width: 96, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, model: "openai/gpt-5.6", modelPreset: "Codex" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as { runtimeControls: { modelText: { plainText: string } } }

    app.accept({ event: "attached", chat_id: "chat", model_preset: null })
    app.accept({
      event: "runtime_model_updated",
      model_name: "deepseek/deepseek-chat",
      model_preset: null,
    })
    await setup.flush()

    expect(ui.runtimeControls.modelText.plainText).toBe("default ▾")
    expect(ui.runtimeControls.modelText.plainText).not.toContain("deepseek/deepseek-chat")
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
      runtimeControls: { modelText: { plainText: string } }
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
      await waitUntil(() => ui.runtimeControls.modelText.plainText.includes("Deep Research"))

      expect(sent).toEqual(["/model deep research"])
    } finally {
      globalThis.fetch = original
    }
  })

  test("opens composer runtime controls by mouse and applies canonical choices", async () => {
    const original = globalThis.fetch
    const sent: string[] = []
    const scopes: WorkspaceScopePayload[] = []
    let settingsRequests = 0
    let workspaceRequests = 0
    globalThis.fetch = (async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/settings")) {
        settingsRequests += 1
        return new Response(JSON.stringify({
          model_presets: [
            { name: "default", model: "test/model" },
            { name: "fast", model: "fast/model" },
          ],
        }))
      }
      if (url.endsWith("/api/workspaces")) {
        workspaceRequests += 1
        return new Response(JSON.stringify({
          controls: { can_use_full_access: true },
        }))
      }
      return new Response(JSON.stringify({ sessions: [] }))
    }) as typeof fetch
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(sent, [], [], [], [], scopes),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      runtimeControls: {
        modelText: TextRenderable
        accessText: TextRenderable
        contextText: TextRenderable
        visible: boolean
        menuRoot: { getChildren(): unknown[] }
      }
      composer: TextareaRenderable
      status: TextRenderable
      meta: TextRenderable
    }

    try {
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
      await setup.renderOnce()
      expect(setup.renderer.getCursorState()).toMatchObject({
        style: "line",
        blinking: false,
      })
      expect(ui.runtimeControls.modelText.selectable).toBe(false)
      expect(ui.runtimeControls.accessText.selectable).toBe(false)
      expect(ui.runtimeControls.contextText.selectable).toBe(false)
      expect(ui.status.selectable).toBe(false)
      expect(ui.meta.selectable).toBe(false)
      app.accept({ event: "goal_status", chat_id: "chat", status: "running" })
      await setup.flush()
      await setup.mockMouse.click(
        ui.runtimeControls.modelText.x + 2,
        ui.runtimeControls.modelText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      await setup.flush()
      const modelRows = ui.runtimeControls.menuRoot.getChildren() as TextRenderable[]
      expect(modelRows.every((row) => !row.selectable)).toBe(true)
      const fast = modelRows.find((row) => row.plainText.includes("fast"))
      if (!fast) throw new Error("fast model row was not rendered")
      ui.composer.blur()
      expect(ui.composer.focused).toBe(false)
      await setup.mockMouse.click(fast.x + 2, fast.y)
      await waitUntil(() => sent.includes("/model fast"))
      expect(ui.composer.focused).toBe(true)

      await setup.mockMouse.click(
        ui.runtimeControls.accessText.x + 2,
        ui.runtimeControls.accessText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      await setup.flush()
      const accessRows = ui.runtimeControls.menuRoot.getChildren() as TextRenderable[]
      const full = accessRows.find((row) => row.plainText.includes("Full access"))
      if (!full) throw new Error("full access row was not rendered")
      ui.composer.blur()
      expect(ui.composer.focused).toBe(false)
      await setup.mockMouse.click(full.x + 2, full.y)
      expect(ui.composer.focused).toBe(true)

      expect(scopes).toEqual([{
        project_path: "/tmp/nanobot-workspace",
        access_mode: "full",
        restrict_to_workspace: false,
      }])

      await setup.mockMouse.click(
        ui.runtimeControls.modelText.x + 2,
        ui.runtimeControls.modelText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      ui.composer.blur()
      await setup.mockMouse.click(ui.status.x, ui.status.y)
      expect(ui.runtimeControls.visible).toBe(false)
      expect(ui.composer.focused).toBe(true)

      await setup.mockMouse.click(
        ui.runtimeControls.accessText.x + 2,
        ui.runtimeControls.accessText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      ui.composer.blur()
      await setup.mockMouse.click(ui.status.x, ui.status.y)
      expect(ui.runtimeControls.visible).toBe(false)
      expect(ui.composer.focused).toBe(true)
      expect(settingsRequests).toBe(1)
      expect(workspaceRequests).toBe(1)

      expect((app as unknown as { activeTurn: boolean }).activeTurn).toBe(true)
      app.accept({ event: "goal_status", chat_id: "chat", status: "idle" })
    } finally {
      globalThis.fetch = original
    }
  })

  test("switches sessions only through the sessions command", async () => {
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return Promise.resolve(new Response(JSON.stringify({
        sessions: [
          { key: "websocket:chat", title: "Current chat", preview: "Current work" },
          { key: "websocket:other", title: "Release checklist", preview: "Ship it" },
        ],
      })))
    }) as typeof fetch
    const attached: string[] = []
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client([], attached),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      composer: TextareaRenderable
      sessionMenu: { visible: boolean; root: { getChildren(): unknown[] } }
      title: { getChildren(): unknown[] }
    }

    try {
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
      await setup.renderOnce()
      const titleItems = ui.title.getChildren() as TextRenderable[]
      expect(titleItems.some((item) => item.id === "nanobot-tui-title-text")).toBe(false)
      expect(ui.sessionMenu.visible).toBe(false)

      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionMenu.visible)
      await setup.flush()
      expect(ui.composer.placeholder).toBe("Search sessions")

      const rows = ui.sessionMenu.root.getChildren() as TextRenderable[]
      const other = rows.find((row) => row.plainText.includes("Release checklist"))
      if (!other) throw new Error("other session row was not rendered")
      ui.composer.blur()
      await setup.mockMouse.click(other.x + 2, other.y)
      await waitUntil(() => attached.length === 1)
      expect(attached).toEqual(["other"])
      expect(ui.sessionMenu.visible).toBe(false)
      expect(ui.composer.focused).toBe(true)
    } finally {
      globalThis.fetch = original
    }
  })

  test("offers clickable recovery actions without letting a late response revive stale state", async () => {
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const calls: Array<{ action: string; chatId: string; recoveryId: string }> = []
    let deferredResolve: ((state: RecoveryState) => void) | undefined
    const recoveryClient = client()
    recoveryClient.updateRecovery = (action, chatId, recoveryId) => {
      calls.push({ action, chatId, recoveryId })
      if (recoveryId === "recovery-1") {
        return Promise.resolve({ status: "resuming", recovery_id: recoveryId })
      }
      if (action === "dismiss") {
        return Promise.resolve({ status: "recovered", recovery_id: recoveryId })
      }
      return new Promise((resolve) => { deferredResolve = resolve })
    }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      recoveryClient,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({
      event: "attached",
      chat_id: "chat",
      recovery_state: {
        status: "awaiting_user",
        recovery_id: "recovery-1",
        reason: "tool execution interrupted",
      },
    })
    const ui = app as unknown as {
      activeTurn: boolean
      composer: TextareaRenderable
      recoveryNotice: {
        visible: boolean
        dismiss: TextRenderable
        resume: TextRenderable
      }
      status: TextRenderable
    }

    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("⚠ Task interrupted")
    expect(setup.captureCharFrame()).toContain("Tools will not replay automatically")
    expect(ui.status.plainText).toContain("continue or dismiss")
    expect(ui.activeTurn).toBe(false)
    expect(ui.composer.focused).toBe(true)

    await setup.mockMouse.click(ui.recoveryNotice.resume.x + 1, ui.recoveryNotice.resume.y)
    await waitUntil(() => calls.length === 1 && ui.activeTurn)
    expect(calls[0]).toEqual({
      action: "continue",
      chatId: "chat",
      recoveryId: "recovery-1",
    })
    expect(ui.recoveryNotice.visible).toBe(false)
    expect(ui.status.plainText).toContain("Continuing")

    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "awaiting_user",
      recovery_id: "recovery-2",
    })
    await setup.renderOnce()
    await setup.mockMouse.click(ui.recoveryNotice.resume.x + 1, ui.recoveryNotice.resume.y)
    await waitUntil(() => calls.length === 2)
    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "recovered",
      recovery_id: "recovery-2",
    })
    deferredResolve?.({ status: "resuming", recovery_id: "recovery-2" })
    await Bun.sleep(1)

    expect(ui.recoveryNotice.visible).toBe(false)
    expect(ui.activeTurn).toBe(false)
    expect(ui.composer.focused).toBe(true)

    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "awaiting_user",
      recovery_id: "recovery-unavailable",
      can_continue: false,
    })
    await setup.renderOnce()
    const unavailableFrame = setup.captureCharFrame()
    expect(unavailableFrame).toContain("can’t be resumed safely")
    expect(unavailableFrame).not.toContain("Continue")
    expect(ui.status.plainText).toContain("dismiss to start a new message")

    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "awaiting_user",
      recovery_id: "recovery-3",
    })
    await setup.renderOnce()
    await setup.mockMouse.click(ui.recoveryNotice.dismiss.x + 1, ui.recoveryNotice.dismiss.y)
    await waitUntil(() => calls.length === 3 && !ui.recoveryNotice.visible)
    expect(calls[2]).toEqual({
      action: "dismiss",
      chatId: "chat",
      recoveryId: "recovery-3",
    })

    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "awaiting_user",
      recovery_id: "recovery-4",
      can_continue: false,
    })
    await setup.renderOnce()
    expect(ui.recoveryNotice.resume.visible).toBe(false)
    expect(ui.recoveryNotice.dismiss.visible).toBe(true)
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
      expect(occurrences(frame, "Current chat")).toBe(0)
    } finally {
      globalThis.fetch = original
    }
  })

  test("shows compact session context without exposing private reasoning", async () => {
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
      runtimeControls: { contextText: { plainText: string } }
    }

    try {
      ui.composer.setText("/context")
      ui.composer.submit()
      await waitUntil(() => ui.contextPanel.visible)
      await setup.flush()
      expect(ui.runtimeControls.contextText.plainText).toContain("~2.2k ctx")
      const frame = setup.captureCharFrame()

      expect(frame).toContain("~2.2k tokens · 10 replay · 16 archived")
      expect(frame).toContain("The earlier turns agreed on a release plan.")
      expect(frame).not.toContain("Agent context")
      expect(frame).not.toContain("summary active")
      expect(frame).not.toContain("memory, instructions, and skills are added separately")

      setup.resize(40, 10)
      await setup.renderOnce()
      const compact = setup.captureCharFrame()
      expect(occurrences(compact, "Agent context")).toBe(0)
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
      expect(frame).not.toContain("Steer this turn…")
      expect(frame).not.toContain("Ask a follow-up…")
      if (width >= 40 && height >= 9) {
        expect(occurrences(frame, "Enter send now · Tab send next")).toBe(1)
      } else if (width >= 28 && height >= 9) {
        expect(occurrences(frame, "Enter now · Tab next")).toBe(1)
      }
      expect(occurrences(frame, "default ▾")).toBe(height >= 14 ? 1 : 0)
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

  test("reflows markdown tables without clipping columns or cell content", async () => {
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({
      event: "delta",
      chat_id: "chat",
      text: [
        "| Who | Content | Engagement |",
        "| --- | --- | --- |",
        "| @owner | A longer explanation that keeps context readable | 13 likes / 6 RT |",
        "| @reader | Short follow-up | Low interaction |",
      ].join("\n"),
    })
    app.accept({ event: "stream_end", chat_id: "chat" })
    app.accept({ event: "turn_end", chat_id: "chat" })

    for (const width of [96, 54, 96]) {
      setup.resize(width, 24)
      await setup.flush()
      const rendered = setup.captureCharFrame().replace(/\s+/gu, " ")

      expect(rendered).toContain("Who")
      expect(rendered).toContain("Content")
      expect(rendered).toContain("Engagement")
      expect(rendered).toContain("@owner")
      expect(rendered).toContain("longer explanation")
      expect(rendered).toContain("keeps context")
      expect(rendered).toContain("readable")
      expect(rendered).toContain("13 likes / 6")
      expect(rendered).toContain("RT")
      expect(rendered).toContain("Low interaction")
      expect((app as unknown as {
        transcript: { root: HiddenScrollBox }
      }).transcript.root.horizontalScrollBar.visible).toBeFalse()
    }
  })

  test("renders assistant LaTeX as Unicode text without changing code", async () => {
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({
      event: "delta",
      chat_id: "chat",
      text: [
        "缓存率：",
        "\\[\\text{缓存率}=\\frac{\\text{cached input tokens}}{\\text{total input tokens}}\\]",
        "结果：\\(66{,}000 \\times 94\\% \\approx 62{,}040\\)",
        "`\\(code\\)`",
      ].join("\n"),
    })
    app.accept({ event: "stream_end", chat_id: "chat" })
    const transcript = (app as unknown as {
      transcript: { assistant(content: string): void }
    }).transcript
    transcript.assistant("历史公式：\\(x_1^2 + y_2^2 = z^2\\)")
    await setup.flush()
    const frame = setup.captureCharFrame()

    expect(frame).toContain("缓存率 = cached input tokens / total input tokens")
    expect(frame).toContain("66,000 × 94% ≈ 62,040")
    expect(frame).toContain("历史公式：x₁² + y₂² = z²")
    expect(frame).toContain("\\(code\\)")
    expect(frame).not.toContain("\\frac")
    expect(frame).not.toContain("\\text")
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
        syntaxStyle: { getStyle(name: string): { fg?: { toInts(): number[] } } | undefined } | null
      }
      transcript: {
        markdown: Set<{ syntaxStyle: object }>
        frames: Set<{ borderColor: { toInts(): number[] } }>
        userRows: Set<{ backgroundColor: { intent: string; toInts(): number[] } }>
        userMessages: Set<{ renderable: TextRenderable }>
        user(content: string, turnId?: string, media?: Array<{ kind: "image"; name: string }>): void
      }
    }
    internals.transcript.user("Existing question", undefined, [{
      kind: "image",
      name: "clipboard-image-1.png",
    }])
    const userRow = [...internals.transcript.userRows][0]
    const userMessage = [...internals.transcript.userMessages][0]
    const markdown = [...internals.transcript.markdown][0]
    const sessionFrame = [...internals.transcript.frames][0]
    const darkSyntax = markdown?.syntaxStyle
    const darkComposerSyntax = internals.composer.syntaxStyle

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
    expect(internals.composer.syntaxStyle).not.toBe(darkComposerSyntax)
    expect(internals.composer.syntaxStyle?.getStyle("image.placeholder")?.fg?.toInts().slice(0, 3))
      .toEqual([185, 77, 11])
    const recolored = userMessage?.renderable.content as StyledText
    expect(recolored.chunks.find(({ text }) => text === "[Image #1]")?.fg?.toInts().slice(0, 3))
      .toEqual([185, 77, 11])
  })

  test("distinguishes the composer with a quiet focus edge", async () => {
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
        borderColor: { toInts(): number[] }
        backgroundColor: { toInts(): number[] }
      }
      composer: {
        backgroundColor: { toInts(): number[] }
        placeholderColor: { toInts(): number[] }
      }
    }

    expect(internals.composerFrame.border).toEqual(["left"])
    expect(internals.composerFrame.borderColor.toInts().slice(0, 3)).toEqual([185, 77, 11])
    expect(internals.composerFrame.backgroundColor.toInts().slice(0, 3)).toEqual([240, 240, 240])
    expect(internals.composer.backgroundColor.toInts().slice(0, 3)).toEqual([240, 240, 240])
    expect(internals.composer.placeholderColor.toInts().slice(0, 3)).toEqual([111, 111, 120])

    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => internals.ready)
    await setup.renderOnce()

    const composerLine = setup.captureCharFrame().split("\n")
      .find((line) => line.includes("Ask nanobot anything")) || ""
    expect(composerLine).toContain("│")
    expect(composerLine).not.toContain("┌")
    expect(composerLine).not.toContain("┐")
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

  test("uses the idle footer for model telemetry instead of permanent shortcuts", async () => {
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({
      event: "turn_end",
      chat_id: "chat",
      latency_ms: 1700,
      usage: {
        prompt_tokens: 1200,
        completion_tokens: 80,
        cached_tokens: 900,
        generation_ms: 1600,
        measured_completion_tokens: 80,
        ttft_ms: 240,
        timed_requests: 1,
      },
      context_window_tokens: 128_000,
    })
    await setup.flush()

    const footer = setup.captureCharFrame().split("\n").find((line) => line.includes("Ready · 1.7s")) || ""
    expect(footer).toContain("Ready · 1.7s")
    expect(footer).toContain("50 tok/s")
    expect(footer).toContain("1.2K in (75% cached) · 80 out")
    expect(footer).not.toContain("TTFT")
    expect(footer).not.toContain("enter send")

    app.accept({ event: "reasoning_delta", chat_id: "chat", text: "hidden" })
    await Bun.sleep(130)
    await setup.renderOnce()
    const activeFooter = setup.captureCharFrame().split("\n").find((line) => line.includes("Thinking")) || ""
    expect(activeFooter).not.toContain("ctrl+c stop")
    expect(activeFooter).not.toContain("enter steer")
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

  test("overlaps automatic terminal detection with connection startup", async () => {
    setup = await createRenderer({ width: 72, height: 20, screenMode: "alternate-screen" })
    let connected = false
    let rendered = false
    let resolveMode: (mode: "light") => void = () => undefined
    setup.renderer.start = () => { rendered = true }
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
    expect(connected).toBe(true)
    expect(rendered).toBe(true)

    resolveMode("light")
    await starting
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
    expect(ui.status.plainText).toBe("Nanobot unavailable · restart nanobot")
    expect(ui.status.plainText).not.toContain("gateway")
    expect(ui.status.plainText).not.toContain("127.0.0.1")
    expect(ui.status.plainText).not.toContain("HTTP")
    expect(ui.status.plainText).not.toContain("attempt")
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
      expect(ui.status.plainText).toContain("Not sent · press Enter to retry when ready")

      resolveReconnect(new Response(JSON.stringify({
        messages: [{ role: "assistant", content: "restored history" }],
        page: { has_more_before: false },
      })))
      await waitUntil(() => ui.ready)
      expect(ui.status.plainText).toBe("Not sent · press Enter to retry")
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
      handleStatus(
        status: "reconnecting" | "connected",
        detail?: string,
        info?: { endpoint: string; attempt: number; elapsedMs: number },
      ): void
    }

    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    connection.handleStatus("reconnecting", "connection closed", {
      endpoint: "127.0.0.1:8769",
      attempt: 1,
      elapsedMs: 0,
    })
    connection.handleStatus("connected")
    composer.setText("draft before attach")
    composer.submit()
    await Bun.sleep(5)
    composer.submit()
    await Bun.sleep(5)

    expect(sent).toEqual([])
    expect(composer.plainText).toBe("draft before attach")

    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
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

describe("NanobotTui with a Herdr pane title reporter", () => {
  test("keeps the full terminal experience while reporting task titles", async () => {
    const setup = await createTestRenderer({ width: 80, height: 22, screenMode: "alternate-screen" })
    const titles: string[] = []
    let released = false
    const host: TuiHost = {
      reportTitle(title) { titles.push(title) },
      release() { released = true },
    }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
      host,
    )
    const ui = app as unknown as {
      composer: TextareaRenderable
      composerFrame: BoxRenderable
    }

    await setup.mockInput.typeText("/")
    await setup.flush()
    const commandFrame = setup.captureCharFrame()
    expect(commandFrame).toContain("/sessions")
    expect(commandFrame).toContain("/new-chat")
    expect(commandFrame).toContain("/branch")
    setup.mockInput.pressEscape()
    ui.composer.setText("")

    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({
      event: "user_message",
      chat_id: "chat",
      text: "Ship the Herdr integration",
      turn_id: "turn-1",
      starts_turn: true,
    })
    app.accept({
      event: "message",
      chat_id: "chat",
      text: "",
      kind: "tool_hint",
      tool_events: [{ phase: "end", call_id: "read", name: "read_file", arguments: { path: "app.ts" } }],
    })
    await setup.flush()
    const activeFrame = setup.captureCharFrame()
    expect(activeFrame).toContain(">_  nanobot")
    expect(activeFrame).toContain("default ▾")
    expect(occurrences(activeFrame, "› Ship the Herdr integration")).toBe(1)
    expect(occurrences(activeFrame, "app.ts")).toBe(1)
    expect(ui.composer.placeholder).toBe("Enter send now · Tab send next")
    expect(ui.composerFrame.height).toBe(3)
    expect(titles).toEqual(["Ship the Herdr integration"])

    app.accept({
      event: "turn_end",
      chat_id: "chat",
      turn_id: "turn-1",
      goal_state: {
        active: false,
        status: "blocked",
        ui_summary: "Approval required",
      },
    })
    app.accept({
      event: "user_message",
      chat_id: "chat",
      text: "Approved",
      turn_id: "turn-2",
      starts_turn: true,
    })

    expect(titles).toEqual(["Ship the Herdr integration", "Approved"])

    app.stop()
    expect(released).toBe(true)
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
        NANOBOT_TUI_CHAT_ID: "resume-chat",
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
    expect(output.indexOf("\x1b[?1049l")).toBeLessThan(output.indexOf("Resume with:"))
    expect(output).toContain(
      "Resume with: nanobot agent --session websocket:resume-chat\n",
    )
  })
}
