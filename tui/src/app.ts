import {
  BoxRenderable,
  CliRenderEvents,
  MarkdownRenderable,
  RGBA,
  ScrollBoxRenderable,
  SyntaxStyle,
  TextareaRenderable,
  TextAttributes,
  TextRenderable,
  createCliRenderer,
  getTreeSitterClient,
  type CliRenderer,
  type KeyEvent,
} from "@opentui/core"

import {
  NanobotClient,
  fetchHistory,
  type ConnectionStatus,
  type HistoryMessage,
  type InboundEvent,
} from "./protocol"

interface AppOptions {
  wsUrl: string
  apiUrl: string
  apiToken: string
  chatId?: string
  model: string
  workspace: string
  version: string
  access: string
}

interface Palette {
  background: string
  panel: string
  text: string
  muted: string
  faint: string
  border: string
  accent: string
  success: string
  error: string
  user: string
}

const DARK: Palette = {
  background: "#0E0F11",
  panel: "#17181B",
  text: "#ECEDEE",
  muted: "#A1A1AA",
  faint: "#71717A",
  border: "#3F3F46",
  accent: "#8B7CF6",
  success: "#5CC489",
  error: "#F87171",
  user: "#60A5FA",
}

const LIGHT: Palette = {
  background: "#FAFAFA",
  panel: "#F4F4F5",
  text: "#18181B",
  muted: "#71717A",
  faint: "#A1A1AA",
  border: "#D4D4D8",
  accent: "#6D5BD0",
  success: "#218358",
  error: "#DC2626",
  user: "#2563EB",
}

function syntaxStyle(palette: Palette): SyntaxStyle {
  const color = (value: string) => {
    const parsed = RGBA.fromHex(value)
    return { fg: parsed }
  }
  return SyntaxStyle.fromStyles({
    default: color(palette.text),
    keyword: { ...color(palette.accent), bold: true },
    string: color(palette.success),
    comment: { ...color(palette.muted), italic: true },
    number: color(palette.user),
    function: color("#C26A25"),
    type: color("#168A96"),
    variable: color(palette.text),
    property: color(palette.user),
    "markup.heading": { ...color(palette.accent), bold: true },
    "markup.strong": { ...color(palette.text), bold: true },
    "markup.italic": { ...color(palette.muted), italic: true },
    "markup.link": { ...color(palette.user), underline: true },
    "markup.link.label": { ...color(palette.user), underline: true },
    "markup.link.url": { ...color(palette.user), underline: true },
    "markup.raw": color("#C26A25"),
    conceal: color(palette.faint),
  })
}

class Transcript {
  readonly root: ScrollBoxRenderable
  private live: { row: BoxRenderable; text: TextRenderable; content: string } | null = null
  private wrote = false
  private nextId = 0

  constructor(
    private readonly renderer: CliRenderer,
    private palette: Palette,
  ) {
    this.root = new ScrollBoxRenderable(renderer, {
      id: "nanobot-tui-transcript",
      width: "100%",
      minHeight: 0,
      flexGrow: 1,
      scrollX: false,
      scrollY: true,
      stickyScroll: true,
      stickyStart: "bottom",
      viewportCulling: true,
      contentOptions: {
        flexDirection: "column",
        paddingTop: 1,
        paddingBottom: 1,
        paddingLeft: 1,
        paddingRight: 1,
      },
      verticalScrollbarOptions: { visible: false },
      horizontalScrollbarOptions: { visible: false },
    })
    // Constructor options are applied before ScrollBarRenderable starts managing
    // its own visibility. Assigning through the setters keeps both bars hidden.
    this.root.verticalScrollBar.visible = false
    this.root.horizontalScrollBar.visible = false
  }

  setPalette(palette: Palette): void {
    this.palette = palette
  }

  header(options: AppOptions): void {
    const lines = [
      `>_  nanobot  v${options.version}`,
      `${options.model}  ·  ${options.access}`,
      options.workspace,
    ]
    this.writeText(lines.join("\n"), this.palette.text, true, true)
  }

  async history(messages: HistoryMessage[]): Promise<void> {
    for (const message of messages) {
      if (message.role === "user") this.user(message.content)
      else this.assistant(message.content)
    }
  }

