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
  decodeConfigEditorSnapshot,
  fetchConfigEditor,
  fetchHistory,
  fetchGatewayConnection,
  fetchMentionCandidates,
  fetchSessionContext,
  fetchSessions,
  fetchSlashCommands,
  type ApiReauthenticator,
  type ConnectionStatus,
  type FileEditEvent,
  type GatewayApiConnection,
  type HistoryMessage,
  type InboundEvent,
  type MentionCandidate,
  type MessageOptions,
  type RecoveryState,
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
import { ComposerDraft } from "./composer-draft"
import { BranchMenu, branchPoints } from "./branch-menu"
import {
  MentionMenu,
  insertMention,
  mentionOptions,
  mentionQuery,
  type MentionQuery,
} from "./mention-menu"
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
import { createTuiHost, currentGitBranch, type TuiHost } from "./host"
import { ConfigEditor, type ConfigEditorTheme } from "./config-editor"

interface AppOptions {
  wsUrl?: string
  bootstrapUrl?: string
  bootstrapSecret?: string
  apiUrl: string
  apiToken: string
  chatId?: string
  model: string
  modelPreset: string
  workspace: string
  hostWorkspace?: string
  branch?: string
  version: string
  access: string
  theme: "auto" | ThemeMode
  initialView?: "config"
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
  requestMutation?(action: string, payload: Record<string, unknown>): Promise<unknown>
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
const ACTIVE_COMPOSER_PLACEHOLDER = "Steer this turn…"
const SHIMMER_PAUSE = 16
const SHIMMER_BAND = 4
const SHIMMER_INTERVAL_MS = 80
const SESSION_REFRESH_INTERVAL_MS = 1_000
const LOCAL_COMMANDS: TuiCommand[] = [
  {
    command: "/config",
    title: "Configuration",
    description: "Edit every nanobot setting",
    action: "config",
  },
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

function configEditorTheme(palette: Palette): ConfigEditorTheme {
  return {
    text: palette.text,
    muted: palette.muted,
    faint: palette.faint,
    border: palette.border,
    accent: palette.accent,
    success: palette.success,
    error: palette.error,
    selectedBackground: palette.userBackground,
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

function singleLine(value: string, limit = 120): string {
  return value.replace(/\s+/gu, " ").trim().slice(0, limit)
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
  private readonly branchMenu: BranchMenu
  private readonly runtimeControls: RuntimeControls
  private readonly contextPanel: ContextPanel
  private readonly diffViewer: DiffViewer
  private readonly configEditor: ConfigEditor
  private readonly queuePreview: QueuePreview
  private readonly recoveryNotice: RecoveryNotice
  private readonly client: ChatClient
  private readonly shell: BoxRenderable
  private readonly title: BoxRenderable
  private readonly titleText: TextRenderable
  private readonly composerFrame: BoxRenderable
  private readonly composer: TextareaRenderable
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
  private lastProgress = ""
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
  private currentTask = ""
  private currentAction = ""
  private hostBlocked = false
  private recoveryState: RecoveryState | null = null
  private recoveryPending = false
  private hostWorkspace: string
  private hostBranch: string
  private readonly apiReauthenticator: ApiReauthenticator | undefined
  private apiRefreshPromise: Promise<GatewayApiConnection> | null = null
  private initialViewPending: AppOptions["initialView"]
  private rendererStarted = false

  private constructor(
    renderer: CliRenderer,
    private readonly options: AppOptions,
    client?: ChatClient,
    treeSitterClient = getTreeSitterClient(),
    host: TuiHost = createTuiHost({}),
  ) {
    this.renderer = renderer
    this.initialViewPending = options.initialView
    this.defaultModelName = options.model
    this.defaultModelPreset = options.modelPreset
    this.modelName = options.model
    this.modelPreset = options.modelPreset
    this.hostWorkspace = options.hostWorkspace || options.workspace
    this.hostBranch = options.branch || ""
    this.apiReauthenticator = options.bootstrapUrl
      ? (rejectedApiToken) => this.refreshApiConnection(rejectedApiToken)
      : undefined
    this.sessionModelPreset = options.chatId ? undefined : null
    this.backgroundKnown = options.theme !== "auto" || renderer.themeMode !== null
    this.activeThemeMode = this.resolveThemeMode(renderer.themeMode)
    this.palette = this.activeThemeMode === "light" ? LIGHT : DARK
    this.host = host
    this.transcript = new Transcript(
      renderer,
      transcriptTheme(this.palette, this.backgroundKnown),
      treeSitterClient,
      (state) => this.handleTranscriptNavigation(state),
      !host.hosted,
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
            onConnection: (connection) => this.useGatewayConnection(
              connection.apiUrl,
              connection.apiToken,
            ),
            connectionRetryLabel: "Starting local gateway",
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
      onMouseDown: (event) => {
        if (event.button !== 0) return
        if (!this.diffViewer.visible && !this.configEditor.visible) {
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
    this.titleText = new TextRenderable(renderer, {
      id: "nanobot-tui-title-text",
      content: "nanobot",
      height: 1,
      flexShrink: 0,
      truncate: true,
      fg: this.palette.muted,
      selectable: false,
      ...(host.hosted ? {} : {
        onMouseOver: () => { this.titleText.fg = this.palette.accent },
        onMouseOut: () => this.renderTitleColor(),
        onMouseDown: (event) => {
          if (event.button !== 0) return
          event.preventDefault()
          event.stopPropagation()
          this.renderer.clearSelection()
          if (this.sessionLoading || this.sessionMenu.visible) {
            this.closeSessions()
            return
          }
          void this.openSessions()
        },
      }),
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
    this.title.add(this.titleText)
    if (!host.hosted) {
      this.title.add(this.runtimeControls.modelText)
      this.title.add(this.runtimeControls.accessText)
      this.title.add(this.runtimeControls.contextText)
    }
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
      onContentChange: () => {
        this.draft.prune(this.composer.plainText)
        this.runtimeControls.hide()
        if (this.contextPanel.visible && this.composer.plainText) this.contextPanel.hide()
        this.syncComposerPlaceholder()
        if (this.sessionMenu.visible) this.syncSessionMenu()
        else if (this.branchMenu.visible) this.syncBranchMenu()
        else this.syncComposerMenus()
        this.resizeComposer()
      },
      // IMEs may commit their final composed glyph after Enter. Matching the
      // OpenCode/OpenTUI integration, defer twice before reading plainText.
      onSubmit: () => this.deferSubmit(),
      onPaste: (event) => this.handlePaste(event),
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
    this.configEditor = new ConfigEditor(
      renderer,
      configEditorTheme(this.palette),
      {
        load: () => fetchConfigEditor(
          this.options.apiUrl,
          this.options.apiToken,
          this.apiReauthenticator,
        ),
        save: async (revision, config) => {
          if (!this.client.requestMutation) {
            throw new Error("configuration updates require a current gateway")
          }
          return decodeConfigEditorSnapshot(await this.client.requestMutation(
            "settings.config_editor.update",
            { revision, config },
          ))
        },
        onVisibilityChange: (visible) => {
          if (!visible) {
            this.composer.focus()
            if (!this.activeTurn && this.ready) this.status.content = this.readyStatus()
          }
        },
        onStatus: (message) => { this.status.content = message },
      },
    )

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
    this.shell.add(this.branchMenu.root)
    this.shell.add(this.contextPanel.root)
    this.shell.add(this.runtimeControls.menuRoot)
    if (!host.hosted) this.shell.add(this.title)
    this.shell.add(this.queuePreview.root)
    this.shell.add(this.recoveryNotice.root)
    this.shell.add(this.composerFrame)
    this.shell.add(statusRow)
    this.shell.add(this.diffViewer.root)
    this.shell.add(this.configEditor.root)
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
    this.syncHostMetadata()
  }

  static async create(options: AppOptions): Promise<NanobotTui> {
    const host = createTuiHost()
    const renderer = await createCliRenderer({
      targetFps: 30,
      exitOnCtrlC: false,
      useMouse: true,
      screenMode: host.hosted ? "main-screen" : "alternate-screen",
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
  ): NanobotTui {
    return new NanobotTui(renderer, options, client, treeSitterClient, host)
  }

  async start(): Promise<void> {
    // Network setup and small menu payloads do not depend on terminal colors.
    // Start them while OSC theme detection is in flight instead of serializing
    // up to one second of otherwise independent startup work.
    this.host.reportState("unknown", "Connecting")
    this.client.connect()
    void this.loadCommands()
    void this.loadMentions()
    this.runtimeControls.preload()
    this.renderer.start()
    this.rendererStarted = true
    this.openInitialViewIfReady()
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
    const content = this.draft.expand(visibleContent).trim()
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
    if (!visibleContent) return
    if (["exit", "quit", "/quit", ":q"].includes(visibleContent.toLowerCase())) {
      this.quit()
      return
    }
    if (["/continue", "/dismiss"].includes(visibleContent.toLowerCase())) {
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
    if (command?.source === "tui") {
      if (command.command.action === "sessions") void this.openSessions()
      else if (command.command.action === "config") void this.openConfig()
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
      this.status.content = "Preparing chat…"
      return
    }
    const prompt = { content, options: mentionOptions(content, this.availableMentions()) }
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
    } catch (error) {
      this.status.content = error instanceof Error ? error.message : String(error)
      return false
    }
    this.clearComposer()
    this.commandMenu.hide()
    this.mentionMenu.hide()
    this.recordPrompt(prompt.content)
    this.transcript.user(prompt.content, turnId)
    this.hostBlocked = false
    this.setCurrentTask(prompt.content)
    if (steering) {
      this.status.content = `Steering current turn${this.promptQueue.length ? ` · ${this.promptQueue.length} queued` : ""}`
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
    this.lastProgress = ""
    this.activeLabel = "Thinking"
    this.currentFileEdits = []
    this.setCurrentAction("Thinking")
    this.setActive(true, startedAt)
    this.reportHostWorking()
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
      this.host.reportSession(event.chat_id)
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
        const attachments = event.media_urls?.map((media) => media.name).filter(Boolean) || []
        const content = [
          event.text,
          attachments.length ? `Attachments: ${attachments.join(", ")}` : "",
        ].filter(Boolean).join("\n")
        if (this.transcript.user(content, event.turn_id)) this.recordPrompt(event.text)
        this.hostBlocked = false
        this.setCurrentTask(event.text)
        this.reconcileTurnOwnership(event)
        if (this.activeTurn) this.reportHostWorking()
        return
      }
      case "delta":
        this.setActive(true)
        this.activeLabel = "Writing"
        if (!this.currentAction) this.setCurrentAction("Writing")
        this.reportHostWorking()
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
          this.lastProgress = this.transcript.progress(event.text, event.tool_events)
          if (this.lastProgress) this.setCurrentAction(this.lastProgress)
          else if (!this.currentAction) this.setCurrentAction(this.activeLabel)
          this.setActive(true)
          this.reportHostWorking()
        } else {
          this.finalMessage = event.text
        }
        return
      case "file_edit":
        this.activeLabel = "Editing"
        this.currentFileEdits = mergeFileEdits(this.currentFileEdits, event.edits)
        if (this.diffViewer.visible) this.diffViewer.update(this.currentFileEdits)
        this.lastProgress = this.transcript.fileEdits(event.edits)
        this.setCurrentAction(this.lastProgress || "Editing")
        this.setActive(true)
        this.reportHostWorking()
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
        this.applyHostGoalState(event.goal_state)
        this.updateTitle()
        this.setActive(false)
        // A synthetic/rehydrated turn may already be idle, in which case
        // setActive(false) intentionally does not repaint the footer.
        this.updateMeta()
        this.readyDetail = typeof event.latency_ms === "number"
          ? `${(event.latency_ms / 1000).toFixed(1)}s`
          : ""
        this.status.content = this.readyStatus()
        this.reportHostResting()
        if (this.contextTokens !== null) void this.refreshContextEstimate(event.chat_id)
        this.sendNextFollowUp()
        return
      case "goal_status":
        if (event.turn_id && this.activeTurnId && event.turn_id !== this.activeTurnId) return
        if (event.status === "running") {
          if (event.turn_id) this.activeTurnId = event.turn_id
          this.activeLabel = "Working"
          if (!this.currentAction) this.setCurrentAction("Working")
          this.setActive(true, typeof event.started_at === "number" ? event.started_at * 1000 : undefined)
          this.reportHostWorking()
        } else {
          this.setActive(false)
          this.reportHostResting()
        }
        return
      case "goal_state":
        this.applyHostGoalState(event.goal_state)
        if (!this.activeTurn) this.reportHostResting()
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
        this.setCurrentAction(event.reason || event.detail || "Error")
        this.reportHostResting()
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
        if (lastUser) this.setCurrentTask(lastUser.content)
        const lastActivity = reversedHistory.find((message) => message.role === "activity")
        if (lastActivity) {
          this.setCurrentAction(lastActivity.fileEdits?.length ? "Edited" : lastActivity.content)
        }
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
        this.reportHostResting()
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
      this.hostBlocked = false
      this.activeLabel = "Continuing"
      this.setCurrentAction("Continuing interrupted task")
      this.setActive(true)
      this.reportHostWorking()
      return
    }
    if (state.status === "awaiting_user" || state.status === "failed") {
      this.activeTurnId = null
      this.setActive(false)
      this.hostBlocked = true
      this.recoveryNotice.show(state)
      const detail = state.reason || (state.status === "failed"
        ? "Recovery failed"
        : "Task interrupted")
      this.setCurrentAction(detail)
      this.status.content = state.can_continue === false
        ? "Interrupted · dismiss to start a new message"
        : "Interrupted · continue or dismiss"
      this.host.reportState("blocked", detail)
      this.composer.focus()
      return
    }
    this.clearRecoveryState()
    this.activeTurnId = null
    this.hostBlocked = false
    this.setActive(false)
    if (this.ready) this.status.content = this.readyStatus()
    this.reportHostResting()
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
      this.host.reportState("blocked", state.reason || "Task interrupted")
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
    this.openInitialViewIfReady()
    void this.loadCommands()
    void this.loadMentions()
  }

  private openInitialViewIfReady(): void {
    if (
      !this.rendererStarted
      || this.initialViewPending !== "config"
      || !this.options.apiUrl
      || !this.options.apiToken
    ) return
    this.initialViewPending = undefined
    void this.openConfig()
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

  private handleStatus(status: ConnectionStatus, detail?: string): void {
    if (status === "connected") {
      this.ready = false
      this.host.reportState("unknown", "Connecting")
      this.status.content = "Connected · preparing chat…"
      return
    }
    if (status === "connecting") {
      this.ready = false
      const label = detail === "Starting local gateway"
        ? detail
        : detail ? "Reconnecting" : "Connecting"
      this.host.reportState("unknown", label)
      if (detail) this.setActive(false)
      this.status.content = `${label}…`
      return
    }
    if (status === "error") {
      this.setActive(false)
      this.host.reportState("unknown", detail || "Connection error")
      this.status.content = detail || "Connection error"
      return
    }
    if (!this.quitting) {
      this.setActive(false)
      this.host.reportState("unknown", "Disconnected")
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
    this.lastProgress = ""
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
    const content = this.draft.expand(visibleContent).trim()
    if (!content) return
    this.promptQueue.enqueue({
      content,
      options: mentionOptions(content, this.availableMentions()),
    })
    this.clearComposer()
    this.commandMenu.hide()
    this.mentionMenu.hide()
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
    if (this.configEditor.visible) {
      if (this.configEditor.handleKey(key)) key.preventDefault()
      return
    }
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
    this.branchMenu.setTheme(commandMenuTheme(this.palette))
    this.runtimeControls.setTheme(runtimeControlsTheme(this.palette))
    this.contextPanel.setTheme(contextPanelTheme(this.palette))
    this.diffViewer.setTheme(diffViewerTheme(this.palette, this.backgroundKnown))
    this.configEditor.setTheme(configEditorTheme(this.palette))
    this.queuePreview.setTheme(queuePreviewTheme(this.palette))
    this.recoveryNotice.setTheme(recoveryNoticeTheme(this.palette))
    this.updateComposerAppearance()
    this.composer.textColor = this.palette.text
    this.composer.focusedTextColor = this.palette.text
    this.composer.cursorColor = this.palette.accent
    this.renderTitleColor()
    this.status.fg = this.palette.muted
    this.meta.fg = this.palette.faint
    this.updateMeta()
  }

  private handleResize = (): void => {
    this.resizeComposer()
    this.contextPanel.resize(this.renderer.height)
    this.diffViewer.resize(this.renderer.width)
    this.configEditor.resize(this.renderer.width, this.renderer.height)
    if (!this.host.hosted) this.title.visible = this.renderer.height >= 14
    this.runtimeControls.resize(this.renderer.width)
    this.updateTitle()
    this.updateMeta()
  }

  private updateMeta(): void {
    const mode: FooterMode = this.runtimeControls.visible ? "runtime"
      : this.mentionMenu.visible ? "mention"
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
    if (this.host.hosted) {
      this.syncHostMetadata()
      return
    }
    const identity = this.sessionTitle.trim() || "nanobot"
    this.titleText.maxWidth = Math.max(8, Math.floor(this.renderer.width * 0.38))
    this.titleText.content = identity
    const context = this.contextTokens === null
      ? ""
      : `  ·  ~${formatTokenCount(this.contextTokens)}${this.contextWindowTokens
        ? `/${formatTokenCount(this.contextWindowTokens)}`
        : ""} ctx`
    this.runtimeControls.updateModel(this.modelName, this.modelPreset)
    this.runtimeControls.updateContext(context)
    this.syncHostMetadata()
  }

  private renderTitleColor(): void {
    this.titleText.fg = !this.host.hosted && (this.sessionLoading || this.sessionMenu.visible)
      ? this.palette.accent
      : this.palette.muted
  }

  private setCurrentTask(task: string): void {
    const next = singleLine(task)
    if (!next || next === this.currentTask) return
    this.currentTask = next
    this.updateTitle()
  }

  private setCurrentAction(action: string): void {
    const next = singleLine(action.replace(/^\s*[·›✓×]\s*/u, ""), 80)
    if (!next || next === this.currentAction) return
    this.currentAction = next
    this.syncHostMetadata()
  }

  private clearHostContext(): void {
    this.currentTask = ""
    this.currentAction = ""
    this.hostBlocked = false
    this.updateTitle()
  }

  private syncHostMetadata(): void {
    const model = [this.modelPreset, this.modelName].filter(Boolean).join(" · ")
    this.host.reportMetadata({
      model,
      branch: this.hostBranch,
      workspace: this.hostWorkspace,
      task: this.currentTask,
      action: this.currentAction,
    })
  }

  private applyHostGoalState(state: Record<string, unknown> | undefined): void {
    if (!state) return
    this.hostBlocked = state.status === "blocked"
    if (!this.hostBlocked) return
    const summary = typeof state.ui_summary === "string" ? state.ui_summary : ""
    const recap = typeof state.recap === "string" ? state.recap : ""
    const objective = typeof state.objective === "string" ? state.objective : ""
    this.setCurrentAction(summary || recap || objective || "Needs input")
    this.host.reportState("blocked", summary || recap || objective || this.currentTask)
  }

  private reportHostResting(): void {
    this.host.reportState(
      this.hostBlocked ? "blocked" : "idle",
      this.hostBlocked ? this.currentAction || this.currentTask : this.currentAction,
    )
  }

  private reportHostWorking(): void {
    if (!this.hostBlocked) this.host.reportState("working", this.currentTask)
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
    const placeholder = this.composer.plainText
      ? null
      : this.sessionMenu.visible
        ? "Search sessions"
        : this.branchMenu.visible
          ? "Search branch points"
          : this.activeTurn ? ACTIVE_COMPOSER_PLACEHOLDER : COMPOSER_PLACEHOLDER
    if (this.composer.placeholder !== placeholder) this.composer.placeholder = placeholder
  }

  private syncCommandMenu(): void {
    const limit = this.renderer.height >= 20 ? 8 : 3
    this.commandMenu.update(this.composer.plainText, limit)
    this.updateMeta()
  }

  private syncComposerMenus(): void {
    this.activeMentionQuery = mentionQuery(this.composer.plainText, this.composer.cursorOffset)
    const candidates = this.availableMentions()
    if (this.activeMentionQuery && candidates.length) {
      this.commandMenu.hide()
      const limit = this.renderer.height >= 20 ? 7 : 4
      if (this.mentionMenu.visible) this.mentionMenu.update(this.activeMentionQuery.query, limit)
      else this.mentionMenu.show(candidates, this.activeMentionQuery.query, limit)
      this.updateMeta()
      return
    }
    this.mentionMenu.hide()
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
    this.composer.cursorOffset = inserted.cursor
    this.mentionMenu.hide()
    this.activeMentionQuery = null
    this.syncComposerPlaceholder()
    this.updateMeta()
  }

  private setComposer(content: string): void {
    this.draft.clear()
    this.composer.setText(content)
    this.composer.cursorOffset = content.length
  }

  private clearComposer(): void {
    this.draft.clear()
    this.composer.setText("")
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
    if (this.quitting) return
    const commands = new Map(discovered.map((command) => [command.command, command]))
    this.commandMenu.setCommands([...commands.values()], LOCAL_COMMANDS)
    this.syncCommandMenu()
  }

  private closeTransientMenus(): void {
    this.commandMenu.hide()
    this.hideSessionMenu()
    this.mentionMenu.hide()
    this.branchMenu.hide()
    this.contextPanel.hide()
    this.activeMentionQuery = null
  }

  private dismissRuntimeControls(): void {
    if (this.runtimeControls.visible) this.runtimeControls.hide()
  }

  private applyWorkspaceScope(scope: WorkspaceScopePayload): void {
    if (scope.project_path) {
      this.hostWorkspace = scope.project_path
      this.hostBranch = currentGitBranch(scope.project_path)
      this.syncHostMetadata()
    }
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
      if (this.quitting) return
      if (this.activeMentionQuery) this.syncComposerMenus()
    } catch {
      // Mentions are additive; plain text input remains fully functional.
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
      this.clearHostContext()
      this.setCurrentTask(preview)
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
    this.branchMenu.hide()
    this.contextPanel.hide()
    this.clearComposer()
    this.sessionLoading = true
    this.renderTitleColor()
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
      this.renderTitleColor()
      this.sessionMenu.update(this.composer.plainText, limit)
      this.syncComposerPlaceholder()
      this.updateMeta()
      this.status.content = sessions.length ? `${sessions.length} sessions` : "No saved sessions"
    } catch (error) {
      if (loadId !== this.sessionLoadId) return
      this.sessionLoading = false
      this.renderTitleColor()
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
      this.clearHostContext()
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
    this.branchMenu.hide()
    this.contextPanel.hide()
    this.clearComposer()
    try {
      this.ready = false
      this.clearRecoveryState()
      this.clearPromptQueue()
      this.sessionMetadataId += 1
      this.clearHostContext()
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
      this.status.content = "Preparing chat…"
      return
    }
    if (this.activeTurn && lifecycle === "agent_turn") {
      this.status.content = "A turn is already running · Ctrl+C to stop"
      return
    }
    let turnId: string
    try {
      turnId = this.client.send(content, options)
    } catch (error) {
      this.status.content = error instanceof Error ? error.message : String(error)
      return
    }
    this.commandTurns.set(turnId, lifecycle)
    if (silent) this.silentCommandTurns.add(turnId)
    if (/^\/model(?:\s|$)/iu.test(content)) this.modelCommandTurns.add(turnId)
    this.clearComposer()
    this.commandMenu.hide()
    if (!silent && lifecycle !== "stop_active_turn") this.transcript.user(content)
    if (!silent) this.recordPrompt(content)

    if (lifecycle === "agent_turn") {
      this.hostBlocked = false
      this.setCurrentTask(content)
      this.activeTurnId = turnId
      this.finalMessage = ""
      this.turnHadAnswer = false
      this.lastProgress = ""
      this.activeLabel = "Thinking"
      this.currentFileEdits = []
      this.setCurrentAction("Thinking")
      this.setActive(true)
      this.reportHostWorking()
    } else if (lifecycle === "finalize_active_turn") {
      this.activeTurnId = null
      this.transcript.finishStream(this.turnHadAnswer ? "" : this.finalMessage)
      this.transcript.finishActivity()
      this.finalMessage = ""
      this.turnHadAnswer = false
      this.setActive(false)
      this.reportHostResting()
      this.status.content = "Resetting chat…"
    } else if (lifecycle === "stop_active_turn") {
      this.activeTurnId = null
      this.setActive(false)
      this.reportHostResting()
      this.status.content = "Stopping…"
    } else if (!this.activeTurn) {
      this.status.content = `Running ${content.split(/\s+/u, 1)[0]}…`
    }
  }

  private recordPrompt(content: string): void {
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
    this.renderTitleColor()
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

  private async openConfig(): Promise<void> {
    if (this.activeTurn) {
      this.status.content = "Wait for the current turn or press Ctrl+C"
      return
    }
    this.closeTransientMenus()
    this.dismissRuntimeControls()
    this.clearComposer()
    this.composer.blur()
    await this.configEditor.show()
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
    if (this.shimmerTimer) clearInterval(this.shimmerTimer)
    this.stopSessionRefresh()
    this.transcript.destroy()
    this.diffViewer.destroy()
    this.configEditor.destroy()
    this.host.release()
    this.client.close()
  }
}

export type { AppOptions }
