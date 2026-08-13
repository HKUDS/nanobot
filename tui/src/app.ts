import {
  BoxRenderable,
  CliRenderEvents,
  RGBA,
  SyntaxStyle,
  TextareaRenderable,
  TextRenderable,
  createCliRenderer,
  getTreeSitterClient,
  type CliRenderer,
  type KeyEvent,
  type ThemeMode,
  type TreeSitterClient,
} from "@opentui/core"

import {
  NanobotClient,
  fetchHistory,
  fetchSessions,
  fetchSlashCommands,
  type ConnectionStatus,
  type InboundEvent,
  type SlashCommand,
} from "./protocol"
import { CommandMenu, type CommandMenuTheme } from "./command-menu"
import { SessionMenu } from "./session-menu"
import { Transcript, type TranscriptTheme } from "./transcript"

interface AppOptions {
  wsUrl: string
  apiUrl: string
  apiToken: string
  chatId?: string
  model: string
  workspace: string
  version: string
  access: string
  theme: "auto" | ThemeMode
}

interface ChatClient {
  readonly activeChatId: string
  connect(): void
  close(): void
  send(content: string): string
  attach(chatId: string): void
  newChat(): void
}

interface Palette {
  referenceBackground: string
  text: string
  muted: string
  faint: string
  border: string
  accent: string
  success: string
  error: string
  user: string
  warm: string
  cool: string
}

const DARK: Palette = {
  referenceBackground: "#0E0F11",
  text: "#ECEDEE",
  muted: "#A1A1AA",
  faint: "#71717A",
  border: "#3F3F46",
  accent: "#8B7CF6",
  success: "#5CC489",
  error: "#F87171",
  user: "#60A5FA",
  warm: "#C26A25",
  cool: "#1795A2",
}

const LIGHT: Palette = {
  referenceBackground: "#FAFAFA",
  text: "#18181B",
  muted: "#6F6F78",
  faint: "#8A8A94",
  border: "#D4D4D8",
  accent: "#5B4BC4",
  success: "#166534",
  error: "#B91C1C",
  user: "#1D4ED8",
  warm: "#C2410C",
  cool: "#0F766E",
}

const COMPOSER_PLACEHOLDER = "Ask nanobot anything"
const LOCAL_COMMANDS: SlashCommand[] = [
  {
    command: "/sessions",
    title: "Sessions",
    description: "Find and switch conversations",
    argHint: "",
    acceptsArgs: false,
  },
  {
    command: "/resume",
    title: "Resume",
    description: "Find and switch conversations",
    argHint: "",
    acceptsArgs: false,
  },
  {
    command: "/new",
    title: "New chat",
    description: "Start a separate conversation",
    argHint: "",
    acceptsArgs: false,
  },
]

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
    function: color(palette.warm),
    type: color(palette.cool),
    variable: color(palette.text),
    property: color(palette.user),
    "markup.heading": { ...color(palette.accent), bold: true },
    "markup.strong": { ...color(palette.text), bold: true },
    "markup.italic": { ...color(palette.muted), italic: true },
    "markup.link": { ...color(palette.user), underline: true },
    "markup.link.label": { ...color(palette.user), underline: true },
    "markup.link.url": { ...color(palette.user), underline: true },
    "markup.raw": color(palette.warm),
    conceal: color(palette.faint),
  })
}

function transcriptTheme(palette: Palette): TranscriptTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    error: palette.error,
    user: palette.user,
    assistant: palette.accent,
    border: palette.border,
    syntax: syntaxStyle(palette),
  }
}

function commandMenuTheme(palette: Palette): CommandMenuTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    border: palette.border,
  }
}