  user(content: string): void {
    this.writeText(`› ${content}`, this.palette.user, true)
  }

  assistant(content: string): void {
    if (!content.trim()) return
    this.writeMarkdown(content)
  }

  notice(content: string, error = false): void {
    this.writeText(content, error ? this.palette.error : this.palette.muted)
  }

  stream(delta: string): void {
    if (!delta) return
    if (!this.live) {
      const row = this.createRow()
      const text = new TextRenderable(this.renderer, {
        id: this.id("assistant-stream"),
        content: "",
        width: "100%",
        wrapMode: "word",
        fg: this.palette.text,
      })
      row.add(text)
      this.root.add(row)
      this.live = { row, text, content: "" }
      this.wrote = true
    }
    this.live.content += delta
    this.live.text.content = this.live.content
  }

  finishStream(fallback = ""): void {
    const content = this.live?.content || fallback
    if (this.live) {
      this.root.remove(this.live.row)
      this.live.row.destroy()
      this.live = null
    }
    if (content.trim()) this.assistant(content)
  }

  destroy(): void {
    this.live = null
  }

  private id(prefix: string): string {
    this.nextId += 1
    return `${prefix}-${this.nextId}`
  }

  private createRow(framed = false): BoxRenderable {
    return new BoxRenderable(this.renderer, {
      id: this.id(framed ? "text-frame" : "text-row"),
      width: "100%",
      marginTop: this.wrote ? 1 : 0,
      border: framed,
      borderStyle: "rounded",
      borderColor: this.palette.border,
      paddingLeft: 1,
      paddingRight: 1,
      flexDirection: "column",
    })
  }

  private writeText(
    content: string,
    color: string,
    bold = false,
    framed = false,
  ): void {
    const row = this.createRow(framed)
    row.add(
      new TextRenderable(this.renderer, {
        id: this.id("text"),
        content,
        width: "100%",
        wrapMode: "word",
        fg: color,
        attributes: bold ? TextAttributes.BOLD : 0,
      }),
    )
    this.root.add(row)
    this.wrote = true
  }

  private writeMarkdown(content: string): void {
    const row = this.createRow()
    const markdown = new MarkdownRenderable(this.renderer, {
      id: this.id("markdown"),
      content,
      width: "100%",
      syntaxStyle: syntaxStyle(this.palette),
      streaming: false,
      internalBlockMode: "top-level",
      treeSitterClient: getTreeSitterClient(),
    })
    row.add(markdown)
    this.root.add(row)
    this.wrote = true
  }
}

export class NanobotTui {
  private readonly renderer: CliRenderer
  private readonly transcript: Transcript
  private readonly client: NanobotClient
  private readonly shell: BoxRenderable
  private readonly title: TextRenderable
  private readonly composerFrame: BoxRenderable
  private readonly composer: TextareaRenderable
  private readonly status: TextRenderable
  private readonly meta: TextRenderable
  private palette: Palette
  private activeTurn = false
  private lastProgress = ""
  private finalMessage = ""
  private historyLoaded = false
  private ready = false
  private shimmerFrame = 0
  private shimmerTimer: ReturnType<typeof setInterval> | null = null
  private quitting = false

