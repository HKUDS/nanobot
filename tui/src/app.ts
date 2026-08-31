import {
  BoxRenderable,
  CliRenderEvents,
  RGBA,
  StyledText,
  SyntaxStyle,
  TextareaRenderable,
  TextRenderable,
  createCliRenderer,
  decodePasteBytes,
  getTreeSitterClient,
  stripAnsiSequences,
  type CliRenderer,
  type KeyEvent,
  type PasteEvent,
  type TextChunk,
  type ThemeMode,
  type TreeSitterClient,
} from "@opentui/core"

import {
  NanobotClient,
  connectionEndpoint,
  fetchAvailableSkills,
  fetchGatewayHealth,
  fetchHistory,
  fetchGatewayConnection,
  fetchMentionCandidates,
  fetchSessionContext,
  fetchSessions,
  fetchSlashCommands,
  type ApiReauthenticator,
  type ConnectionStatus,
  type ConnectionStatusInfo,
  type FileEditEvent,
  type GatewayApiConnection,
  type HistoryMessage,
  type InboundEvent,
  type MentionCandidate,
  type MessageOptions,
  type RecoveryState,
  type SkillCandidate,
  type SlashCommand,
  type SessionSummary,
  type TokenUsage,
  type WorkspaceScopePayload,
} from "./protocol"
import {
  CommandMenu,
  resolveSlashCommandLifecycle,
  type CommandMenuTheme,
  type ResolvedSlashCommandLifecycle,
  type TuiCommand,
} from "./command-menu"
import { SessionMenu, sessionLabel } from "./session-menu"
import { ContextPanel, formatTokenCount, type ContextPanelTheme } from "./context-panel"
import {
  DiffViewer,
  latestTurnFileEdits,
  mergeFileEdits,
  type DiffViewerTheme,
} from "./diff-viewer"
import {
  Transcript,
  type TranscriptNavigation,
  type TranscriptTheme,
} from "./transcript"
import { ComposerDraft, MAX_DRAFT_IMAGES } from "./composer-draft"
import {
  createClipboardImageReader,
  type ClipboardImageReader,
} from "./clipboard-image"
import { BranchMenu, branchPoints } from "./branch-menu"
import {
  MentionMenu,
  insertMention,
  mentionOptions,
  mentionQuery,
  type MentionQuery,
} from "./mention-menu"
import {
  insertSkill,
  SkillMenu,
  skillQuery,
  type SkillQuery,
} from "./skill-menu"
import { PromptQueue, type QueuedPrompt } from "./prompt-queue"
import { QueuePreview, type QueuePreviewTheme } from "./queue-preview"
import { RecoveryNotice, type RecoveryNoticeTheme } from "./recovery-notice"
import { RuntimeControls } from "./runtime-controls"
import {
  contextualFooterHints,
  footerTelemetry,
  type FooterMode,
  type FooterHintTheme,
} from "./footer-hints"
import { configureOpenTuiEnvironment, createTuiHost, type TuiHost } from "./host"

interface AppOptions {
  wsUrl?: string
  bootstrapUrl?: string
  bootstrapSecret?: string
  healthUrl?: string
  apiUrl: string
  apiToken: string
  chatId?: string
  model: string
  modelPreset: string
  workspace: string
  version: string
  access: string
  theme: "auto" | ThemeMode
  onDetach?: (chatId?: string) => void
  onExit?: (chatId: string) => void
}

interface ChatClient {
  readonly activeChatId: string
  connect(): void
  close(): void
  send(content: string, options?: MessageOptions): string
  attach(chatId: string): void
  newChat(scope?: WorkspaceScopePayload): void
  forkChat?(sourceChatId: string, beforeUserIndex: number, title?: string): void
  setWorkspaceScope(scope: WorkspaceScopePayload): void
  updateRecovery(
    action: "continue" | "dismiss",
    chatId: string,
    recoveryId: string,
  ): Promise<RecoveryState>
}

interface Palette {
  referenceBackground: string
  text: string
  muted: string
  faint: string
  border: string
  accent: string
  link: string
  success: string
  warning: string
  error: string
  user: string
  userBackground: string
  warm: string
  cool: string
}

const DARK: Palette = {
  referenceBackground: "#0E0F11",
  text: "#ECEDEE",
  muted: "#A1A1AA",
  faint: "#71717A",
  border: "#3F3F46",
  accent: "#EF8E30",
  link: "#60A5FA",
  success: "#5CC489",
  warning: "#F5C451",
  error: "#F87171",
  user: "#EF8E30",
  // Codex-style turn anchor: 12% white over the reference dark background.
  userBackground: "#2B2C2E",
  warm: "#C26A25",
  cool: "#1795A2",
}

const LIGHT: Palette = {
  referenceBackground: "#FAFAFA",
  text: "#18181B",
  muted: "#6F6F78",
  faint: "#8A8A94",
  border: "#D4D4D8",
  accent: "#B94D0B",
  link: "#1D4ED8",
  success: "#166534",
  warning: "#A16207",
  error: "#B91C1C",
  user: "#B94D0B",
  // Codex-style turn anchor: 4% black over the reference light background.
  userBackground: "#F0F0F0",
  warm: "#C2410C",
  cool: "#0F766E",
}

const COMPOSER_PLACEHOLDER = "Ask nanobot anything"
const ACTIVE_COMPOSER_PLACEHOLDER = "Enter send now · Tab send next"
const COMPACT_ACTIVE_COMPOSER_PLACEHOLDER = "Enter now · Tab next"
const IMAGE_PLACEHOLDER_STYLE = "image.placeholder"
const SHIMMER_PAUSE = 16
const SHIMMER_BAND = 4
const SHIMMER_INTERVAL_MS = 80
const SESSION_REFRESH_INTERVAL_MS = 1_000
const LOCAL_COMMANDS: TuiCommand[] = [
  {
    command: "/sessions",
    title: "Sessions",
    description: "Find and switch conversations",
    action: "sessions",
  },
  {
    command: "/new-chat",
    title: "New saved chat",
    description: "Keep this conversation and start another",
    action: "new-chat",
  },
  {
    command: "/context",
    title: "Agent context",
    description: "Explain what this session contributes to the next prompt",
    action: "context",
  },
  {
    command: "/diff",
    title: "Last turn diff",
    description: "Inspect file changes from the latest turn",
    action: "diff",
  },
  {
    command: "/branch",
    title: "Branch from reply",
    description: "Continue from an earlier completed reply",
    action: "branch",
  },
  {
    command: "/detach",
    title: "Detach",
    description: "Close this terminal UI and keep the agent running",
    action: "detach",
  },
  {
    command: "/exit",
    title: "Exit",
    description: "Close this terminal UI",
    action: "exit",
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
    number: color(palette.link),
    function: color(palette.warm),
    type: color(palette.cool),
    variable: color(palette.text),
    property: color(palette.link),
    "markup.heading": { ...color(palette.accent), bold: true },
    "markup.strong": { ...color(palette.text), bold: true },
    "markup.italic": { ...color(palette.muted), italic: true },
    "markup.link": { ...color(palette.link), underline: true },
    "markup.link.label": { ...color(palette.link), underline: true },
    "markup.link.url": { ...color(palette.link), underline: true },
    "markup.raw": color(palette.warm),
    conceal: color(palette.faint),
  })
}

function composerSyntaxStyle(palette: Palette): SyntaxStyle {
  return SyntaxStyle.fromStyles({
    [IMAGE_PLACEHOLDER_STYLE]: { fg: RGBA.fromHex(palette.accent), bold: true },
  })
}

function transcriptTheme(palette: Palette, backgroundKnown: boolean): TranscriptTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    error: palette.error,
    user: palette.user,
    userBackground: backgroundKnown ? palette.userBackground : null,
    border: palette.border,
    syntax: syntaxStyle(palette),
  }
}

function commandMenuTheme(palette: Palette): CommandMenuTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    border: palette.border,
    accent: palette.accent,
    warning: palette.warning,
    selectedBackground: palette.userBackground,
  }
}

function runtimeControlsTheme(palette: Palette) {
  return {
    ...commandMenuTheme(palette),
    accent: palette.accent,
    faint: palette.faint,
  }
}

function contextPanelTheme(palette: Palette): ContextPanelTheme {
  return {
    text: palette.text,
    border: palette.border,
    accent: palette.accent,
  }
}

function diffViewerTheme(palette: Palette, backgroundKnown: boolean): DiffViewerTheme {
  const light = palette === LIGHT
  return {
    text: palette.text,
    muted: palette.muted,
    border: palette.border,
    accent: palette.accent,
    success: palette.success,
    error: palette.error,
    addedBackground: backgroundKnown ? light ? "#E7F6EC" : "#142D22" : null,
    removedBackground: backgroundKnown ? light ? "#FCE8EA" : "#352024" : null,
    syntax: syntaxStyle(palette),
  }
}

function queuePreviewTheme(palette: Palette): QueuePreviewTheme {
  return {
    accent: palette.accent,
    muted: palette.muted,
    faint: palette.faint,
  }
}

function recoveryNoticeTheme(palette: Palette): RecoveryNoticeTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    border: palette.border,
    accent: palette.accent,
    warning: palette.warning,
    error: palette.error,
  }
}

function footerHintTheme(palette: Palette): FooterHintTheme {
  return {
    accent: palette.accent,
    danger: palette.error,
    muted: palette.muted,
    separator: palette.faint,
  }
}

function shimmerStatus(
  label: string,
  suffix: string,
  frame: number,
  palette: Palette,
): StyledText {
  const chars = Array.from(label)
  const base = RGBA.fromHex(palette.muted).toInts()
  const highlight = RGBA.fromHex(palette.accent).toInts()
  // Sweep immediately, then leave a quiet pause before repeating. The text
  // keeps a constant width throughout, so the footer never jitters.
  const position = frame % (chars.length + SHIMMER_PAUSE)
  const chunks: TextChunk[] = chars.map((text, index) => {
    const distance = Math.abs(index - position)
    const intensity = distance > SHIMMER_BAND
      ? 0
      : (1 + Math.cos(Math.PI * distance / SHIMMER_BAND)) / 2
    return {
      __isChunk: true,
      text,
      fg: RGBA.fromInts(
        Math.round(base[0] + (highlight[0] - base[0]) * intensity),
        Math.round(base[1] + (highlight[1] - base[1]) * intensity),
        Math.round(base[2] + (highlight[2] - base[2]) * intensity),
      ),
    }
  })
  chunks.push({ __isChunk: true, text: suffix, fg: RGBA.fromHex(palette.muted) })
  return new StyledText(chunks)
}