function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`
}

async function copyWithSystemClipboard(text: string): Promise<void> {
  const commands = process.platform === "darwin"
    ? [["pbcopy"]]
    : process.platform === "win32"
      ? [["clip.exe"]]
      : [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
  for (const command of commands) {
    try {
      const child = Bun.spawn(command, { stdin: "pipe", stdout: "ignore", stderr: "ignore" })
      child.stdin.write(text)
      child.stdin.end()
      if (await child.exited === 0) return
    } catch {
      // Try the next platform clipboard provider.
    }
  }
  throw new Error("no clipboard provider available")
}

export class NanobotTui {
  private readonly renderer: CliRenderer
  private readonly transcript: Transcript
  private readonly commandMenu: CommandMenu
  private readonly sessionMenu: SessionMenu
  private readonly client: ChatClient
  private readonly shell: BoxRenderable
  private readonly title: TextRenderable
  private readonly composerFrame: BoxRenderable
  private readonly composer: TextareaRenderable
  private readonly status: TextRenderable
  private readonly meta: TextRenderable
  private palette: Palette
  private activeThemeMode: ThemeMode
  private activeTurn = false
  private activeLabel = "Thinking"
  private activeStartedAt = 0
  private lastProgress = ""
  private finalMessage = ""
  private turnHadAnswer = false
  private historyLoaded = false
  private attachedOnce = false
  private pendingEvents: InboundEvent[] | null = null
  private hydrationId = 0
  private ready = false
  private shimmerFrame = 0
  private shimmerTimer: ReturnType<typeof setInterval> | null = null
  private submitPending = false
  private submitGeneration = 0
  private readonly promptHistory: string[] = []
  private historyCursor = 0
  private historyDraft = ""
  private modelName: string
  private quitting = false
  private sessionLoadId = 0
  private sessionLoading = false

  private constructor(
    renderer: CliRenderer,
    private readonly options: AppOptions,
    client?: ChatClient,
    treeSitterClient = getTreeSitterClient(),
  ) {
    this.renderer = renderer
    this.modelName = options.model
    this.activeThemeMode = this.resolveThemeMode(renderer.themeMode)
    this.palette = this.activeThemeMode === "light" ? LIGHT : DARK
    this.transcript = new Transcript(renderer, transcriptTheme(this.palette), treeSitterClient)
    this.commandMenu = new CommandMenu(renderer, commandMenuTheme(this.palette))
    this.sessionMenu = new SessionMenu(renderer, commandMenuTheme(this.palette))
    this.client = client || new NanobotClient({
      url: options.wsUrl,
      chatId: options.chatId,
      onEvent: (event) => this.accept(event),
      onStatus: (status, detail) => this.handleStatus(status, detail),
    })

    // The terminal owns its canvas. Keeping the default-background intent is
    // essential in embedded terminals, where painting our own near-black RGB
    // only colors occupied cells and turns long output into dark strips.
    this.renderer.setBackgroundColor(RGBA.defaultBackground())
    this.shell = new BoxRenderable(renderer, {
      id: "nanobot-tui-footer",
      width: "100%",
      height: "100%",
      paddingLeft: 1,
      paddingRight: 1,
      flexDirection: "column",
      backgroundColor: RGBA.defaultBackground(),
    })
    this.title = new TextRenderable(renderer, {
      id: "nanobot-tui-title",
      content: `nanobot  ·  ${this.modelName}`,
      height: 1,
      flexShrink: 0,
      fg: this.palette.muted,
    })
    this.composerFrame = new BoxRenderable(renderer, {
      id: "nanobot-tui-composer-frame",
      width: "100%",
      minHeight: 3,
      flexShrink: 0,
      border: true,
      borderStyle: "rounded",
      borderColor: this.palette.border,
      paddingLeft: 1,
      paddingRight: 1,
      backgroundColor: RGBA.defaultBackground(),
    })
    this.composer = new TextareaRenderable(renderer, {
      id: "nanobot-tui-composer",
      width: "100%",
      minHeight: 1,
      maxHeight: 8,
      wrapMode: "word",
      placeholder: COMPOSER_PLACEHOLDER,
      placeholderColor: this.palette.faint,
      textColor: this.palette.text,
      focusedTextColor: this.palette.text,
      backgroundColor: RGBA.defaultBackground(),
      focusedBackgroundColor: RGBA.defaultBackground(),
      cursorColor: this.palette.accent,
      showCursor: true,
      keyBindings: [
        { name: "return", action: "submit" },
        { name: "return", meta: true, action: "newline" },
      ],
      onContentChange: () => {
        this.syncComposerPlaceholder()
        if (this.sessionMenu.visible) this.syncSessionMenu()
        else this.syncCommandMenu()
        this.resizeComposer()
      },
      // IMEs may commit their final composed glyph after Enter. Matching the
      // OpenCode/OpenTUI integration, defer twice before reading plainText.
      onSubmit: () => this.deferSubmit(),
    })
    this.status = new TextRenderable(renderer, {
      id: "nanobot-tui-status",
      content: "Connecting…",
      fg: this.palette.muted,
      height: 1,
      width: "auto",
      minWidth: 0,
      flexGrow: 1,
      flexShrink: 1,
    })
    this.meta = new TextRenderable(renderer, {
      id: "nanobot-tui-meta",
      content: "enter send · alt+enter newline · ctrl+c stop",
      fg: this.palette.faint,
      height: 1,
      width: "auto",
      flexShrink: 1,
    })

    const statusRow = new BoxRenderable(renderer, {
      id: "nanobot-tui-status-row",
      width: "100%",
      height: 1,
      flexShrink: 0,
      flexDirection: "row",
      justifyContent: "space-between",
      gap: 2,
    })
    this.composerFrame.add(this.composer)
    statusRow.add(this.status)
    statusRow.add(this.meta)
    this.shell.add(this.transcript.root)
    this.shell.add(this.commandMenu.root)
    this.shell.add(this.sessionMenu.root)
    this.shell.add(this.title)
    this.shell.add(this.composerFrame)
    this.shell.add(statusRow)
    this.renderer.root.add(this.shell)

    this.renderer.keyInput.on("keypress", this.handleKey)
    this.renderer.on(CliRenderEvents.THEME_MODE, this.handleTheme)
    this.renderer.on(CliRenderEvents.RESIZE, this.handleResize)
    this.renderer.on(CliRenderEvents.DESTROY, this.handleDestroy)
    this.renderer.console.onCopySelection = (text) => void this.copySelection(text)
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

  static mount(
    renderer: CliRenderer,
    options: AppOptions,
    client?: ChatClient,
    treeSitterClient?: TreeSitterClient,
  ): NanobotTui {
    return new NanobotTui(renderer, options, client, treeSitterClient)
  }

  async start(): Promise<void> {
    // OpenTUI learns the real terminal background through OSC 10/11. Wait for
    // that bounded probe before first paint, as OpenCode does, so a light
    // terminal does not briefly render the dark palette. The app already owns
    // the renderer here, so a signal during the probe can still restore it.
    if (this.options.theme === "auto") await this.renderer.waitForThemeMode(1_000)
    if (this.quitting) return
    if (this.options.theme === "auto" && this.renderer.themeMode) {
      this.applyTheme(this.renderer.themeMode)
    }
    this.client.connect()
    void this.loadCommands()
    this.renderer.start()
  }

  stop(): void {
    this.quit()
  }

  private deferSubmit(): void {
    if (this.submitPending) return
    this.submitPending = true
    const generation = ++this.submitGeneration
    setTimeout(() => setTimeout(() => {
      if (generation !== this.submitGeneration) return
      this.submitPending = false
      if (this.composer.isDestroyed) return
      this.submit()
    }, 0), 0)
  }

  private submit(): void {
    if (this.quitting || this.composer.isDestroyed) return
    const content = this.composer.plainText.trim()
    if (this.sessionLoading) {
      this.status.content = "Loading sessions…"
      return
    }
    if (this.sessionMenu.visible) {
      const session = this.sessionMenu.choose()
      if (session) this.switchSession(session.chatId)
      return
    }
    if (!content) return
    const completion = this.commandMenu.completion(content)
    if (completion) {
      this.setComposer(completion)
      this.commandMenu.hide()
      this.updateMeta()
      return
    }
    if (["/sessions", "/resume", "/continue"].includes(content.toLocaleLowerCase())) {
      void this.openSessions()
      return
    }
    if (content.toLocaleLowerCase() === "/new") {
      this.startNewChat()
      return
    }
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
    this.commandMenu.hide()
    if (this.promptHistory.at(-1) !== content) this.promptHistory.push(content)
    if (this.promptHistory.length > 50) this.promptHistory.shift()
    this.historyCursor = this.promptHistory.length
    this.historyDraft = ""
    this.transcript.user(content)
    this.finalMessage = ""
    this.turnHadAnswer = false
    this.lastProgress = ""
    this.activeLabel = "Thinking"
    this.setActive(true)
  }

  accept(event: InboundEvent): void {
    if (event.event === "attached") {
      const restoring = this.attachedOnce
      this.attachedOnce = true
      if (restoring) this.setActive(false)
      const queuesEvents = restoring || (!this.historyLoaded && Boolean(this.options.chatId))
      if (queuesEvents) {
        this.ready = false
        this.pendingEvents = []
      }
      const hydrationId = ++this.hydrationId
      void this.prepareChat(event.chat_id, restoring, hydrationId).then(() => {
        if (hydrationId === this.hydrationId) this.flushPendingEvents()
      })
      return
    }
    if (
      "chat_id" in event
      && event.chat_id
      && this.client.activeChatId
      && event.chat_id !== this.client.activeChatId
    ) return
    if (this.pendingEvents) {
      this.pendingEvents.push(event)
      return
    }

    switch (event.event) {
      case "message_accepted":
        return
      case "delta":
        this.setActive(true)
        this.activeLabel = "Writing"
        this.turnHadAnswer = true
        this.transcript.stream(event.text)
        return
      case "message":
        if (event.kind) {
          this.activeLabel = event.kind === "tool_hint" ? "Working" : "Thinking"
          this.lastProgress = this.transcript.progress(event.text, event.tool_events)
          this.setActive(true)
        } else {
          this.finalMessage = event.text
        }
        return
      case "file_edit":
        this.activeLabel = "Editing"
        this.lastProgress = this.transcript.fileEdits(event.edits)
        this.setActive(true)
        return
      case "reasoning_delta":
        this.activeLabel = "Thinking"
        this.setActive(true)
        return
      case "reasoning_end":
        return
      case "stream_end":
        if (event.text && !this.turnHadAnswer) this.turnHadAnswer = true
        if (event.resuming && event.merge_next) {
          this.transcript.reconcileStream(event.text || "")
        } else {
          this.transcript.finishStream(event.text || "")
        }
        return
      case "turn_end":
        this.transcript.finishStream(this.turnHadAnswer ? "" : this.finalMessage)
        this.transcript.finishActivity()
        this.finalMessage = ""
        this.turnHadAnswer = false
        this.setActive(false)
        if (typeof event.latency_ms === "number") {
          this.status.content = `Ready · ${(event.latency_ms / 1000).toFixed(1)}s`
        }
        return
      case "goal_status":
        if (event.status === "running") {
          this.activeLabel = "Working"
          this.setActive(true, typeof event.started_at === "number" ? event.started_at * 1000 : undefined)
        } else {
          this.setActive(false)
        }
        return
      case "goal_state":
        return
      case "turn_model_updated":
        this.setModel(event.model_name)
        return
      case "runtime_model_updated":
        this.setModel(event.model_name)
        return
      case "error":
        this.transcript.finishStream(this.turnHadAnswer ? "" : this.finalMessage)
        this.transcript.notice(event.reason || event.detail || "Unknown gateway error", true)
        this.finalMessage = ""
        this.turnHadAnswer = false
        this.setActive(false)
        return
    }
  }

  private async prepareChat(chatId: string, restoring: boolean, hydrationId: number): Promise<void> {
    try {
      if (restoring) {
        this.transcript.reset({
          model: this.modelName,
          workspace: this.options.workspace,
          version: this.options.version,
          access: this.options.access,
        })
      }
      if (restoring || (!this.historyLoaded && this.options.chatId)) {
        this.historyLoaded = true
        const history = await fetchHistory(this.options.apiUrl, this.options.apiToken, chatId)
        if (hydrationId !== this.hydrationId) return
        if (history.truncated) {
          this.transcript.notice("Earlier messages omitted · open WebUI to load the full history")
        }
        this.transcript.history(history.messages)
      }
    } catch (error) {
      if (hydrationId !== this.hydrationId) return
      this.transcript.notice(error instanceof Error ? error.message : String(error), true)
    } finally {
      if (hydrationId !== this.hydrationId) return
      this.ready = true
      if (!this.activeTurn) this.status.content = "Ready"
    }
  }

  private flushPendingEvents(): void {
    const events = this.pendingEvents
    this.pendingEvents = null
    for (const event of events || []) this.accept(event)
  }

  private handleStatus(status: ConnectionStatus, detail?: string): void {
    if (status === "connected") {
      this.ready = false
      this.status.content = "Connected · preparing chat…"
      return
    }
    if (status === "connecting") {
      this.ready = false
      if (detail) this.setActive(false)
      this.status.content = detail ? "Reconnecting…" : "Connecting…"
      return
    }
    if (status === "error") {
      this.setActive(false)
      this.status.content = detail || "Connection error"
      return
    }
    if (!this.quitting) {
      this.setActive(false)
      this.status.content = "Disconnected"
    }
  }

  private setActive(active: boolean, startedAt?: number): void {
    if (this.activeTurn === active) {
      if (active && startedAt !== undefined) this.activeStartedAt = startedAt
      return
    }
    this.activeTurn = active
    this.updateMeta()
    if (active) {
      this.activeStartedAt = startedAt ?? Date.now()
      this.shimmerFrame = 0
      this.shimmerTimer = setInterval(() => {
        const frames = ["◐", "◓", "◑", "◒"]
        const frame = frames[this.shimmerFrame++ % frames.length]
        const elapsed = formatElapsed(Date.now() - this.activeStartedAt)
        const detail = this.lastProgress ? ` · ${this.lastProgress.replace(/^\s*[·›✓×]\s*/u, "")}` : ""
        this.status.content = `${frame} ${this.activeLabel}  ${elapsed}${detail}`
      }, 120)
      return
    }
    if (this.shimmerTimer) clearInterval(this.shimmerTimer)
    this.shimmerTimer = null
    this.lastProgress = ""
    this.status.content = "Ready"
  }

  private handleKey = (key: KeyEvent): void => {
    if (this.sessionLoading && key.name === "escape") {
      this.closeSessions()
      this.status.content = "Ready"
      key.preventDefault()
      return
    }
    if (this.sessionMenu.visible) {
      if (!key.ctrl && !key.meta && (key.name === "up" || key.name === "down")) {
        this.sessionMenu.move(key.name === "up" ? -1 : 1)
        key.preventDefault()
        return
      }
      if (key.name === "escape") {
        this.closeSessions()
        key.preventDefault()
        return
      }
    }
    if (this.commandMenu.visible) {
      if (!key.ctrl && !key.meta && (key.name === "up" || key.name === "down")) {
        this.commandMenu.move(key.name === "up" ? -1 : 1)
        key.preventDefault()
        return
      }
      if (!key.ctrl && !key.meta && key.name === "tab") {
        const completion = this.commandMenu.complete()
        if (completion) {
          this.setComposer(completion)
          this.commandMenu.hide()
        }
        this.updateMeta()
        key.preventDefault()
        return
      }
      if (key.name === "escape") {
        this.commandMenu.hide()
        this.updateMeta()
        key.preventDefault()
        return
      }
    }
    if (key.ctrl && key.name === "o") {
      const expanded = this.transcript.toggleActivityDetails()
      if (expanded === null) return
      this.status.content = expanded ? "Tool details expanded" : "Tool details collapsed"
      key.preventDefault()
      return
    }
    if (!key.ctrl && !key.meta && (key.name === "up" || key.name === "down")) {
      const direction = key.name === "up" ? -1 : 1
      const boundary = direction < 0 ? 0 : this.composer.plainText.length
      if (this.composer.cursorOffset !== boundary) {
        const visualRow = this.composer.scrollY + this.composer.visualCursor.visualRow
        const edgeRow = direction < 0 ? 0 : Math.max(0, this.composer.virtualLineCount - 1)
        if (visualRow === edgeRow) this.composer.cursorOffset = boundary
        return
      }
      if (this.navigateHistory(direction)) {
        key.preventDefault()
        return
      }
    }
    if (key.ctrl && key.name === "c") {
      key.preventDefault()
      const selected = this.renderer.getSelection()?.getSelectedText()
      if (selected) {
        void this.copySelection(selected)
        return
      }
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
      return
    }
    if (key.name === "pageup" || key.name === "pagedown") {
      key.preventDefault()
      this.transcript.scrollByPage(key.name === "pageup" ? -1 : 1)
      return
    }
    if (key.ctrl && (key.name === "home" || key.name === "end")) {
      key.preventDefault()
      this.transcript.scrollToEdge(key.name === "home" ? "top" : "bottom")
    }
  }

  private navigateHistory(direction: -1 | 1): boolean {
    if (this.promptHistory.length === 0) return false
    if (direction < 0) {
      if (this.historyCursor === this.promptHistory.length) this.historyDraft = this.composer.plainText
      if (this.historyCursor === 0) return false
      this.historyCursor -= 1
    } else {
      if (this.historyCursor >= this.promptHistory.length) return false
      this.historyCursor += 1
    }
    const content = this.historyCursor === this.promptHistory.length
      ? this.historyDraft
      : this.promptHistory[this.historyCursor] || ""
    this.composer.setText(content)
    this.composer.cursorOffset = direction < 0 ? 0 : content.length
    return true
  }

  private handleTheme = (mode: ThemeMode): void => {
    if (this.options.theme !== "auto") return
    this.applyTheme(mode)
  }

  private resolveThemeMode(detected: ThemeMode | null): ThemeMode {
    return this.options.theme === "auto" ? detected ?? "dark" : this.options.theme
  }

  private applyTheme(mode: ThemeMode): void {
    if (this.activeThemeMode === mode) return
    this.activeThemeMode = mode
    this.palette = mode === "light" ? LIGHT : DARK
    this.transcript.setTheme(transcriptTheme(this.palette))
    this.commandMenu.setTheme(commandMenuTheme(this.palette))
    this.sessionMenu.setTheme(commandMenuTheme(this.palette))
    this.composerFrame.borderColor = this.palette.border
    this.composer.textColor = this.palette.text
    this.composer.focusedTextColor = this.palette.text
    this.composer.cursorColor = this.palette.accent
    this.title.fg = this.palette.muted
    this.status.fg = this.palette.muted
    this.meta.fg = this.palette.faint
  }

  private handleResize = (): void => {
    this.resizeComposer()
    this.title.visible = this.renderer.height >= 14
    this.updateMeta()
  }

  private updateMeta(): void {
    if (this.activeTurn) {
      this.meta.content = this.renderer.width >= 48 ? "ctrl+c stop" : ""
      return
    }
    if (this.commandMenu.visible) {
      this.meta.content = this.renderer.width >= 72
        ? "↑↓ choose · tab complete · esc close"
        : "tab complete · esc close"
      return
    }
    if (this.sessionMenu.visible) {
      this.meta.content = this.renderer.width >= 64
        ? "type to filter · ↑↓ choose · enter open · esc close"
        : "enter open · esc close"
      return
    }
    this.meta.content = this.renderer.width >= 112
      ? "enter send · alt+enter newline · pgup/pgdn scroll · ctrl+o tools · ctrl+c stop"
      : this.renderer.width >= 72
        ? "enter send · alt+enter newline · ctrl+c stop"
        : this.renderer.width >= 48
        ? "enter send · alt+enter newline"
        : ""
  }

  private setModel(model: string): void {
    this.modelName = model
    this.title.content = `nanobot  ·  ${model}`
  }

  private resizeComposer(): void {
    const maxHeight = Math.max(1, Math.min(12, Math.floor(this.renderer.height / 3)))
    this.composer.maxHeight = maxHeight
    this.composerFrame.maxHeight = maxHeight + 2
  }

  private syncComposerPlaceholder(): void {
    // OpenTUI normally suppresses placeholder glyphs while the editor is not
    // empty. Explicitly removing them also invalidates their old cells, which
    // prevents stale placeholder text in differential/embedded terminals.
    const placeholder = this.composer.plainText
      ? null
      : this.sessionMenu.visible ? "Search sessions" : COMPOSER_PLACEHOLDER
    if (this.composer.placeholder !== placeholder) this.composer.placeholder = placeholder
  }

  private syncCommandMenu(): void {
    const limit = this.renderer.height >= 20 ? 6 : 3
    this.commandMenu.update(this.composer.plainText, limit)
    this.updateMeta()
  }

  private syncSessionMenu(): void {
    const limit = this.renderer.height >= 20 ? 8 : 4
    this.sessionMenu.update(this.composer.plainText, limit)
    this.updateMeta()
  }

  private setComposer(content: string): void {
    this.composer.setText(content)
    this.composer.cursorOffset = content.length
  }

  private async loadCommands(): Promise<void> {
    let discovered: SlashCommand[] = []
    try {
      discovered = await fetchSlashCommands(
        this.options.apiUrl,
        this.options.apiToken,
      )
    } catch {
      // Local navigation remains available against older gateways.
    }
    const commands = new Map(discovered.map((command) => [command.command, command]))
    for (const command of LOCAL_COMMANDS) commands.set(command.command, command)
    this.commandMenu.setCommands([...commands.values()])
    this.syncCommandMenu()
  }

  private async openSessions(): Promise<void> {
    if (this.activeTurn) {
      this.status.content = "Wait for the current turn or press Ctrl+C"
      return
    }
    this.commandMenu.hide()
    this.composer.setText("")
    this.sessionLoading = true
    const loadId = ++this.sessionLoadId
    this.status.content = "Loading sessions…"
    try {
      const sessions = await fetchSessions(this.options.apiUrl, this.options.apiToken)
      if (this.quitting || loadId !== this.sessionLoadId) return
      this.sessionLoading = false
      const limit = this.renderer.height >= 20 ? 8 : 4
      this.sessionMenu.open(sessions, this.client.activeChatId, limit)
      this.syncComposerPlaceholder()
      this.updateMeta()
      this.status.content = sessions.length ? `${sessions.length} sessions` : "No saved sessions"
    } catch (error) {
      if (loadId !== this.sessionLoadId) return
      this.sessionLoading = false
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private switchSession(chatId: string): void {
    if (this.activeTurn) {
      this.status.content = "Wait for the current turn or press Ctrl+C"
      return
    }
    this.closeSessions()
    if (chatId === this.client.activeChatId) {
      this.status.content = "Ready"
      return
    }
    try {
      this.ready = false
      this.status.content = "Opening session…"
      this.client.attach(chatId)
    } catch (error) {
      this.ready = true
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private startNewChat(): void {
    if (this.activeTurn) {
      this.status.content = "Wait for the current turn or press Ctrl+C"
      return
    }
    this.commandMenu.hide()
    this.sessionMenu.hide()
    this.composer.setText("")
    try {
      this.ready = false
      this.status.content = "Starting a new chat…"
      this.client.newChat()
    } catch (error) {
      this.ready = true
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private closeSessions(): void {
    this.sessionLoadId += 1
    this.sessionLoading = false
    this.sessionMenu.hide()
    this.composer.setText("")
    this.syncComposerPlaceholder()
    this.updateMeta()
  }

  private async copySelection(text: string): Promise<void> {
    if (!text) return
    try {
      if (!this.renderer.copyToClipboardOSC52(text)) await copyWithSystemClipboard(text)
      this.renderer.clearSelection()
      this.status.content = "Copied"
    } catch {
      this.status.content = "Copy unavailable"
    }
  }

  private quit(): void {
    if (this.quitting) return
    this.quitting = true
    this.submitGeneration += 1
    this.submitPending = false
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