  private constructor(renderer: CliRenderer, private readonly options: AppOptions) {
    this.renderer = renderer
    this.palette = renderer.themeMode === "light" ? LIGHT : DARK
    this.transcript = new Transcript(renderer, this.palette)
    this.client = new NanobotClient({
      url: options.wsUrl,
      chatId: options.chatId,
      onEvent: (event) => this.handleEvent(event),
      onStatus: (status, detail) => this.handleStatus(status, detail),
    })

    this.renderer.setBackgroundColor(this.palette.background)
    this.shell = new BoxRenderable(renderer, {
      id: "nanobot-tui-footer",
      width: "100%",
      height: "100%",
      paddingLeft: 1,
      paddingRight: 1,
      flexDirection: "column",
      backgroundColor: this.palette.background,
    })
    this.title = new TextRenderable(renderer, {
      id: "nanobot-tui-title",
      content: `nanobot  ·  ${options.model}`,
      height: 1,
      flexShrink: 0,
      fg: this.palette.muted,
    })
    this.composerFrame = new BoxRenderable(renderer, {
      id: "nanobot-tui-composer-frame",
      width: "100%",
      height: 3,
      flexShrink: 0,
      border: true,
      borderStyle: "rounded",
      borderColor: this.palette.border,
      paddingLeft: 1,
      paddingRight: 1,
      backgroundColor: this.palette.panel,
    })
    this.composer = new TextareaRenderable(renderer, {
      id: "nanobot-tui-composer",
      width: "100%",
      minHeight: 1,
      flexGrow: 1,
      wrapMode: "word",
      placeholder: "Ask nanobot anything",
      placeholderColor: this.palette.faint,
      textColor: this.palette.text,
      focusedTextColor: this.palette.text,
      backgroundColor: this.palette.panel,
      focusedBackgroundColor: this.palette.panel,
      cursorColor: this.palette.accent,
      showCursor: true,
      keyBindings: [
        { name: "return", action: "submit" },
        { name: "return", meta: true, action: "newline" },
      ],
      onSubmit: () => this.submit(),
    })
    this.status = new TextRenderable(renderer, {
      id: "nanobot-tui-status",
      content: "Connecting…",
      fg: this.palette.muted,
      height: 1,
      flexGrow: 1,
    })
    this.meta = new TextRenderable(renderer, {
      id: "nanobot-tui-meta",
      content: "enter send · alt+enter newline · ctrl+c stop",
      fg: this.palette.faint,
      height: 1,
    })

    const statusRow = new BoxRenderable(renderer, {
      id: "nanobot-tui-status-row",
      width: "100%",
      height: 1,
      flexShrink: 0,
      flexDirection: "row",
      justifyContent: "space-between",
    })
    this.composerFrame.add(this.composer)
    statusRow.add(this.status)
    statusRow.add(this.meta)
    this.shell.add(this.transcript.root)
    this.shell.add(this.title)
    this.shell.add(this.composerFrame)
    this.shell.add(statusRow)
    this.renderer.root.add(this.shell)

    this.renderer.keyInput.on("keypress", this.handleKey)
    this.renderer.on(CliRenderEvents.THEME_MODE, this.handleTheme)
    this.renderer.on(CliRenderEvents.RESIZE, this.handleResize)
    this.renderer.on(CliRenderEvents.DESTROY, this.handleDestroy)
    this.handleResize()
    this.composer.focus()
    this.transcript.header(options)
  }

  static async create(options: AppOptions): Promise<NanobotTui> {
    const renderer = await createCliRenderer({
      targetFps: 30,
      exitOnCtrlC: false,
      useMouse: true,
      screenMode: "alternate-screen",
      externalOutputMode: "passthrough",
      consoleMode: "disabled",
    })
    return NanobotTui.mount(renderer, options)
  }

  static mount(renderer: CliRenderer, options: AppOptions): NanobotTui {
    return new NanobotTui(renderer, options)
  }

  start(): void {
    this.client.connect()
    this.renderer.start()
  }

  private submit(): void {
    const content = this.composer.plainText.trim()
    if (!content) return
    if (!this.ready) {
      this.status.content = "Preparing chat…"
      return
    }
    if (["exit", "quit", "/exit", "/quit", ":q"].includes(content.toLowerCase())) {
      this.quit()
      return
    }
    if (this.activeTurn) {
      this.status.content = "A turn is already running · Ctrl+C to stop"
      return
    }
    try {
      this.client.send(content)
    } catch (error) {
      this.status.content = error instanceof Error ? error.message : String(error)
      return
    }
    this.composer.setText("")
    this.transcript.user(content)
    this.finalMessage = ""
    this.lastProgress = ""
    this.setActive(true)
  }