function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`
}

function connectionStatusText(
  status: ConnectionStatus,
  info?: ConnectionStatusInfo,
): string {
  if (["starting", "connecting", "connected"].includes(status)) return "Getting ready…"
  if (status === "reconnecting") return "Resuming…"
  if (status === "unavailable") {
    return info?.health === "degraded"
      ? "Still getting ready…"
      : "Nanobot is taking longer to respond…"
  }
  if (status === "error") return "Nanobot unavailable · restart nanobot"
  return "Session ended"
}

export function sessionExitMessage(chatId: string): string {
  const sessionId = `websocket:${chatId}`
  return `Resume with: nanobot agent --session ${sessionId}\n`
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
  private readonly mentionMenu: MentionMenu
  private readonly skillMenu: SkillMenu
  private readonly branchMenu: BranchMenu
  private readonly runtimeControls: RuntimeControls
  private readonly contextPanel: ContextPanel
  private readonly diffViewer: DiffViewer
  private readonly queuePreview: QueuePreview
  private readonly recoveryNotice: RecoveryNotice
  private readonly client: ChatClient
  private readonly shell: BoxRenderable
  private readonly title: BoxRenderable
  private readonly composerFrame: BoxRenderable
  private readonly composer: TextareaRenderable
  private composerSyntax: SyntaxStyle
  private readonly status: TextRenderable
  private readonly meta: TextRenderable
  private readonly host: TuiHost
  private readonly draft = new ComposerDraft()
  private readonly promptQueues = new Map<string, PromptQueue>()
  private currentChatId = ""
  private palette: Palette
  private activeThemeMode: ThemeMode
  private backgroundKnown: boolean
  private activeTurn = false
  private activeTurnId: string | null = null
  private activeLabel = "Thinking"
  private activeStartedAt = 0
  private finalMessage = ""
  private turnHadAnswer = false
  private historyLoaded = false
  private historyBeforeCursor: string | null = null
  private historyHasMore = false
  private historyLoadingOlder = false
  private attachedOnce = false
  private pendingEvents: InboundEvent[] | null = null
  private hydrationId = 0
  private ready = false
  private shimmerFrame = 0
  private shimmerTimer: ReturnType<typeof setInterval> | null = null
  private submitPending = false
  private submitGeneration = 0
  private unsentSubmit = false
  private connectionMessage = "Getting ready…"
  private readonly promptHistory: string[] = []
  private historyCursor = 0
  private historyDraft = ""
  private defaultModelName: string
  private defaultModelPreset: string
  private modelName: string
  private modelPreset: string
  private sessionModelPreset: string | null | undefined
  private sessionTitle = ""
  private sessionMetadataId = 0
  private contextTokens: number | null = null
  private contextWindowTokens: number | null = null
  private lastUsage: TokenUsage | null = null
  private readyDetail = ""
  private mentionCandidates: MentionCandidate[] = []
  private activeMentionQuery: MentionQuery | null = null
  private skillCandidates: SkillCandidate[] = []
  private activeSkillQuery: SkillQuery | null = null
  private transcriptNavigation: TranscriptNavigation = {
    awayFromBottom: false,
    unseenOutput: false,
  }
  private quitting = false
  private sessionLoadId = 0
  private sessionLoading = false
  private sessionRefreshPending = false
  private sessionRefreshTimer: ReturnType<typeof setInterval> | null = null
  private readonly commandTurns = new Map<string, ResolvedSlashCommandLifecycle>()
  private readonly modelCommandTurns = new Set<string>()
  private readonly silentCommandTurns = new Set<string>()
  private currentFileEdits: FileEditEvent[] = []
  private lastFileEdits: FileEditEvent[] = []
  private recoveryState: RecoveryState | null = null
  private recoveryPending = false
  private readonly apiReauthenticator: ApiReauthenticator | undefined
  private readonly clipboardImageReader: ClipboardImageReader
  private apiRefreshPromise: Promise<GatewayApiConnection> | null = null
  private skillLoadId = 0
  private clipboardImagePending = false
  private clipboardPasteGeneration = 0
  private composerValue = ""
  private composerCursor = 0
  private reconcilingComposer = false

  private constructor(
    renderer: CliRenderer,
    private readonly options: AppOptions,
    client?: ChatClient,
    treeSitterClient = getTreeSitterClient(),
    host: TuiHost = createTuiHost({}),
    clipboardImageReader: ClipboardImageReader = createClipboardImageReader(),
  ) {
    this.renderer = renderer
    this.clipboardImageReader = clipboardImageReader
    this.defaultModelName = options.model
    this.defaultModelPreset = options.modelPreset
    this.modelName = options.model
    this.modelPreset = options.modelPreset
    this.apiReauthenticator = options.bootstrapUrl
      ? (rejectedApiToken) => this.refreshApiConnection(rejectedApiToken)
      : undefined
    this.sessionModelPreset = options.chatId ? undefined : null
    this.backgroundKnown = options.theme !== "auto" || renderer.themeMode !== null
    this.activeThemeMode = this.resolveThemeMode(renderer.themeMode)
    this.palette = this.activeThemeMode === "light" ? LIGHT : DARK
    this.composerSyntax = composerSyntaxStyle(this.palette)
    this.host = host
    this.transcript = new Transcript(
      renderer,
      transcriptTheme(this.palette, this.backgroundKnown),
      treeSitterClient,
      (state) => this.handleTranscriptNavigation(state),
      options.workspace,
    )
    this.commandMenu = new CommandMenu(renderer, commandMenuTheme(this.palette))
    this.commandMenu.setCommands([], LOCAL_COMMANDS)
    this.sessionMenu = new SessionMenu(
      renderer,
      commandMenuTheme(this.palette),
      (session) => this.switchSession(session),
    )
    this.mentionMenu = new MentionMenu(renderer, commandMenuTheme(this.palette))
    this.skillMenu = new SkillMenu(renderer, commandMenuTheme(this.palette))
    this.branchMenu = new BranchMenu(renderer, commandMenuTheme(this.palette))
    this.contextPanel = new ContextPanel(renderer, contextPanelTheme(this.palette))
    this.diffViewer = new DiffViewer(
      renderer,
      diffViewerTheme(this.palette, this.backgroundKnown),
      treeSitterClient,
    )
    this.queuePreview = new QueuePreview(renderer, queuePreviewTheme(this.palette))
    this.recoveryNotice = new RecoveryNotice(
      renderer,
      recoveryNoticeTheme(this.palette),
      {
        onContinue: () => void this.updateRecovery("continue"),
        onDismiss: () => void this.updateRecovery("dismiss"),
      },
    )
    this.client = client || new NanobotClient({
      ...(options.bootstrapUrl
        ? {
            resolveConnection: () => fetchGatewayConnection(
              options.bootstrapUrl || "",
              options.bootstrapSecret || "",
              options.apiUrl,
              `tui-${process.pid}`,
            ),
            ...(options.healthUrl
              ? { checkHealth: () => fetchGatewayHealth(options.healthUrl || "") }
              : {}),
            onConnection: (connection) => this.useGatewayConnection(
              connection.apiUrl,
              connection.apiToken,
            ),
            targetEndpoint: connectionEndpoint(options.bootstrapUrl),
            reconnectDelayMs: 100,
            startupRetryMaxDelayMs: 250,
          }
        : { url: options.wsUrl }),
      chatId: options.chatId,
      initialWorkspaceScope: {
        project_path: options.workspace,
        access_mode: options.access.toLocaleLowerCase().includes("full") ? "full" : "restricted",
      },
      onEvent: (event) => this.accept(event),
      onStatus: (status, detail, info) => this.handleStatus(status, detail, info),
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
      onMouseDown: (event) => {
        if (event.button !== 0) return
        if (!this.diffViewer.visible) {
          // OpenTUI applies automatic focus after mouse handlers run. Prevent
          // a focusable transcript ancestor from stealing text focus back
          // after the composer has been restored here.
          event.preventDefault()
          this.composer.focus()
        }
        // Runtime pickers are transient popovers. A primary click anywhere
        // outside their trigger or body dismisses them; hide() restores the
        // composer focus through the shared visibility callback.
        this.dismissRuntimeControls()
        if (this.sessionLoading || this.sessionMenu.visible) {
          this.closeSessions()
        }
        // Selection belongs to transcript/input content, never to empty chrome.
        // Clearing it here prevents default-background cells from lingering as
        // opaque blocks in terminals with differential repainting.
        if (event.target && !event.target.selectable) {
          this.renderer.clearSelection()
        }
      },
    })
    this.title = new BoxRenderable(renderer, {
      id: "nanobot-tui-title",
      width: "100%",
      height: 1,
      flexShrink: 0,
      flexDirection: "row",
      alignItems: "center",
      backgroundColor: RGBA.defaultBackground(),
    })
    this.runtimeControls = new RuntimeControls(
      renderer,
      runtimeControlsTheme(this.palette),
      {
        apiUrl: options.apiUrl,
        apiToken: options.apiToken,
        model: this.modelName,
        modelPreset: this.modelPreset,
        workspace: options.workspace,
        access: options.access,
        reauthenticateApi: this.apiReauthenticator,
        // Runtime settings are session state. Changing them during a turn is
        // safe and takes effect when the next provider call starts.
        available: () => this.ready,
        beforeOpen: () => this.closeTransientMenus(),
        refreshScope: () => this.refreshSessionMetadata(this.client.activeChatId),
        onModel: (preset) => this.sendGatewayCommand(`/model ${preset}`, "side_channel", true),
        onAccess: (scope) => {
          try {
            this.client.setWorkspaceScope(scope)
            this.status.content = "Changing access…"
          } catch (error) {
            this.status.content = error instanceof Error ? error.message : String(error)
          }
        },
        onStatus: (message) => { this.status.content = message },
        onVisibilityChange: (visible) => {
          this.updateMeta()
          if (!visible) this.composer.focus()
        },
      },
    )
    this.title.add(this.runtimeControls.modelText)
    this.title.add(this.runtimeControls.accessText)
    this.title.add(this.runtimeControls.contextText)
    const composerSurface = this.composerSurface()
    this.composerFrame = new BoxRenderable(renderer, {
      id: "nanobot-tui-composer-frame",
      width: "100%",
      minHeight: 1,
      flexShrink: 0,
      border: ["left"],
      borderColor: this.palette.accent,
      paddingLeft: 1,
      paddingRight: 1,
      backgroundColor: composerSurface,
    })
    this.composer = new TextareaRenderable(renderer, {
      id: "nanobot-tui-composer",
      width: "100%",
      minHeight: 1,
      maxHeight: 8,
      wrapMode: "word",
      placeholder: COMPOSER_PLACEHOLDER,
      placeholderColor: this.palette.muted,
      textColor: this.palette.text,
      focusedTextColor: this.palette.text,
      backgroundColor: composerSurface,
      focusedBackgroundColor: composerSurface,
      cursorColor: this.palette.accent,
      syntaxStyle: this.composerSyntax,
      // A steady line cursor avoids the block-cell trails produced by some
      // terminals when a retained full-screen UI redraws around the composer.
      cursorStyle: { style: "line", blinking: false },
      showCursor: true,
      keyBindings: [
        { name: "return", shift: true, action: "newline" },
        { name: "return", meta: true, action: "newline" },
        { name: "return", ctrl: true, action: "newline" },
        { name: "j", ctrl: true, action: "newline" },
        { name: "linefeed", action: "newline" },
        { name: "return", action: "submit" },
      ],
      onCursorChange: () => {
        this.keepComposerCursorOutsideImages()
        if (!this.sessionMenu.visible && !this.branchMenu.visible) this.syncComposerMenus()
      },
      onContentChange: () => this.handleComposerContentChange(),
      onMouseDown: () => queueMicrotask(() => this.keepComposerCursorOutsideImages()),
      onMouseUp: () => queueMicrotask(() => this.keepComposerCursorOutsideImages()),
      onMouseDrag: () => queueMicrotask(() => this.keepComposerCursorOutsideImages()),
      onMouseDragEnd: () => queueMicrotask(() => this.keepComposerCursorOutsideImages()),
      // IMEs may commit their final composed glyph after Enter. Matching the
      // OpenCode/OpenTUI integration, defer twice before reading plainText.
      onSubmit: () => this.deferSubmit(),
      onPaste: (event) => this.handlePaste(event),
    })
    this.status = new TextRenderable(renderer, {
      id: "nanobot-tui-status",
      content: "Getting ready…",
      fg: this.palette.muted,
      height: 1,
      width: "auto",
      minWidth: 0,
      flexGrow: 1,
      flexShrink: 1,
      selectable: false,
    })
    this.meta = new TextRenderable(renderer, {
      id: "nanobot-tui-meta",
      content: "",
      fg: this.palette.faint,
      height: 1,
      width: "auto",
      flexShrink: 1,
      selectable: false,
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
    this.shell.add(this.mentionMenu.root)
    this.shell.add(this.skillMenu.root)
    this.shell.add(this.branchMenu.root)
    this.shell.add(this.contextPanel.root)
    this.shell.add(this.runtimeControls.menuRoot)
    this.shell.add(this.title)
    this.shell.add(this.queuePreview.root)
    this.shell.add(this.recoveryNotice.root)
    this.shell.add(this.composerFrame)
    this.shell.add(statusRow)
    this.shell.add(this.diffViewer.root)
    this.renderer.root.add(this.shell)

    this.renderer.keyInput.on("keypress", this.handleKey)
    this.renderer.on(CliRenderEvents.THEME_MODE, this.handleTheme)
    this.renderer.on(CliRenderEvents.CAPABILITIES, this.handleCapabilities)
    this.renderer.on(CliRenderEvents.RESIZE, this.handleResize)
    this.renderer.on(CliRenderEvents.DESTROY, this.handleDestroy)
    this.renderer.console.onCopySelection = (text) => void this.copySelection(text)
    this.handleResize()
    this.composer.focus()
    this.transcript.header(options)
  }

  static async create(options: AppOptions): Promise<NanobotTui> {
    configureOpenTuiEnvironment()
    const host = createTuiHost()
    const renderer = await createCliRenderer({
      targetFps: 30,
      exitOnCtrlC: false,
      useMouse: true,
      screenMode: "alternate-screen",
      externalOutputMode: "passthrough",
      consoleMode: "disabled",
    })
    return NanobotTui.mount(renderer, options, undefined, undefined, host)
  }

  static mount(
    renderer: CliRenderer,
    options: AppOptions,
    client?: ChatClient,
    treeSitterClient?: TreeSitterClient,
    host?: TuiHost,
    clipboardImageReader?: ClipboardImageReader,
  ): NanobotTui {
    return new NanobotTui(
      renderer,
      options,
      client,
      treeSitterClient,
      host,
      clipboardImageReader,
    )
  }

  async start(): Promise<void> {
    // Network setup and small menu payloads do not depend on terminal colors.
    // Start them while OSC theme detection is in flight instead of serializing
    // up to one second of otherwise independent startup work.
    this.client.connect()
    void this.loadCommands()
    void this.loadMentions()
    void this.loadSkills()
    this.runtimeControls.preload()
    this.renderer.start()
    // OpenTUI learns the real terminal background through OSC 10/11. Wait for
    // that bounded probe after first paint. The neutral terminal background is
    // safe to render immediately, and the detected palette can be applied later.
    if (this.options.theme === "auto") await this.renderer.waitForThemeMode(1_000)
    if (this.quitting) return
    if (this.options.theme === "auto" && this.renderer.themeMode) {
      this.applyTheme(this.renderer.themeMode)
    }
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
    const visibleContent = this.composer.plainText.trim()
    if (this.sessionLoading) {
      this.status.content = "Loading sessions…"
      return
    }
    if (this.runtimeControls.visible) {
      this.runtimeControls.choose()
      return
    }
    if (this.sessionMenu.visible) {
      const session = this.sessionMenu.choose()
      if (session) this.switchSession(session)
      return
    }
    if (this.branchMenu.visible) {
      const point = this.branchMenu.choose()
      if (point) this.createBranch(point.beforeUserIndex, point.preview)
      return
    }
    if (this.mentionMenu.visible && this.activeMentionQuery) {
      const candidate = this.mentionMenu.choose()
      if (candidate) this.chooseMention(candidate, this.activeMentionQuery)
      return
    }
    if (this.skillMenu.visible && this.activeSkillQuery) {
      const candidate = this.skillMenu.choose()
      if (candidate) {
        this.chooseSkill(candidate, this.activeSkillQuery)
        return
      }
      this.skillMenu.hide()
      this.activeSkillQuery = null
    }
    if (!visibleContent) return
    if (["exit", "quit", "/quit", ":q"].includes(visibleContent.toLowerCase())) {
      this.quit()
      return
    }
    if (["/continue", "/dismiss"].includes(visibleContent.toLowerCase())) {
      if (!this.ready) {
        this.markSubmitUnsent()
        return
      }
      this.clearComposer()
      this.commandMenu.hide()
      void this.updateRecovery(visibleContent.toLowerCase() === "/continue" ? "continue" : "dismiss")
      return
    }
    const completion = this.commandMenu.completion(visibleContent)
    if (completion) {
      this.setComposer(completion)
      this.commandMenu.hide()
      this.updateMeta()
      return
    }
    const command = this.commandMenu.resolve(visibleContent)
    if ((command || visibleContent.startsWith("!")) && this.draft.media(visibleContent).length) {
      this.status.content = "Images cannot be used with commands · remove the image first"
      return
    }
    if (command?.source === "tui") {
      if (command.command.action === "sessions") void this.openSessions()
      else if (command.command.action === "context") void this.openContext()
      else if (command.command.action === "diff") this.openDiff()
      else if (command.command.action === "branch") void this.openBranch()
      else if (command.command.action === "detach") this.quit(true)
      else if (command.command.action === "exit") this.quit()
      else this.startNewChat()
      return
    }
    if (command?.source === "gateway") {
      const lifecycle = resolveSlashCommandLifecycle(visibleContent, command.command)
      if (lifecycle) this.sendGatewayCommand(visibleContent, lifecycle)
      return
    }
    if (visibleContent.startsWith("!")) {
      this.sendGatewayCommand(visibleContent, "side_channel", false, { userShell: true })
      return
    }
    if (!this.ready) {
      this.markSubmitUnsent()
      return
    }
    const prompt = this.composerPrompt()
    if (!this.canSendPrompt(prompt)) return
    if (this.activeTurn) {
      this.sendPrompt(prompt, true)
      return
    }
    this.sendPrompt(prompt)
  }

  private sendPrompt(prompt: QueuedPrompt, steering = false): boolean {
    let turnId: string
    try {
      turnId = this.client.send(prompt.content, prompt.options)
    } catch {
      this.markSubmitUnsent(true)
      return false
    }
    this.unsentSubmit = false
    this.clearComposer()
    this.commandMenu.hide()
    this.mentionMenu.hide()
    this.skillMenu.hide()
    this.recordPrompt(prompt.content)
    this.transcript.user(
      prompt.content,
      turnId,
      prompt.options.media,
      prompt.displayContent,
    )
    this.host.reportTitle(prompt.content)
    if (steering) {
      this.renderActiveStatus()
      this.updateMeta()
      return true
    }
    this.beginTurn(turnId)
    return true
  }

  private beginTurn(turnId: string | null, startedAt?: number): void {
    this.activeTurnId = turnId
    this.readyDetail = ""
    this.finalMessage = ""
    this.turnHadAnswer = false
    this.activeLabel = "Thinking"
    this.currentFileEdits = []
    this.setActive(true, startedAt)
  }

  private reconcileTurnOwnership(event: {
    turn_id?: string
    active_turn_id?: string
    starts_turn?: boolean
    started_at?: number
  }): void {
    if (event.active_turn_id && this.activeTurn) {
      this.activeTurnId = event.active_turn_id
    } else if (event.active_turn_id || (event.starts_turn && !this.activeTurn)) {
      this.beginTurn(
        event.active_turn_id || event.turn_id || null,
        typeof event.started_at === "number" ? event.started_at * 1000 : undefined,
      )
    }
  }

  accept(event: InboundEvent): void {
    if (event.event === "attached") {
      const switchedSession = Boolean(this.currentChatId && this.currentChatId !== event.chat_id)
      this.currentChatId = event.chat_id
      if (event.usage) this.lastUsage = event.usage
      if (event.model_preset !== undefined) {
        this.applyModelPreset(event.model_preset)
        this.updateTitle()
      }
      this.commandTurns.clear()
      this.modelCommandTurns.clear()
      const restoring = this.attachedOnce
      this.attachedOnce = true
      if (restoring) {
        this.activeTurnId = null
        this.setActive(false)
      }
      const queuesEvents = restoring || (!this.historyLoaded && Boolean(this.options.chatId))
      if (queuesEvents) {
        this.ready = false
        this.pendingEvents = []
      }
      const hydrationId = ++this.hydrationId
      void this.prepareChat(event.chat_id, restoring, hydrationId).then(() => {
        if (hydrationId !== this.hydrationId) return
        this.applyRecoveryState(event.recovery_state ?? null)
        this.flushPendingEvents()
        this.syncQueuePreview()
        if (switchedSession) this.sendNextFollowUp()
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
        this.reconcileTurnOwnership(event)
        return
      case "user_message": {
        if (this.transcript.user(
          event.text,
          event.turn_id,
          event.media_urls,
        )) {
          this.recordPrompt(event.text)
        }
        this.host.reportTitle(event.text)
        this.reconcileTurnOwnership(event)
        return
      }
      case "delta":
        this.setActive(true)
        this.activeLabel = "Writing"
        this.turnHadAnswer = true
        this.transcript.stream(event.text)
        return
      case "message":
        if (event.turn_id && this.commandTurns.has(event.turn_id) && !event.kind) {
          const lifecycle = this.commandTurns.get(event.turn_id)
          if (lifecycle !== "agent_turn") {
            this.commandTurns.delete(event.turn_id)
            const silent = this.silentCommandTurns.delete(event.turn_id)
            if (this.modelCommandTurns.delete(event.turn_id)) {
              void this.refreshSessionMetadata(event.chat_id)
            }
            if (!silent) this.transcript.assistant(event.text)
            if (!this.activeTurn) this.status.content = "Ready"
            return
          }
        }
        if (event.kind) {
          this.activeLabel = event.kind === "tool_hint" ? "Working" : "Thinking"
          this.transcript.progress(event.text, event.tool_events)
          this.setActive(true)
        } else {
          this.finalMessage = event.text
        }
        return
      case "file_edit":
        this.activeLabel = "Editing"
        this.currentFileEdits = mergeFileEdits(this.currentFileEdits, event.edits)
        if (this.diffViewer.visible) this.diffViewer.update(this.currentFileEdits)
        this.transcript.fileEdits(event.edits)
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
        if (event.turn_id && this.activeTurnId && event.turn_id !== this.activeTurnId) return
        if (event.turn_id) {
          this.commandTurns.delete(event.turn_id)
          this.modelCommandTurns.delete(event.turn_id)
        }
        this.transcript.finishStream(this.turnHadAnswer ? "" : this.finalMessage)
        this.transcript.finishActivity()
        if (this.currentFileEdits.length) this.lastFileEdits = this.currentFileEdits
        this.currentFileEdits = []
        if (this.diffViewer.visible) this.diffViewer.update(this.lastFileEdits)
        this.finalMessage = ""
        this.turnHadAnswer = false
        this.activeTurnId = null
        if (event.usage) this.lastUsage = event.usage
        if (typeof event.context_window_tokens === "number") {
          this.contextWindowTokens = event.context_window_tokens
        }
        this.updateTitle()
        this.setActive(false)
        // A synthetic/rehydrated turn may already be idle, in which case
        // setActive(false) intentionally does not repaint the footer.
        this.updateMeta()
        this.readyDetail = typeof event.latency_ms === "number"
          ? `${(event.latency_ms / 1000).toFixed(1)}s`
          : ""
        this.status.content = this.readyStatus()
        if (this.contextTokens !== null) void this.refreshContextEstimate(event.chat_id)
        this.sendNextFollowUp()
        return
      case "goal_status":
        if (event.turn_id && this.activeTurnId && event.turn_id !== this.activeTurnId) return
        if (event.status === "running") {
          if (event.turn_id) this.activeTurnId = event.turn_id
          this.activeLabel = "Working"
          this.setActive(true, typeof event.started_at === "number" ? event.started_at * 1000 : undefined)
        } else {
          this.setActive(false)
        }
        return
      case "goal_state":
        return
      case "recovery_state":
        this.applyRecoveryState(event)
        return
      case "turn_model_updated":
        if (typeof event.context_window_tokens === "number") {
          this.contextWindowTokens = event.context_window_tokens
        }
        this.setTurnModel(event.model_name, event.model_preset)
        return
      case "runtime_model_updated":
        this.setDefaultModel(event.model_name, event.model_preset)
        return
      case "session_updated":
        if (event.workspace_scope) this.applyWorkspaceScope(event.workspace_scope)
        if (
          !this.sessionTitle
          || this.sessionTitle === "New chat"
          || this.sessionTitle === "Untitled chat"
          || event.scope === "metadata"
        ) {
          void this.refreshSessionMetadata(event.chat_id)
        }
        return
      case "error":
        const commandLifecycle = event.turn_id ? this.commandTurns.get(event.turn_id) : undefined
        if (event.turn_id) {
          this.commandTurns.delete(event.turn_id)
          this.modelCommandTurns.delete(event.turn_id)
          this.silentCommandTurns.delete(event.turn_id)
        }
        if (event.turn_id && this.activeTurnId && event.turn_id !== this.activeTurnId) {
          this.transcript.notice(event.reason || event.detail || "Unknown gateway error", true)
          return
        }
        this.transcript.finishStream(this.turnHadAnswer ? "" : this.finalMessage)
        this.transcript.notice(event.reason || event.detail || "Unknown gateway error", true)
        if (!commandLifecycle || commandLifecycle === "agent_turn") {
          if (this.currentFileEdits.length) this.lastFileEdits = this.currentFileEdits
          this.currentFileEdits = []
          if (this.diffViewer.visible) this.diffViewer.update(this.lastFileEdits)
        }
        this.finalMessage = ""
        this.turnHadAnswer = false
        this.restoreQueuedPrompts()
        this.setActive(false)
        return
    }
  }

  private async prepareChat(chatId: string, restoring: boolean, hydrationId: number): Promise<void> {
    try {
      if (restoring) {
        this.contextPanel.hide()
        this.diffViewer.hide()
        this.currentFileEdits = []
        this.lastFileEdits = []
        this.historyBeforeCursor = null
        this.historyHasMore = false
        this.historyLoadingOlder = false
        this.transcript.reset({
          model: this.modelName || this.modelPreset,
          workspace: this.options.workspace,
          version: this.options.version,
          access: this.options.access,
        })
      }
      if (restoring || (!this.historyLoaded && this.options.chatId)) {
        this.historyLoaded = true
        const history = await fetchHistory(
          this.options.apiUrl,
          this.options.apiToken,
          chatId,
          undefined,
          this.apiReauthenticator,
        )
        if (hydrationId !== this.hydrationId) return
        this.historyBeforeCursor = history.beforeCursor
        this.historyHasMore = history.hasMoreBefore
        this.transcript.history(history.messages)
        this.restorePromptHistory(history.messages)
        const reversedHistory = [...history.messages].reverse()
        const lastUser = reversedHistory.find((message) => message.role === "user")
        if (lastUser) this.host.reportTitle(lastUser.content)
        this.lastFileEdits = latestTurnFileEdits(history.messages)
        if (this.diffViewer.visible) this.diffViewer.update(this.lastFileEdits)
      }
    } catch (error) {
      if (hydrationId !== this.hydrationId) return
      this.transcript.notice(error instanceof Error ? error.message : String(error), true)
    } finally {
      if (hydrationId !== this.hydrationId) return
      this.ready = true
      if (!this.activeTurn) {
        this.status.content = this.readyStatus()
      }
    }
  }

  private flushPendingEvents(): void {
    const events = this.pendingEvents
    this.pendingEvents = null
    for (const event of events || []) this.accept(event)
  }

  private clearRecoveryState(): void {
    this.recoveryState = null
    this.recoveryPending = false
    this.recoveryNotice.hide()
  }

  private applyRecoveryState(state: RecoveryState | null): void {
    if (!state) {
      this.clearRecoveryState()
      return
    }
    this.recoveryState = state
    this.recoveryPending = false
    if (state.status === "resuming") {
      this.recoveryNotice.hide()
      this.activeLabel = "Continuing"
      this.setActive(true)
      return
    }
    if (state.status === "awaiting_user" || state.status === "failed") {
      this.activeTurnId = null
      this.setActive(false)
      this.recoveryNotice.show(state)
      this.status.content = state.can_continue === false
        ? "Interrupted · dismiss to start a new message"
        : "Interrupted · continue or dismiss"
      this.composer.focus()
      return
    }
    this.clearRecoveryState()
    this.activeTurnId = null
    this.setActive(false)
    if (this.ready) this.status.content = this.readyStatus()
  }

  private async updateRecovery(action: "continue" | "dismiss"): Promise<void> {
    const state = this.recoveryState
    if (
      !state
      || (state.status !== "awaiting_user" && state.status !== "failed")
      || (action === "continue" && state.can_continue === false)
    ) {
      this.status.content = "No interrupted task"
      this.composer.focus()
      return
    }
    if (this.recoveryPending) return
    this.recoveryPending = true
    this.recoveryNotice.setBusy(true)
    this.status.content = action === "continue" ? "Continuing…" : "Dismissing…"
    try {
      const next = await this.client.updateRecovery(
        action,
        this.client.activeChatId,
        state.recovery_id,
      )
      if (this.recoveryState?.recovery_id === state.recovery_id) {
        this.applyRecoveryState(next)
      }
    } catch (error) {
      if (this.recoveryState?.recovery_id !== state.recovery_id) return
      this.recoveryPending = false
      this.recoveryNotice.setBusy(false)
      this.status.content = error instanceof Error ? error.message : String(error)
    } finally {
      this.composer.focus()
    }
  }

  private updateGatewayApiConnection(apiUrl: string, apiToken: string): void {
    this.options.apiUrl = apiUrl
    this.options.apiToken = apiToken
    this.runtimeControls.useApiConnection(apiUrl, apiToken)
  }

  private useGatewayConnection(apiUrl: string, apiToken: string): void {
    this.updateGatewayApiConnection(apiUrl, apiToken)
    void this.loadCommands()
    void this.loadMentions()
    void this.loadSkills()
  }

  private async refreshApiConnection(
    rejectedApiToken: string,
  ): Promise<GatewayApiConnection> {
    if (this.options.apiToken && rejectedApiToken !== this.options.apiToken) {
      return { apiUrl: this.options.apiUrl, apiToken: this.options.apiToken }
    }
    if (this.apiRefreshPromise) return this.apiRefreshPromise
    const refresh = fetchGatewayConnection(
      this.options.bootstrapUrl || "",
      this.options.bootstrapSecret || "",
      this.options.apiUrl,
      `tui-${process.pid}`,
    ).then((connection) => {
      this.updateGatewayApiConnection(connection.apiUrl, connection.apiToken)
      return connection
    })
    this.apiRefreshPromise = refresh
    try {
      return await refresh
    } finally {
      if (this.apiRefreshPromise === refresh) this.apiRefreshPromise = null
    }
  }

  private handleStatus(
    status: ConnectionStatus,
    _detail?: string,
    info?: ConnectionStatusInfo,
  ): void {
    // Invalid frames do not mean the transport is unavailable. Keep the last
    // accurate user-facing state unless the protocol supplied connection diagnostics.
    if (status === "error" && !info) return
    this.connectionMessage = connectionStatusText(status, info)
    if (status === "connected") {
      this.ready = false
      this.renderConnectionMessage()
      return
    }
    if (["starting", "connecting", "reconnecting", "unavailable"].includes(status)) {
      this.ready = false
      if (status === "reconnecting" || status === "unavailable") this.setActive(false)
      this.renderConnectionMessage()
      return
    }
    if (status === "error") {
      if (info) this.ready = false
      this.setActive(false)
      this.renderConnectionMessage()
      return
    }
    if (!this.quitting) {
      this.ready = false
      this.setActive(false)
      this.renderConnectionMessage()
    }
  }

  private renderConnectionMessage(): void {
    this.status.content = this.unsentSubmit
      ? `Not sent · press Enter to retry when ready · ${this.connectionMessage}`
      : this.connectionMessage
  }

  private markSubmitUnsent(sendFailed = false): void {
    this.unsentSubmit = true
    if (sendFailed) {
      this.status.content = "Not sent · send failed; press Enter to retry when ready"
      return
    }
    this.renderConnectionMessage()
  }

  private setActive(active: boolean, startedAt?: number): void {
    if (this.activeTurn === active) {
      if (active && startedAt !== undefined) this.activeStartedAt = startedAt
      return
    }
    this.activeTurn = active
    this.updateMeta()
    this.syncComposerPlaceholder()
    if (active) {
      this.activeStartedAt = startedAt ?? Date.now()
      this.shimmerFrame = 0
      this.renderActiveStatus()
      this.shimmerTimer = setInterval(() => {
        this.shimmerFrame += 1
        this.renderActiveStatus()
      }, SHIMMER_INTERVAL_MS)
      return
    }
    if (this.shimmerTimer) clearInterval(this.shimmerTimer)
    this.shimmerTimer = null
    this.status.content = this.readyStatus()
  }

  private renderActiveStatus(): void {
    if (this.sessionLoading || this.sessionMenu.visible) return
    const elapsed = formatElapsed(Date.now() - this.activeStartedAt)
    const navigation = this.transcriptNavigation.awayFromBottom ? " · Ctrl+End latest" : ""
    const queued = this.promptQueue.length ? ` · ${this.promptQueue.length} queued` : ""
    this.status.content = shimmerStatus(
      this.activeLabel,
      `  ${elapsed}${queued}${navigation}`,
      this.shimmerFrame,
      this.palette,
    )
  }

  private readyStatus(detail = this.readyDetail): string {
    if (this.unsentSubmit) return "Not sent · press Enter to retry"
    if (this.transcriptNavigation.awayFromBottom) {
      return this.transcriptNavigation.unseenOutput
        ? "New output · Ctrl+End latest"
        : "History · Ctrl+End latest"
    }
    if (detail) return `Ready · ${detail}`
    return this.historyHasMore ? "Ready · PageUp for earlier history" : "Ready"
  }

  private sendNextFollowUp(): void {
    if (!this.ready || this.activeTurn || this.quitting) return
    const prompt = this.promptQueue.takeFollowUp()
    if (!prompt) return
    this.syncQueuePreview()
    this.sendPrompt(prompt)
  }

  private get promptQueue(): PromptQueue {
    const chatId = this.currentChatId || this.client.activeChatId
    let queue = this.promptQueues.get(chatId)
    if (!queue) {
      queue = new PromptQueue()
      this.promptQueues.set(chatId, queue)
    }
    return queue
  }

  private composerPrompt(): QueuedPrompt {
    const visible = this.composer.plainText.trim()
    const content = this.draft.expand(visible).trim()
    const media = this.draft.media(visible)
    const displayContent = this.draft.display(visible).trim()
    return {
      content,
      ...(media.length ? { displayContent } : {}),
      options: {
        ...mentionOptions(content, this.availableMentions()),
        ...(media.length ? { media } : {}),
      },
    }
  }

  private hasPrompt(prompt: QueuedPrompt): boolean {
    return Boolean(prompt.content || prompt.options.media?.length)
  }

  private canSendPrompt(prompt: QueuedPrompt): boolean {
    if (this.draft.hasImageLabelConflict(this.composer.plainText)) {
      this.status.content = "Duplicate image placeholder text · rename or remove it before sending"
      return false
    }
    if (!this.hasPrompt(prompt)) return false
    if ((prompt.options.media?.length || 0) <= MAX_DRAFT_IMAGES) return true
    this.status.content = `Remove images until ${MAX_DRAFT_IMAGES} or fewer remain`
    return false
  }

  private restoreQueuedPrompts(): void {
    const queued = this.promptQueue.restore()
    if (!queued.length) return
    this.syncQueuePreview()
    const current = this.draft.expand(this.composer.plainText).trim()
    this.setComposer([current, ...queued.map((prompt) => prompt.content)].filter(Boolean).join("\n\n"))
  }

  private queueFollowUp(): void {
    if (!this.activeTurn || !this.ready) return
    const visibleContent = this.composer.plainText.trim()
    if (this.draft.media(visibleContent).length) {
      this.status.content = "Images cannot be queued · press Enter to send now"
      return
    }
    const content = this.draft.expand(visibleContent).trim()
    if (!content) return
    this.promptQueue.enqueue({
      content,
      options: mentionOptions(content, this.availableMentions()),
    })
    this.clearComposer()
    this.commandMenu.hide()
    this.mentionMenu.hide()
    this.skillMenu.hide()
    this.recordPrompt(content)
    this.syncQueuePreview()
    this.renderActiveStatus()
    this.updateMeta()
  }

  private editLastFollowUp(): boolean {
    const prompt = this.promptQueue.takeLast()
    if (!prompt) return false
    const current = this.draft.expand(this.composer.plainText).trim()
    this.setComposer([prompt.content, current].filter(Boolean).join("\n\n"))
    this.syncQueuePreview()
    this.renderActiveStatus()
    this.updateMeta()
    return true
  }

  private clearPromptQueue(): void {
    this.promptQueue.clear()
    this.syncQueuePreview()
  }

  private syncQueuePreview(): void {
    this.queuePreview.update(this.promptQueue.snapshot().map(({ content }) => content))
  }

  private handleTranscriptNavigation(state: TranscriptNavigation): void {
    this.transcriptNavigation = state
    if (this.activeTurn) this.renderActiveStatus()
    else if (this.ready) this.status.content = this.readyStatus()
    this.updateMeta()
  }

  private handleKey = (key: KeyEvent): void => {
    if (this.diffViewer.visible) {
      if (key.ctrl && key.name === "c") {
        const selected = this.renderer.getSelection()?.getSelectedText()
        if (selected) void this.copySelection(selected)
      } else if (this.diffViewer.handleKey(key) && !this.diffViewer.visible) {
        this.composer.focus()
        this.status.content = this.readyStatus()
        this.updateMeta()
      }
      key.preventDefault()
      return
    }
    if (this.contextPanel.visible && key.name === "escape") {
      this.contextPanel.hide()
      this.status.content = this.readyStatus()
      this.updateMeta()
      key.preventDefault()
      return
    }
    if (this.sessionLoading && key.name === "escape") {
      this.closeSessions()
      this.status.content = this.readyStatus()
      key.preventDefault()
      return
    }
    if (this.runtimeControls.handleKey(key)) return
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
    if (this.branchMenu.visible) {
      if (!key.ctrl && !key.meta && (key.name === "up" || key.name === "down")) {
        this.branchMenu.move(key.name === "up" ? -1 : 1)
        key.preventDefault()
        return
      }
      if (key.name === "escape") {
        this.closeBranch()
        key.preventDefault()
        return
      }
    }
    if (this.mentionMenu.visible) {
      if (!key.ctrl && !key.meta && (key.name === "up" || key.name === "down")) {
        this.mentionMenu.move(key.name === "up" ? -1 : 1)
        key.preventDefault()
        return
      }
      if (!key.ctrl && !key.meta && key.name === "tab" && this.activeMentionQuery) {
        const candidate = this.mentionMenu.choose()
        if (candidate) this.chooseMention(candidate, this.activeMentionQuery)
        key.preventDefault()
        return
      }
      if (key.name === "escape") {
        this.mentionMenu.hide()
        this.activeMentionQuery = null
        this.updateMeta()
        key.preventDefault()
        return
      }
    }
    if (this.skillMenu.visible) {
      if (!key.ctrl && !key.meta && (key.name === "up" || key.name === "down")) {
        this.skillMenu.move(key.name === "up" ? -1 : 1)
        key.preventDefault()
        return
      }
      if (!key.ctrl && !key.meta && key.name === "tab" && this.activeSkillQuery) {
        const candidate = this.skillMenu.choose()
        if (candidate) {
          this.chooseSkill(candidate, this.activeSkillQuery)
          key.preventDefault()
          return
        }
        this.skillMenu.hide()
        this.activeSkillQuery = null
        this.updateMeta()
        key.preventDefault()
        return
      }
      if (key.name === "escape") {
        this.skillMenu.hide()
        this.activeSkillQuery = null
        this.updateMeta()
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
    if (
      (key.ctrl || key.meta)
      && key.name.toLocaleLowerCase() === "v"
      && !this.sessionLoading
      && !this.sessionMenu.visible
      && !this.branchMenu.visible
      && !this.contextPanel.visible
    ) {
      key.preventDefault()
      void this.pasteClipboardImage()
      return
    }
    if (this.activeTurn && !key.ctrl && !key.meta && key.name === "tab") {
      this.queueFollowUp()
      key.preventDefault()
      return
    }
    if (this.activeTurn && key.meta && key.name === "up") {
      if (this.editLastFollowUp()) key.preventDefault()
      return
    }
    if (key.ctrl && key.name === "o") {
      const expanded = this.transcript.toggleActivityDetails()
      if (expanded === null) return
      this.status.content = expanded ? "Tool details expanded" : "Tool details collapsed"
      key.preventDefault()
      return
    }
    if (!key.ctrl && !key.meta && !key.shift && (key.name === "left" || key.name === "right")) {
      const direction = key.name === "left" ? -1 : 1
      const target = this.draft.moveImageCursor(
        this.composer.plainText,
        this.composerStringCursor(),
        direction,
      )
      if (target !== null) {
        this.composerCursor = target
        this.setComposerStringCursor(this.composer.plainText, target)
        key.preventDefault()
        return
      }
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
        this.restoreQueuedPrompts()
        try {
          this.client.send("/stop")
          this.status.content = "Stopping…"
        } catch {
          this.setActive(false)
        }
      } else if (this.composer.plainText) {
        this.clearComposer()
        this.status.content = this.readyStatus()
      } else {
        // Finish dispatching the raw ETX before destroy() restores terminal input.
        // Releasing the terminal from inside this callback can leak the same Ctrl+C
        // to the parent shell on Windows terminals.
        setTimeout(() => this.quit(), 0)
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
      const pageUp = key.name === "pageup"
      const wasAtTop = this.transcript.atTop
      this.transcript.scrollByPage(pageUp ? -1 : 1)
      if (pageUp && (wasAtTop || this.transcript.atTop)) void this.loadOlderHistory()
      return
    }
    if (key.ctrl && (key.name === "home" || key.name === "end")) {
      key.preventDefault()
      this.transcript.scrollToEdge(key.name === "home" ? "top" : "bottom")
    }
  }

  private navigateHistory(direction: -1 | 1): boolean {
    if (this.promptHistory.length === 0 || this.draft.imageCount) return false
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

  private handleCapabilities = (): void => {
    this.updateMeta()
  }

  private resolveThemeMode(detected: ThemeMode | null): ThemeMode {
    return this.options.theme === "auto" ? detected ?? "dark" : this.options.theme
  }

  private applyTheme(mode: ThemeMode): void {
    const backgroundWasUnknown = !this.backgroundKnown
    this.backgroundKnown = true
    if (this.activeThemeMode === mode && !backgroundWasUnknown) return
    this.activeThemeMode = mode
    this.palette = mode === "light" ? LIGHT : DARK
    this.transcript.setTheme(transcriptTheme(this.palette, this.backgroundKnown))
    this.commandMenu.setTheme(commandMenuTheme(this.palette))
    this.sessionMenu.setTheme(commandMenuTheme(this.palette))
    this.mentionMenu.setTheme(commandMenuTheme(this.palette))
    this.skillMenu.setTheme(commandMenuTheme(this.palette))
    this.branchMenu.setTheme(commandMenuTheme(this.palette))
    this.runtimeControls.setTheme(runtimeControlsTheme(this.palette))
    this.contextPanel.setTheme(contextPanelTheme(this.palette))
    this.diffViewer.setTheme(diffViewerTheme(this.palette, this.backgroundKnown))
    this.queuePreview.setTheme(queuePreviewTheme(this.palette))
    this.recoveryNotice.setTheme(recoveryNoticeTheme(this.palette))
    this.updateComposerAppearance()
    this.composer.textColor = this.palette.text
    this.composer.focusedTextColor = this.palette.text
    this.composer.cursorColor = this.palette.accent
    const previousComposerSyntax = this.composerSyntax
    this.composerSyntax = composerSyntaxStyle(this.palette)
    this.composer.syntaxStyle = this.composerSyntax
    this.syncComposerImageHighlights(this.composer.plainText)
    void this.renderer.idle().catch(() => {}).finally(() => previousComposerSyntax.destroy())
    this.status.fg = this.palette.muted
    this.meta.fg = this.palette.faint
    this.updateMeta()
  }

  private handleResize = (): void => {
    this.resizeComposer()
    this.syncComposerPlaceholder()
    this.contextPanel.resize(this.renderer.height)
    this.diffViewer.resize(this.renderer.width)
    this.title.visible = this.renderer.height >= 14
    this.runtimeControls.resize(this.renderer.width)
    this.updateTitle()
    this.updateMeta()
  }

  private updateMeta(): void {
    const mode: FooterMode = this.runtimeControls.visible ? "runtime"
      : this.mentionMenu.visible ? "mention"
      : this.skillMenu.visible ? "skill"
      : this.activeTurn ? "active"
      : this.branchMenu.visible ? "branch"
      : this.commandMenu.visible ? "command"
      : this.sessionMenu.visible ? "session"
      : this.contextPanel.visible ? "context"
      : this.transcriptNavigation.awayFromBottom ? "history"
      : "ready"
    if (mode === "ready") {
      this.meta.content = footerTelemetry(
        this.lastUsage,
        this.renderer.width,
        footerHintTheme(this.palette),
      )
      return
    }
    this.meta.content = contextualFooterHints(
      mode,
      this.renderer.width,
      footerHintTheme(this.palette),
      process.platform,
      Boolean(this.renderer.capabilities?.kitty_keyboard),
    )
  }

  private setTurnModel(model: string, preset?: string | null): void {
    this.modelName = model
    this.modelPreset = preset?.trim() || "default"
    this.updateTitle()
  }

  private setDefaultModel(model: string, preset?: string | null): void {
    this.defaultModelName = model
    this.defaultModelPreset = preset?.trim() || "default"
    if (this.sessionModelPreset === null) {
      this.modelName = this.defaultModelName
      this.modelPreset = this.defaultModelPreset
      this.updateTitle()
    }
  }

  private applySessionModel(session: SessionSummary): void {
    this.applyModelPreset(session.modelPreset)
  }

  private applySessionScope(session: SessionSummary): void {
    if (session.workspaceScope) this.applyWorkspaceScope(session.workspaceScope)
  }

  private applyModelPreset(preset: string | null): void {
    const currentModel = this.modelName
    const currentPreset = this.modelPreset
    this.sessionModelPreset = preset
    this.modelPreset = preset || this.defaultModelPreset
    this.modelName = this.modelPreset === this.defaultModelPreset
      ? this.defaultModelName
      : this.modelPreset === currentPreset ? currentModel : ""
  }

  private updateTitle(): void {
    const context = this.contextTokens === null
      ? ""
      : `     ~${formatTokenCount(this.contextTokens)}${this.contextWindowTokens
        ? `/${formatTokenCount(this.contextWindowTokens)}`
        : ""} ctx`
    this.runtimeControls.updateModel(this.modelName, this.modelPreset)
    this.runtimeControls.updateContext(context)
  }

  private resizeComposer(): void {
    const verticalPadding = this.renderer.height >= 12 ? 1 : 0
    const maxContentHeight = Math.max(1, Math.min(12, Math.floor(this.renderer.height / 3)))
    this.composer.minHeight = 1
    this.composer.maxHeight = maxContentHeight
    this.composerFrame.paddingTop = verticalPadding
    this.composerFrame.paddingBottom = verticalPadding
    this.composerFrame.minHeight = 1 + verticalPadding * 2
    this.composerFrame.maxHeight = maxContentHeight + verticalPadding * 2
  }

  private composerSurface(): RGBA {
    return this.backgroundKnown
      ? RGBA.fromHex(this.palette.userBackground)
      : RGBA.defaultBackground()
  }

  private updateComposerAppearance(): void {
    const surface = this.composerSurface()
    this.composerFrame.backgroundColor = surface
    this.composerFrame.borderColor = this.palette.accent
    this.composer.backgroundColor = surface
    this.composer.focusedBackgroundColor = surface
    this.composer.placeholderColor = this.palette.muted
  }

  private syncComposerPlaceholder(): void {
    // OpenTUI normally suppresses placeholder glyphs while the editor is not
    // empty. Explicitly removing them also invalidates their old cells, which
    // prevents stale placeholder text in differential/embedded terminals.
    const activePlaceholder = this.renderer.width >= 40
      ? ACTIVE_COMPOSER_PLACEHOLDER
      : COMPACT_ACTIVE_COMPOSER_PLACEHOLDER
    const placeholder = this.composer.plainText
      ? null
      : this.sessionMenu.visible
        ? "Search sessions"
        : this.branchMenu.visible
          ? "Search branch points"
          : this.activeTurn ? activePlaceholder : COMPOSER_PLACEHOLDER
    if (this.composer.placeholder !== placeholder) this.composer.placeholder = placeholder
  }

  private syncCommandMenu(): void {
    const limit = this.renderer.height >= 20 ? 7 : 3
    this.commandMenu.update(this.composer.plainText, limit)
    this.updateMeta()
  }

  private syncComposerMenus(): void {
    const value = this.composer.plainText
    const cursor = this.composerStringCursor()
    this.activeMentionQuery = mentionQuery(value, cursor)
    this.activeSkillQuery = skillQuery(value, cursor)
    const mentionCandidates = this.availableMentions()
    if (this.activeMentionQuery && mentionCandidates.length) {
      this.commandMenu.hide()
      this.skillMenu.hide()
      const limit = this.renderer.height >= 20 ? 7 : 4
      if (this.mentionMenu.visible) this.mentionMenu.update(this.activeMentionQuery.query, limit)
      else this.mentionMenu.show(mentionCandidates, this.activeMentionQuery.query, limit)
      this.updateMeta()
      return
    }
    this.mentionMenu.hide()
    if (this.activeSkillQuery && this.skillCandidates.length) {
      this.commandMenu.hide()
      const limit = this.renderer.height >= 20 ? 7 : 4
      if (this.skillMenu.visible) this.skillMenu.update(this.activeSkillQuery.query, limit)
      else this.skillMenu.show(this.skillCandidates, this.activeSkillQuery.query, limit)
      this.updateMeta()
      return
    }
    this.skillMenu.hide()
    this.syncCommandMenu()
  }

  private syncSessionMenu(): void {
    const limit = this.renderer.height >= 20 ? 8 : 4
    this.sessionMenu.update(this.composer.plainText, limit)
    this.updateMeta()
  }

  private syncBranchMenu(): void {
    const limit = this.renderer.height >= 20 ? 8 : 4
    this.branchMenu.update(this.composer.plainText, limit)
    this.updateMeta()
  }

  private chooseMention(candidate: MentionCandidate, query: MentionQuery): void {
    const inserted = insertMention(this.composer.plainText, candidate, query)
    this.composer.setText(inserted.value)
    this.setComposerStringCursor(inserted.value, inserted.cursor)
    this.mentionMenu.hide()
    this.activeMentionQuery = null
    this.syncComposerPlaceholder()
    this.updateMeta()
  }

  private chooseSkill(candidate: SkillCandidate, query: SkillQuery): void {
    const inserted = insertSkill(this.composer.plainText, candidate, query)
    this.composer.setText(inserted.value)
    this.setComposerStringCursor(inserted.value, inserted.cursor)
    this.skillMenu.hide()
    this.activeSkillQuery = null
    this.syncComposerPlaceholder()
    this.updateMeta()
  }

  private composerStringCursor(): number {
    return this.composer.editBuffer.getTextRange(0, this.composer.cursorOffset).length
  }

  private keepComposerCursorOutsideImages(): void {
    if (this.reconcilingComposer) return
    const value = this.composer.plainText
    const cursor = this.composerStringCursor()
    const target = this.draft.snapImageCursor(value, cursor, this.composerCursor)
    this.composerCursor = target
    if (target !== cursor) this.setComposerStringCursor(value, target)
  }

  private handleComposerContentChange(): void {
    if (this.reconcilingComposer) return
    let value = this.composer.plainText
    let cursor = this.composerStringCursor()
    const edit = this.draft.reconcileImageEdit(this.composerValue, value, cursor)
    if (edit.value !== value) {
      this.reconcilingComposer = true
      try {
        this.composer.replaceText(edit.value)
        this.composer.clearSelection()
        this.setComposerStringCursor(edit.value, edit.cursor)
      } finally {
        this.reconcilingComposer = false
      }
      value = edit.value
      cursor = edit.cursor
    }
    this.composerValue = value
    this.composerCursor = cursor
    this.draft.prune(value)
    this.syncComposerImageHighlights(value)
    const clearedUnsent = this.unsentSubmit && !value.trim()
    if (clearedUnsent) this.unsentSubmit = false
    this.runtimeControls.hide()
    if (this.contextPanel.visible && value) this.contextPanel.hide()
    this.syncComposerPlaceholder()
    if (this.sessionMenu.visible) this.syncSessionMenu()
    else if (this.branchMenu.visible) this.syncBranchMenu()
    else this.syncComposerMenus()
    this.resizeComposer()
    if (clearedUnsent && !this.activeTurn) {
      this.status.content = this.ready ? this.readyStatus() : this.connectionMessage
    }
    if (edit.removedImages.length) {
      this.status.content = `Removed ${edit.removedImages.join(", ")}`
    }
  }

  private setComposerStringCursor(value: string, cursor: number): void {
    this.composer.cursorOffset = this.composerOffsetForStringIndex(value, cursor)
  }

  private composerOffsetForStringIndex(value: string, cursor: number): number {
    const target = Math.min(Math.max(cursor, 0), value.length)
    const before = value.slice(0, target)
    const row = before.split("\n").length - 1
    const line = before.slice(before.lastIndexOf("\n") + 1)
    let offset = row === 0 ? 0 : this.composer.editBuffer.getLineStartOffset(row)
    const maxColumn = Math.max(8, line.length * 8 + 8)
    for (let column = 0; column <= maxColumn; column += 1) {
      const candidate = this.composer.editBuffer.positionToOffset(row, column)
      if (candidate === 0 && (row !== 0 || column !== 0)) break
      const candidateLength = this.composer.editBuffer.getTextRange(0, candidate).length
      if (candidateLength > target) break
      if (candidateLength === target) offset = candidate
    }
    return offset
  }

  private syncComposerImageHighlights(value: string): void {
    this.composer.clearAllHighlights()
    const styleId = this.composerSyntax.getStyleId(IMAGE_PLACEHOLDER_STYLE)
    if (styleId === null) return
    for (const range of this.draft.imagePlaceholderRanges(value)) {
      this.composer.addHighlightByCharRange({
        start: this.composerOffsetForStringIndex(value, range.start),
        end: this.composerOffsetForStringIndex(value, range.end),
        styleId,
        priority: 100,
      })
    }
  }

  private setComposer(content: string): void {
    this.clipboardPasteGeneration += 1
    this.draft.clear()
    this.composer.setText(content)
    this.composer.cursorOffset = content.length
  }

  private clearComposer(): void {
    this.unsentSubmit = false
    this.setComposer("")
  }

  private async pasteClipboardImage(): Promise<void> {
    if (this.clipboardImagePending) return
    if (this.draft.imageCount >= MAX_DRAFT_IMAGES) {
      this.status.content = `A message can include up to ${MAX_DRAFT_IMAGES} images`
      return
    }
    const generation = this.clipboardPasteGeneration
    this.clipboardImagePending = true
    this.status.content = "Reading clipboard image…"
    try {
      const image = await this.clipboardImageReader.read()
      if (this.quitting || generation !== this.clipboardPasteGeneration) return
      const insertion = this.draft.image(image, this.composer.plainText)
      if (!insertion) {
        this.status.content = `A message can include up to ${MAX_DRAFT_IMAGES} images`
        return
      }
      this.composer.insertText(insertion.text)
      this.status.content = `Pasted ${insertion.description} · review before sending`
    } catch (error) {
      if (
        this.quitting
        || this.composer.isDestroyed
        || generation !== this.clipboardPasteGeneration
      ) return
      const message = error instanceof Error
        ? error.message
        : "Clipboard image paste is unavailable"
      this.status.content = message
      this.transcript.notice(message, true)
    } finally {
      this.clipboardImagePending = false
    }
  }

  private handlePaste(event: PasteEvent): void {
    event.preventDefault()
    const value = stripAnsiSequences(decodePasteBytes(event.bytes))
    const insertion = this.draft.paste(value)
    if (!insertion.text) return
    this.composer.insertText(insertion.text)
    if (insertion.compacted) {
      this.status.content = `Pasted ${insertion.description} · review before sending`
    }
  }

  private async loadCommands(): Promise<void> {
    let discovered: SlashCommand[] = []
    try {
      discovered = await fetchSlashCommands(
        this.options.apiUrl,
        this.options.apiToken,
        this.apiReauthenticator,
      )
    } catch {
      // Local navigation remains available against older gateways.
    }
    const commands = new Map(discovered.map((command) => [command.command, command]))
    this.commandMenu.setCommands([...commands.values()], LOCAL_COMMANDS)
    this.syncCommandMenu()
  }

  private closeTransientMenus(): void {
    this.commandMenu.hide()
    this.hideSessionMenu()
    this.mentionMenu.hide()
    this.skillMenu.hide()
    this.branchMenu.hide()
    this.contextPanel.hide()
    this.activeMentionQuery = null
    this.activeSkillQuery = null
  }

  private dismissRuntimeControls(): void {
    if (this.runtimeControls.visible) this.runtimeControls.hide()
  }

  private applyWorkspaceScope(scope: WorkspaceScopePayload): void {
    this.runtimeControls.updateWorkspaceScope(scope)
    this.updateTitle()
    if (!this.activeTurn && this.ready) this.status.content = this.readyStatus()
  }

  private async loadMentions(): Promise<void> {
    try {
      this.mentionCandidates = await fetchMentionCandidates(
        this.options.apiUrl,
        this.options.apiToken,
        this.apiReauthenticator,
      )
      if (this.activeMentionQuery) this.syncComposerMenus()
    } catch {
      // Mentions are additive; plain text input remains fully functional.
    }
  }

  private async loadSkills(): Promise<void> {
    const loadId = ++this.skillLoadId
    try {
      const candidates = await fetchAvailableSkills(
        this.options.apiUrl,
        this.options.apiToken,
        this.apiReauthenticator,
      )
      if (loadId !== this.skillLoadId) return
      this.skillCandidates = candidates
      if (this.activeSkillQuery) {
        this.skillMenu.hide()
        this.syncComposerMenus()
      }
    } catch {
      // Skill completion is additive; explicit $skill-name input still works.
    }
  }

  private availableMentions(): MentionCandidate[] {
    const currentKey = this.client.activeChatId
      ? `websocket:${this.client.activeChatId}`
      : ""
    return this.mentionCandidates.filter((candidate) => (
      candidate.session?.session_key !== currentKey
    ))
  }

  private async openBranch(): Promise<void> {
    if (this.activeTurn) {
      this.status.content = "Wait for the current turn or press Ctrl+C"
      return
    }
    if (!this.ready) {
      this.status.content = "Preparing chat…"
      return
    }
    this.commandMenu.hide()
    this.hideSessionMenu()
    this.contextPanel.hide()
    this.clearComposer()
    this.status.content = "Loading branch points…"
    const chatId = this.client.activeChatId
    try {
      const history = await fetchHistory(
        this.options.apiUrl,
        this.options.apiToken,
        chatId,
        undefined,
        this.apiReauthenticator,
      )
      if (chatId !== this.client.activeChatId) return
      const points = branchPoints(history.messages)
      const limit = this.renderer.height >= 20 ? 8 : 4
      this.branchMenu.open(points, limit)
      this.syncComposerPlaceholder()
      this.updateMeta()
      this.status.content = points.length ? `${points.length} branch points` : "No completed replies"
    } catch (error) {
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private createBranch(beforeUserIndex: number, preview: string): void {
    if (!this.ready || this.activeTurn) return
    this.branchMenu.hide()
    this.clearComposer()
    try {
      if (!this.client.forkChat) throw new Error("branching is unavailable")
      this.ready = false
      this.clearPromptQueue()
      this.sessionMetadataId += 1
      this.sessionTitle = `Fork · ${preview.slice(0, 48)}`
      this.host.reportTitle(preview)
      this.contextTokens = null
      this.lastUsage = null
      this.readyDetail = ""
      this.updateTitle()
      this.status.content = "Creating branch…"
      this.client.forkChat(
        this.client.activeChatId,
        beforeUserIndex,
        this.sessionTitle,
      )
    } catch (error) {
      this.ready = true
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private closeBranch(): void {
    this.branchMenu.hide()
    this.clearComposer()
    this.syncComposerPlaceholder()
    if (!this.activeTurn && this.ready) this.status.content = this.readyStatus()
    this.updateMeta()
  }

  private async openSessions(): Promise<void> {
    this.commandMenu.hide()
    this.dismissRuntimeControls()
    this.mentionMenu.hide()
    this.skillMenu.hide()
    this.branchMenu.hide()
    this.contextPanel.hide()
    this.clearComposer()
    this.sessionLoading = true
    const loadId = ++this.sessionLoadId
    this.status.content = "Loading sessions…"
    try {
      const sessions = await fetchSessions(
        this.options.apiUrl,
        this.options.apiToken,
        this.apiReauthenticator,
      )
      if (this.quitting || loadId !== this.sessionLoadId) return
      this.sessionLoading = false
      const current = sessions.find((session) => session.chatId === this.client.activeChatId)
      if (current) {
        this.sessionTitle = sessionLabel(current)
        this.applySessionModel(current)
        this.applySessionScope(current)
        this.applyRecoveryState(current.recoveryState ?? null)
        this.updateTitle()
      }
      const limit = this.renderer.height >= 20 ? 8 : 4
      this.sessionMenu.open(
        sessions,
        this.client.activeChatId,
        limit,
        this.defaultModelPreset,
      )
      this.startSessionRefresh()
      this.sessionMenu.update(this.composer.plainText, limit)
      this.syncComposerPlaceholder()
      this.updateMeta()
      this.status.content = sessions.length ? `${sessions.length} sessions` : "No saved sessions"
    } catch (error) {
      if (loadId !== this.sessionLoadId) return
      this.sessionLoading = false
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private switchSession(session: SessionSummary): void {
    this.sessionMenu.markRead(session.chatId)
    if (session.chatId === this.client.activeChatId) {
      this.sessionTitle = sessionLabel(session)
      this.applySessionModel(session)
      this.applySessionScope(session)
      this.applyRecoveryState(session.recoveryState ?? null)
      this.updateTitle()
      this.closeSessions()
      return
    }
    if (!this.ready) {
      this.status.content = "Preparing chat…"
      return
    }
    this.closeSessions()
    try {
      this.ready = false
      this.activeTurnId = null
      this.setActive(false)
      this.clearRecoveryState()
      this.queuePreview.update([])
      this.sessionMetadataId += 1
      this.host.reportTitle("")
      this.sessionTitle = sessionLabel(session)
      this.applySessionModel(session)
      this.applySessionScope(session)
      this.contextTokens = null
      this.lastUsage = null
      this.readyDetail = ""
      this.updateTitle()
      this.status.content = "Opening session…"
      this.client.attach(session.chatId)
    } catch (error) {
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private startNewChat(): void {
    if (this.activeTurn) {
      this.status.content = "Wait for the current turn or press Ctrl+C"
      return
    }
    if (!this.ready) {
      this.status.content = "Preparing chat…"
      return
    }
    this.commandMenu.hide()
    this.hideSessionMenu()
    this.mentionMenu.hide()
    this.skillMenu.hide()
    this.branchMenu.hide()
    this.contextPanel.hide()
    this.clearComposer()
    try {
      this.ready = false
      this.clearRecoveryState()
      this.clearPromptQueue()
      this.sessionMetadataId += 1
      this.host.reportTitle("")
      this.sessionTitle = "New chat"
      this.sessionModelPreset = null
      this.modelName = this.defaultModelName
      this.modelPreset = this.defaultModelPreset
      this.contextTokens = null
      this.lastUsage = null
      this.readyDetail = ""
      this.updateTitle()
      this.status.content = "Starting a new chat…"
      this.client.newChat(this.runtimeControls.workspaceScope)
    } catch (error) {
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private sendGatewayCommand(
    content: string,
    lifecycle: ResolvedSlashCommandLifecycle,
    silent = false,
    options: MessageOptions = {},
  ): void {
    if (!this.ready) {
      this.markSubmitUnsent()
      return
    }
    if (this.activeTurn && lifecycle === "agent_turn") {
      this.status.content = "A turn is already running · Ctrl+C to stop"
      return
    }
    let turnId: string
    try {
      turnId = this.client.send(content, options)
    } catch {
      this.markSubmitUnsent(true)
      return
    }
    this.unsentSubmit = false
    this.commandTurns.set(turnId, lifecycle)
    if (silent) this.silentCommandTurns.add(turnId)
    if (/^\/model(?:\s|$)/iu.test(content)) this.modelCommandTurns.add(turnId)
    this.clearComposer()
    this.commandMenu.hide()
    if (!silent && lifecycle !== "stop_active_turn") this.transcript.user(content)
    if (!silent) this.recordPrompt(content)

    if (lifecycle === "agent_turn") {
      this.host.reportTitle(content)
      this.activeTurnId = turnId
      this.finalMessage = ""
      this.turnHadAnswer = false
      this.activeLabel = "Thinking"
      this.currentFileEdits = []
      this.setActive(true)
    } else if (lifecycle === "finalize_active_turn") {
      this.activeTurnId = null
      this.transcript.finishStream(this.turnHadAnswer ? "" : this.finalMessage)
      this.transcript.finishActivity()
      this.finalMessage = ""
      this.turnHadAnswer = false
      this.setActive(false)
      this.status.content = "Resetting chat…"
    } else if (lifecycle === "stop_active_turn") {
      this.activeTurnId = null
      this.setActive(false)
      this.status.content = "Stopping…"
    } else if (!this.activeTurn) {
      this.status.content = `Running ${content.split(/\s+/u, 1)[0]}…`
    }
  }

  private recordPrompt(content: string): void {
    if (!content) return
    if (this.promptHistory.at(-1) !== content) this.promptHistory.push(content)
    if (this.promptHistory.length > 50) this.promptHistory.shift()
    this.historyCursor = this.promptHistory.length
    this.historyDraft = ""
  }

  private restorePromptHistory(messages: HistoryMessage[], prepend = false): void {
    const restored = messages
      .filter((message) => message.role === "user")
      .map((message) => message.content.trim())
      .filter(Boolean)
    const combined = prepend ? [...restored, ...this.promptHistory] : restored
    const compacted = combined.filter((content, index) => content !== combined[index - 1])
    this.promptHistory.splice(0, this.promptHistory.length, ...compacted.slice(-50))
    this.historyCursor = this.promptHistory.length
    this.historyDraft = ""
  }

  private closeSessions(): void {
    this.sessionLoadId += 1
    this.sessionLoading = false
    this.hideSessionMenu()
    this.clearComposer()
    this.syncComposerPlaceholder()
    this.composer.focus()
    if (this.activeTurn) this.renderActiveStatus()
    else if (this.ready) this.status.content = this.readyStatus()
    this.updateMeta()
  }

  private hideSessionMenu(): void {
    this.stopSessionRefresh()
    this.sessionMenu.hide()
  }

  private startSessionRefresh(): void {
    if (this.sessionRefreshTimer) return
    this.sessionRefreshTimer = setInterval(() => {
      if (!this.sessionMenu.visible) {
        this.stopSessionRefresh()
        return
      }
      void this.refreshSessionMenu()
    }, SESSION_REFRESH_INTERVAL_MS)
    ;(this.sessionRefreshTimer as unknown as { unref?: () => void }).unref?.()
  }

  private stopSessionRefresh(): void {
    if (this.sessionRefreshTimer) clearInterval(this.sessionRefreshTimer)
    this.sessionRefreshTimer = null
  }

  private async refreshSessionMenu(): Promise<void> {
    if (this.sessionRefreshPending || !this.sessionMenu.visible || this.quitting) return
    this.sessionRefreshPending = true
    const loadId = this.sessionLoadId
    try {
      const sessions = await fetchSessions(
        this.options.apiUrl,
        this.options.apiToken,
        this.apiReauthenticator,
      )
      if (this.quitting || loadId !== this.sessionLoadId || !this.sessionMenu.visible) return
      this.sessionMenu.replace(
        sessions,
        this.client.activeChatId,
        this.defaultModelPreset,
      )
      this.status.content = sessions.length ? `${sessions.length} sessions` : "No saved sessions"
    } catch {
      // Keep the existing picker usable during a transient refresh failure.
    } finally {
      this.sessionRefreshPending = false
    }
  }

  private async openContext(): Promise<void> {
    this.commandMenu.hide()
    this.hideSessionMenu()
    this.mentionMenu.hide()
    this.skillMenu.hide()
    this.branchMenu.hide()
    this.clearComposer()
    this.status.content = "Reading agent context…"
    try {
      const context = await fetchSessionContext(
        this.options.apiUrl,
        this.options.apiToken,
        this.client.activeChatId,
        this.apiReauthenticator,
      )
      if (!context) {
        this.status.content = "Context unavailable · new session or older gateway"
        return
      }
      this.contextTokens = context.estimatedSessionTokens
      this.lastUsage = context.lastUsage
      this.updateTitle()
      this.contextPanel.show(context)
      this.status.content = "Context snapshot"
      this.updateMeta()
    } catch (error) {
      this.status.content = error instanceof Error ? error.message : String(error)
    }
  }

  private async refreshSessionMetadata(chatId: string): Promise<void> {
    if (!this.options.apiUrl || !this.options.apiToken) return
    const requestId = ++this.sessionMetadataId
    try {
      const sessions = await fetchSessions(
        this.options.apiUrl,
        this.options.apiToken,
        this.apiReauthenticator,
      )
      if (
        requestId !== this.sessionMetadataId
        || chatId !== this.client.activeChatId
      ) return
      const session = sessions.find((candidate) => candidate.chatId === chatId)
      if (!session) return
      this.sessionTitle = sessionLabel(session)
      this.applySessionModel(session)
      this.applySessionScope(session)
      this.updateTitle()
    } catch {
      // Session metadata is decorative; conversation transport stays authoritative.
    }
  }

  private async refreshContextEstimate(chatId: string): Promise<void> {
    try {
      const context = await fetchSessionContext(
        this.options.apiUrl,
        this.options.apiToken,
        chatId,
        this.apiReauthenticator,
      )
      if (!context || chatId !== this.client.activeChatId) return
      this.contextTokens = context.estimatedSessionTokens
      this.lastUsage = context.lastUsage || this.lastUsage
      this.updateTitle()
      if (!this.activeTurn) this.status.content = this.readyStatus()
      this.updateMeta()
    } catch {
      // Keep the last known estimate; it is intentionally informational.
    }
  }

  private openDiff(): void {
    this.commandMenu.hide()
    this.hideSessionMenu()
    this.mentionMenu.hide()
    this.skillMenu.hide()
    this.branchMenu.hide()
    this.contextPanel.hide()
    this.clearComposer()
    this.composer.blur()
    const edits = this.currentFileEdits.length ? this.currentFileEdits : this.lastFileEdits
    this.diffViewer.show(edits)
    this.diffViewer.resize(this.renderer.width)
    this.status.content = edits.length ? "Last turn diff" : "No file changes in the last turn"
    this.updateMeta()
  }

  private async loadOlderHistory(): Promise<void> {
    if (
      this.historyLoadingOlder
      || !this.historyHasMore
      || !this.historyBeforeCursor
      || !this.client.activeChatId
    ) return
    const hydrationId = this.hydrationId
    const chatId = this.client.activeChatId
    this.historyLoadingOlder = true
    this.status.content = "Loading earlier messages…"
    try {
      const history = await fetchHistory(
        this.options.apiUrl,
        this.options.apiToken,
        chatId,
        this.historyBeforeCursor,
        this.apiReauthenticator,
      )
      if (hydrationId !== this.hydrationId || chatId !== this.client.activeChatId) return
      await this.transcript.prependHistory(history.messages)
      this.restorePromptHistory(history.messages, true)
      this.historyBeforeCursor = history.beforeCursor
      this.historyHasMore = history.hasMoreBefore
      this.status.content = history.hasMoreBefore
        ? `${history.messages.length} earlier messages · PageUp for more`
        : "Start of session"
    } catch (error) {
      if (hydrationId !== this.hydrationId) return
      this.status.content = error instanceof Error ? error.message : String(error)
    } finally {
      if (hydrationId === this.hydrationId) this.historyLoadingOlder = false
    }
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

  private quit(detach = false): void {
    if (this.quitting) return
    this.quitting = true
    this.submitGeneration += 1
    this.submitPending = false
    this.stopSessionRefresh()
    this.host.release()
    this.client.close()
    this.renderer.destroy()
    const chatId = this.client.activeChatId || this.options.chatId
    if (detach) this.options.onDetach?.(chatId)
    else if (chatId) this.options.onExit?.(chatId)
  }

  private handleDestroy = (): void => {
    this.quitting = true
    this.clipboardPasteGeneration += 1
    if (this.shimmerTimer) clearInterval(this.shimmerTimer)
    this.stopSessionRefresh()
    this.composerSyntax.destroy()
    this.transcript.destroy()
    this.diffViewer.destroy()
    void this.clipboardImageReader.dispose().catch(() => {})
    this.host.release()
    this.client.close()
  }
}

export type { AppOptions }
