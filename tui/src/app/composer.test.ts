import { afterEach, describe, expect, test } from "bun:test"
import { StyledText, TextareaRenderable, TextAttributes, TextRenderable } from "@opentui/core"
import { MockTreeSitterClient, createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"
import { NanobotTui } from "./app"
import type { MessageOptions, SkillCandidate, SlashCommand } from "../client"
import type { ClipboardImageReader } from "../composer/clipboard-image"
import { options, client, mount, waitUntil, occurrences } from "./test-support"

describe("NanobotTui composer", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  const createRenderer = (rendererOptions: Parameters<typeof createTestRenderer>[0]) => (
    createTestRenderer(rendererOptions)
  )
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
    expect(placeholderStyle?.fg?.intent).toBe("default")
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
    expect(imageChunk?.fg?.intent).toBe("default")

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
    ui.composer.cursorOffset = 10
    setup.mockInput.pressArrow("left", { shift: true })
    await waitUntil(() => ui.composer.cursorOffset === 0)
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

  test.each(["enter", "tab"])("submits a running goal with %s", async (key) => {
    const sent: string[] = []
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const transport = client(sent)
    transport.send = (content) => {
      sent.push(content)
      return sent.length === 1 ? "active" : "followup"
    }
    const app = NanobotTui.mount(
      setup.renderer, options, transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      ready: boolean
      activeTurnId: string | null
      composer: TextareaRenderable
      commandMenu: { setCommands(commands: SlashCommand[]): void }
      queuePreview: { root: { visible: boolean } }
    }
    await waitUntil(() => ui.ready)
    ui.commandMenu.setCommands([{
      command: "/goal",
      title: "Goal",
      description: "Start sustained work",
      argHint: "<goal>",
      lifecycle: "agent_turn_with_args",
      acceptsArgs: true,
    }])
    ui.composer.setText("Discuss the migration plan")
    setup.mockInput.pressEnter()
    await waitUntil(() => sent.length === 1)
    await waitUntil(() => ui.activeTurnId === "active")

    const goal = "/goal implement the plan we discussed"
    ui.composer.setText(goal)
    if (key === "enter") setup.mockInput.pressEnter()
    else setup.mockInput.pressTab()
    await waitUntil(() => ui.composer.plainText === "")

    expect(sent).toEqual(key === "enter" ? ["Discuss the migration plan", goal] : ["Discuss the migration plan"])
    expect(ui.activeTurnId).toBe("active")
    expect(ui.queuePreview.root.visible).toBe(key === "tab")
    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "active" })
    await waitUntil(() => sent.length === 2)
    expect(sent).toEqual(["Discuss the migration plan", goal])
    expect(ui.queuePreview.root.visible).toBeFalse()
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
})