  private handleEvent(event: InboundEvent): void {
    if (event.event === "attached") {
      void this.prepareChat(event.chat_id)
      return
    }
    if (
      "chat_id" in event
      && event.chat_id
      && this.client.activeChatId
      && event.chat_id !== this.client.activeChatId
    ) return

    switch (event.event) {
      case "message_accepted":
        return
      case "delta":
        this.setActive(true)
        this.transcript.stream(event.text)
        return
      case "message":
        if (event.kind) {
          this.lastProgress = event.text.trim()
          if (this.lastProgress) this.status.content = this.lastProgress
          this.setActive(true)
        } else {
          this.finalMessage = event.text
        }
        return
      case "reasoning_delta":
        this.setActive(true)
        return
      case "stream_end":
        if (event.text) this.finalMessage = event.text
        return
      case "turn_end":
        this.transcript.finishStream(this.finalMessage)
        this.finalMessage = ""
        this.setActive(false)
        if (typeof event.latency_ms === "number") {
          this.status.content = `Ready · ${(event.latency_ms / 1000).toFixed(1)}s`
        }
        return
      case "turn_model_updated":
        this.title.content = `nanobot  ·  ${event.model_name}`
        return
      case "runtime_model_updated":
        this.title.content = `nanobot  ·  ${event.model_name}`
        return
      case "error":
        this.transcript.finishStream(this.finalMessage)
        this.transcript.notice(event.reason || event.detail || "Unknown gateway error", true)
        this.setActive(false)
        return
    }
  }

  private async prepareChat(chatId: string): Promise<void> {
    try {
      if (!this.historyLoaded && this.options.chatId) {
        this.historyLoaded = true
        const messages = await fetchHistory(this.options.apiUrl, this.options.apiToken, chatId)
        await this.transcript.history(messages)
      }
    } catch (error) {
      this.transcript.notice(error instanceof Error ? error.message : String(error), true)
    } finally {
      this.ready = true
      this.status.content = "Ready"
    }
  }

  private handleStatus(status: ConnectionStatus, detail?: string): void {
    if (status === "connected") {
      this.status.content = "Connected · preparing chat…"
      return
    }
    if (status === "connecting") {
      this.status.content = "Connecting…"
      return
    }
    if (status === "error") {
      this.status.content = detail || "Connection error"
      return
    }
    if (!this.quitting) this.status.content = "Disconnected"
  }

  private setActive(active: boolean): void {
    if (this.activeTurn === active) return
    this.activeTurn = active
    if (active) {
      this.shimmerFrame = 0
      this.shimmerTimer = setInterval(() => {
        const dots = "·".repeat((this.shimmerFrame++ % 3) + 1)
        const detail = this.lastProgress ? `  ${this.lastProgress}` : ""
        this.status.content = `Working ${dots}${detail}`
      }, 260)
      return
    }
    if (this.shimmerTimer) clearInterval(this.shimmerTimer)
    this.shimmerTimer = null
    this.lastProgress = ""
    this.status.content = "Ready"
  }

  private handleKey = (key: KeyEvent): void => {
    if (key.ctrl && key.name === "c") {
      key.preventDefault()
      if (this.activeTurn) {
        try {
          this.client.send("/stop")
          this.status.content = "Stopping…"
        } catch {
          this.setActive(false)
        }
      } else if (this.composer.plainText) {
        this.composer.setText("")
      } else {
        this.quit()
      }
      return
    }
    if (key.ctrl && key.name === "d" && !this.composer.plainText) {
      key.preventDefault()
      this.quit()
    }
  }

  private handleTheme = (): void => {
    this.palette = this.renderer.themeMode === "light" ? LIGHT : DARK
    this.transcript.setPalette(this.palette)
    this.renderer.setBackgroundColor(this.palette.background)
    this.shell.backgroundColor = this.palette.background
    this.composerFrame.backgroundColor = this.palette.panel
    this.composerFrame.borderColor = this.palette.border
    this.composer.backgroundColor = this.palette.panel
    this.composer.focusedBackgroundColor = this.palette.panel
    this.composer.textColor = this.palette.text
    this.composer.focusedTextColor = this.palette.text
    this.composer.cursorColor = this.palette.accent
    this.title.fg = this.palette.muted
    this.status.fg = this.palette.muted
    this.meta.fg = this.palette.faint
  }

  private handleResize = (): void => {
    this.meta.content = this.renderer.width >= 72
      ? "enter send · alt+enter newline · ctrl+c stop"
      : this.renderer.width >= 48
        ? "enter send · alt+enter newline"
        : ""
  }

  private quit(): void {
    if (this.quitting) return
    this.quitting = true
    this.client.close()
    this.renderer.destroy()
  }

  private handleDestroy = (): void => {
    if (this.shimmerTimer) clearInterval(this.shimmerTimer)
    this.transcript.destroy()
    this.client.close()
  }
}

export type { AppOptions }
