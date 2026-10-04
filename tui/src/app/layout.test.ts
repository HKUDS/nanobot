import { afterEach, describe, expect, test } from "bun:test"
import { BoxRenderable, CliRenderEvents, StyledText, TextareaRenderable, TextAttributes, TextRenderable } from "@opentui/core"
import { MockTreeSitterClient, TestRecorder, setRendererCapabilities, createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"
import { NanobotTui } from "./app"
import type { Transcript } from "../rendering/transcript"
import { options, client, mount, waitUntil, occurrences, contrastRatio, HiddenScrollBox } from "./test-support"

describe("NanobotTui layout and themes", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  const createRenderer = (rendererOptions: Parameters<typeof createTestRenderer>[0]) => (
    createTestRenderer(rendererOptions)
  )
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

  test("keeps model and access details in the composer controls only", async () => {
    setup = await createRenderer({ width: 100, height: 24, screenMode: "alternate-screen" })
    NanobotTui.mount(
      setup.renderer,
      {
        ...options,
        model: "provider/resolved-model",
        modelPreset: "selected-preset",
        access: "full access",
      },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    await setup.renderOnce()

    const frame = setup.captureCharFrame()
    expect(frame).not.toContain("provider/resolved-model")
    expect(frame).toContain("selected-preset ▾")
    expect(occurrences(frame, "full access")).toBe(1)
    expect(frame).toContain(options.workspace)
  })

  test("uses the available transcript width before wrapping the workspace", async () => {
    setup = await createRenderer({ width: 100, height: 24, screenMode: "alternate-screen" })
    const workspace = String.raw`D:\Documents\GitHub\nanobot\.worktrees\responsive-header-fixture`
    NanobotTui.mount(
      setup.renderer,
      { ...options, workspace },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    await setup.renderOnce()

    const frame = setup.captureCharFrame()
    const headerWidth = () => {
      const border = setup?.captureCharFrame().split("\n").find((line) => line.includes("╭"))
      if (!border) throw new Error("header border was not rendered")
      return border.trim().length
    }

    expect(frame).toContain(workspace)
    expect(headerWidth()).toBe(setup.renderer.width - 4)

    setup.resize(120, 24)
    await setup.renderOnce()
    expect(headerWidth()).toBe(setup.renderer.width - 4)
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

  test("keeps finalized streamed Markdown link labels clickable", async () => {
    setup = await createRenderer({ width: 100, height: 24, screenMode: "alternate-screen" })
    setRendererCapabilities(setup.renderer, { hyperlinks: true })
    const label = "HKUDS/nanobot#1234"
    const url = "https://github.com/HKUDS/nanobot/pull/1234"
    const content = `PR updated: [${label}](${url})`
    const labelStart = content.indexOf(label)
    const urlStart = content.indexOf(url)
    const treeSitterClient = new MockTreeSitterClient({ autoResolveTimeout: 0 })
    treeSitterClient.setMockResult({
      highlights: [
        [labelStart - 1, labelStart, "markup.link"],
        [labelStart, labelStart + label.length, "markup.link.label"],
        [labelStart + label.length, urlStart, "markup.link"],
        [urlStart, urlStart + url.length, "markup.link.url"],
        [urlStart + url.length, content.length, "markup.link"],
      ],
    })
    const app = NanobotTui.mount(setup.renderer, options, client(), treeSitterClient)

    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "delta", chat_id: "chat", text: content })
    app.accept({ event: "stream_end", chat_id: "chat" })
    app.accept({ event: "turn_end", chat_id: "chat" })
    await setup.flush()

    const lines = setup.captureCharFrame().split("\n")
    const y = lines.findIndex((line) => line.includes(label))
    const x = y >= 0 ? lines[y]!.indexOf(label) : -1
    expect([x, y]).not.toContain(-1)

    for (let offset = 0; offset < label.length; offset += 1) {
      expect(setup.renderer.getLinkAt(x + offset, y)).toBe(url)
    }
  })

  test("keeps streamed fenced code visible while completing the response", async () => {
    setup = await createRenderer({ width: 100, height: 30, screenMode: "alternate-screen" })
    const app = mount(setup)
    const response = [
      "Commit types:",
      "",
      "```text",
      "feat:",
      "fix:",
      "perf:",
      "docs:",
      "test:",
      "refactor:",
      "chore:",
      "```",
      "",
      "Include the reason in the body.",
    ].join("\n")

    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({ event: "delta", chat_id: "chat", text: response })
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("feat:")

    const recorder = new TestRecorder(setup.renderer)
    recorder.rec()
    app.accept({ event: "stream_end", chat_id: "chat" })
    app.accept({ event: "turn_end", chat_id: "chat" })
    await setup.flush()
    recorder.stop()

    expect(recorder.recordedFrames.length).toBeGreaterThan(0)
    expect(recorder.recordedFrames.every(({ frame }) => frame.includes("feat:"))).toBeTrue()
    expect(recorder.recordedFrames.every(({ frame }) => /│\s+feat:/u.test(frame))).toBeTrue()
    expect(recorder.recordedFrames.every(({ frame }) => (
      frame.includes("Include the reason in the body.")
    ))).toBeTrue()
  })

  test("renders fenced plain text from light-theme history", async () => {
    setup = await createRenderer({ width: 100, height: 30, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, theme: "light" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const response = [
      "Commit types:",
      "",
      "```text",
      "feat:",
      "fix:",
      "perf:",
      "docs:",
      "test:",
      "refactor:",
      "chore:",
      "```",
      "",
      "Include the reason in the body.",
    ].join("\n")
    const transcript = (app as unknown as { transcript: Transcript }).transcript

    transcript.history([{ role: "assistant", content: response }])
    await setup.flush()

    const codeLine = setup.captureSpans().lines.find((line) => (
      line.spans.some((span) => span.text.includes("feat:"))
    ))
    const code = codeLine?.spans.find((span) => span.text.includes("feat:"))
    const rail = codeLine?.spans.find((span) => span.text.includes("│"))
    const frame = setup.captureCharFrame()

    expect(frame).toContain("feat:")
    expect(frame).toMatch(/│\s+feat:/u)
    expect(code?.fg.toInts().slice(0, 3)).toEqual([24, 24, 27])
    expect(rail?.fg.toInts().slice(0, 3)).toEqual([212, 212, 216])
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
        markdown: Set<{ fg?: { toInts(): number[] }; syntaxStyle: object }>
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
    expect(markdown?.fg?.toInts().slice(0, 3)).toEqual([24, 24, 27])
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
    expect(headerBorder.trim().length).toBe(setup.renderer.width - 4)

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

  test("aligns footer labels with transcript content", async () => {
    setup = await createRenderer({ width: 72, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    ;(app as unknown as { transcript: { user(content: string): void } })
      .transcript.user("Aligned message")
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    await setup.renderOnce()

    const lines = setup.captureCharFrame().split("\n")
    const lineContaining = (needle: string): string => {
      const line = lines.find((candidate) => candidate.includes(needle))
      if (!line) throw new Error(`${needle} was not rendered`)
      return line
    }
    const messageLine = lineContaining("Aligned message")
    const composerLine = lineContaining("Ask nanobot anything")
    const contentColumn = messageLine.indexOf("Aligned message")

    expect(lineContaining("default ▾").indexOf("default ▾")).toBe(contentColumn)
    expect(lineContaining("Ready").indexOf("Ready")).toBe(contentColumn)
    expect(composerLine.indexOf("│")).toBe(messageLine.indexOf("›"))
    expect(composerLine.indexOf("Ask nanobot anything")).toBe(contentColumn)
  })

  test("shows context usage in the idle footer", async () => {
    setup = await createRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({
      event: "turn_end",
      chat_id: "chat",
      latency_ms: 1700,
      usage: {
        context_tokens: 14_700,
      },
      context_window_tokens: 128_000,
    })
    await setup.flush()

    const footer = setup.captureCharFrame().split("\n").find((line) => line.includes("Ready · 1.7s")) || ""
    expect(footer).toContain("Ready · 1.7s")
    expect(footer).toContain("11% context")
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

  test.each(["dark", "light"] as const)("uses terminal defaults until a late %s theme response", async (mode) => {
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
    const ui = app as unknown as {
      composer: TextareaRenderable
      status: TextRenderable
      shimmerFrame: number
      renderActiveStatus(): void
    }
    expect(ui.composer.textColor.intent).toBe("default")
    expect(ui.composer.backgroundColor.intent).toBe("default")
    expect([...transcript.userRows][0]?.backgroundColor.intent).toBe("default")
    app.accept({ event: "delta", chat_id: "chat", text: "Readable answer" })
    app.accept({ event: "stream_end", chat_id: "chat" })
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("Readable answer")
    for (const line of setup.captureSpans().lines) {
      for (const span of line.spans) {
        if (span.text.trim()) expect(span.fg.intent).toBe("default")
      }
    }
    // Keep the fallback readable without guessed RGB colors, but do not freeze
    // the active-status animation while waiting for a terminal theme response.
    app.accept({ event: "reasoning_delta", chat_id: "chat", text: "thinking" })
    await setup.flush()
    const terminalFrame = () => (ui.status.content as StyledText).chunks
      .slice(0, "Thinking".length)
      .map((chunk) => chunk.attributes ?? 0)
    const firstFrame = terminalFrame()
    ui.shimmerFrame += 1
    ui.renderActiveStatus()
    const secondFrame = terminalFrame()
    expect(firstFrame).toContain(TextAttributes.BOLD)
    expect(secondFrame).not.toEqual(firstFrame)
    for (const chunk of (ui.status.content as StyledText).chunks) {
      expect(chunk.fg?.intent).toBe("default")
    }

    setup.renderer.emit(CliRenderEvents.THEME_MODE, mode)
    await setup.flush()
    const shimmerColors = new Set(
      (ui.status.content as StyledText).chunks
        .slice(0, "Thinking".length)
        .map((chunk) => chunk.fg?.toInts().slice(0, 3).join(",")),
    )
    expect(shimmerColors.size).toBeGreaterThan(1)
    expect(ui.composer.textColor.intent).toBe("rgb")
    expect(ui.composer.textColor.toInts().slice(0, 3)).toEqual(
      mode === "light" ? [24, 24, 27] : [236, 237, 238],
    )
    expect([...transcript.userRows][0]?.backgroundColor.intent).toBe("rgb")
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

    setup.renderer.emit(CliRenderEvents.THEME_MODE, "dark")
    assertContrast()
    expect(internals.palette.accent).toBe("#EF8E30")
    expect(internals.palette.user).toBe("#EF8E30")
    setup.renderer.emit(CliRenderEvents.THEME_MODE, "light")
    assertContrast()
    expect(internals.palette.accent).toBe("#B94D0B")
    expect(internals.palette.user).toBe("#B94D0B")
  })
})
