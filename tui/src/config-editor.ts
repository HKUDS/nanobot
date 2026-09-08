import {
  BoxRenderable,
  RGBA,
  ScrollBoxRenderable,
  TextareaRenderable,
  TextAttributes,
  TextRenderable,
  decodePasteBytes,
  stripAnsiSequences,
  type CliRenderer,
  type KeyEvent,
  type PasteEvent,
} from "@opentui/core"

import {
  buildConfigFields,
  cloneConfig,
  displayConfigValue,
  editorInitialValue,
  parseConfigValue,
  escapePointer,
  readConfigValue,
  writeConfigValue,
  type ConfigField,
} from "./config-editor-model"
import { hideScrollbars } from "./scrollbox"
import type { ConfigEditorSection, ConfigEditorSnapshot } from "./protocol"
import {
  activeSetupModel, decodeSetupAuthorization, decodeSetupModels, decodeSetupProviders,
  record, setupDraft, newSetupPreset, setupProviderStatus,
  type SetupAuthorization, type SetupModel, type SetupProvider, type SetupPreset,
} from "./setup-model"

export interface ConfigEditorTheme {
  text: string
  muted: string
  faint: string
  border: string
  accent: string
  success: string
  error: string
  selectedBackground: string
}

export interface ConfigEditorOptions {
  load: () => Promise<ConfigEditorSnapshot>
  save: (revision: string, config: Record<string, unknown>) => Promise<ConfigEditorSnapshot>
  onVisibilityChange?: (visible: boolean) => void
  onStatus?: (message: string) => void
  request?: (action: string, payload: Record<string, unknown>) => Promise<unknown>
  read?: (path: string) => Promise<unknown>
  openUrl?: (url: string) => Promise<void>
  copyText?: (text: string) => Promise<void>
  listenForCallback?: (url: string, complete: (url: string) => void) => () => void
  startChat?: () => void
}

type EditorPage = "home" | "advanced-home" | "section" | "search" | "setup"
type EditPurpose = "field" | "search"
type ConfigRow =
  | { kind: "field"; field: ConfigField }
  | { kind: "section"; section: ConfigEditorSection; count: number }
  | { kind: "advanced"; count: number }
  | { kind: "back" }
  | { kind: "action"; label: string; description: string; run: () => void }

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function searchText(field: ConfigField): string {
  return `${field.label} ${field.breadcrumb} ${field.path}`.toLocaleLowerCase()
}

/** Full-screen schema-driven configuration editor shared by agent and onboarding. */
export class ConfigEditor {
  readonly root: BoxRenderable
  private readonly header: TextRenderable
  private readonly intro: TextRenderable
  private readonly detail: TextRenderable
  private readonly scroll: ScrollBoxRenderable
  private readonly editorFrame: BoxRenderable
  private readonly editorLabel: TextRenderable
  private readonly editorInput: TextareaRenderable
  private readonly secretInput: TextRenderable
  private readonly feedback: TextRenderable
  private readonly footer: TextRenderable
  private snapshot: ConfigEditorSnapshot | null = null
  private draft: Record<string, unknown> = {}
  private fields: ConfigField[] = []
  private rows: ConfigRow[] = []
  private selected = 0
  private page: EditorPage = "home"
  private sectionId = ""
  private advanced = false
  private query = ""
  private editPurpose: EditPurpose | null = null
  private editingField: ConfigField | null = null
  private secretValue = ""
  private dirty = new Set<string>()
  private loading = false
  private waitingForGateway = false
  private onboarding = false
  private saving = false
  private destroyed = false
  private discardArmed = false
  private terminalWidth = 80
  private setupStep: "provider" | "credentials" | "model" | "review" | "done" = "provider"
  private providers: SetupProvider[] = []
  private provider: SetupProvider | null = null
  private models: SetupModel[] = []
  private preset: SetupPreset | null = null
  private presetName = ""
  private existingPresetName: string | null = null
  private makeDefault = true
  private generationOptions = false
  private authorization: SetupAuthorization | null = null
  private inputAction: ((value: string) => void) | null = null
  private generation = 0
  private modelQuery = ""
  private providerQuery = ""
  private providerGroup: "account" | "api" | "local" = "account"
  private listOffset = 0
  private readonly filterInput: TextareaRenderable
  private signInTimer: ReturnType<typeof setTimeout> | null = null
  private signInBusy = false
  private signInHelp = false
  private testedRevision = ""
  private tested = false
  private resolvedProvider = ""
  private stopCallback: (() => void) | null = null
  private pendingCallback: { auth: SetupAuthorization; response: string } | null = null
  private connectionOptions = false
  private authorizationSubmitted = false

  constructor(
    private readonly renderer: CliRenderer,
    private theme: ConfigEditorTheme,
    private readonly options: ConfigEditorOptions,
  ) {
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-config-editor",
      position: "absolute",
      top: 0,
      left: 0,
      width: "100%",
      height: "100%",
      zIndex: 110,
      flexDirection: "column",
      padding: 1,
      backgroundColor: RGBA.defaultBackground(),
      visible: false,
    })
    this.header = new TextRenderable(renderer, {
      id: "nanobot-tui-config-header",
      content: "Configuration",
      width: "100%",
      height: 1,
      flexShrink: 0,
      fg: theme.text,
      attributes: TextAttributes.BOLD,
      selectable: false,
    })
    this.intro = new TextRenderable(renderer, {
      id: "nanobot-tui-config-intro",
      content: "Set up what nanobot needs first. Every other setting remains available below.",
      width: "100%",
      height: 2,
      flexShrink: 0,
      fg: theme.muted,
      wrapMode: "word",
      selectable: false,
    })
    this.detail = new TextRenderable(renderer, {
      id: "nanobot-tui-config-detail",
      content: "",
      width: "100%",
      height: 2,
      flexShrink: 0,
      fg: theme.faint,
      wrapMode: "word",
      selectable: false,
    })
    this.scroll = new ScrollBoxRenderable(renderer, {
      id: "nanobot-tui-config-scroll",
      width: "100%",
      minHeight: 0,
      flexGrow: 1,
      scrollX: false,
      scrollY: true,
      viewportCulling: true,
      contentOptions: { flexDirection: "column", paddingTop: 1, paddingBottom: 1 },
      verticalScrollbarOptions: { visible: false },
      horizontalScrollbarOptions: { visible: false },
    })
    hideScrollbars(this.scroll)
    this.filterInput = new TextareaRenderable(renderer, {
      id: "nanobot-tui-setup-filter", width: "100%", height: 1, flexShrink: 0,
      visible: false, placeholder: "Type to search…", textColor: theme.text,
      focusedTextColor: theme.text, backgroundColor: RGBA.defaultBackground(),
      focusedBackgroundColor: RGBA.defaultBackground(),
      onContentChange: () => {
        if (this.setupStep === "provider") this.providerQuery = this.filterInput.plainText
        else this.modelQuery = this.filterInput.plainText
        this.listOffset = 0
        this.selected = 0
        this.rebuildRows()
      },
    })
    this.editorFrame = new BoxRenderable(renderer, {
      id: "nanobot-tui-config-input-frame",
      width: "100%",
      minHeight: 3,
      maxHeight: 8,
      flexShrink: 0,
      flexDirection: "column",
      border: ["left"],
      borderColor: theme.accent,
      paddingLeft: 1,
      paddingRight: 1,
      visible: false,
    })
    this.editorLabel = new TextRenderable(renderer, {
      id: "nanobot-tui-config-input-label",
      content: "",
      width: "100%",
      height: 1,
      flexShrink: 0,
      fg: theme.muted,
      truncate: true,
      selectable: false,
    })
    this.editorInput = new TextareaRenderable(renderer, {
      id: "nanobot-tui-config-input",
      width: "100%",
      minHeight: 1,
      maxHeight: 6,
      flexGrow: 1,
      wrapMode: "word",
      textColor: theme.text,
      focusedTextColor: theme.text,
      backgroundColor: RGBA.defaultBackground(),
      focusedBackgroundColor: RGBA.defaultBackground(),
      cursorColor: theme.accent,
      cursorStyle: { style: "line", blinking: false },
      keyBindings: [
        { name: "return", shift: true, action: "newline" },
        { name: "return", ctrl: true, action: "submit" },
        { name: "return", action: "submit" },
      ],
      onSubmit: () => this.commitInput(),
    })
    this.secretInput = new TextRenderable(renderer, {
      id: "nanobot-tui-config-secret-input",
      content: "",
      width: "100%",
      height: 1,
      flexGrow: 1,
      fg: theme.text,
      selectable: false,
      visible: false,
    })
    this.feedback = new TextRenderable(renderer, {
      id: "nanobot-tui-config-feedback",
      content: "",
      width: "100%",
      minHeight: 1,
      maxHeight: 2,
      flexShrink: 0,
      fg: theme.muted,
      wrapMode: "word",
      selectable: false,
    })
    this.footer = new TextRenderable(renderer, {
      id: "nanobot-tui-config-footer",
      content: "↑/↓ move · enter edit · / search · ctrl+s save · esc close",
      width: "100%",
      height: 1,
      flexShrink: 0,
      fg: theme.muted,
      truncate: true,
      selectable: false,
    })
    this.editorFrame.add(this.editorLabel)
    this.editorFrame.add(this.editorInput)
    this.editorFrame.add(this.secretInput)
    this.root.add(this.header)
    this.root.add(this.intro)
    this.root.add(this.detail)
    this.root.add(this.filterInput)
    this.root.add(this.scroll)
    this.root.add(this.editorFrame)
    this.root.add(this.feedback)
    this.root.add(this.footer)
    this.renderer.keyInput.on("paste", this.handlePaste)
  }

  get visible(): boolean {
    return this.root.visible
  }

  showWaitingForGateway(): void {
    this.onboarding = true
    this.waitingForGateway = true
    this.root.visible = true
    this.options.onVisibilityChange?.(true)
    this.feedback.content = "Connecting to gateway…"
    this.rebuildRows()
    this.footer.content = "Connecting… · Ctrl+C exit"
  }

  updateConnectionStatus(message: string): void {
    if (this.waitingForGateway && !this.destroyed) this.feedback.content = message
  }

  async show(quickStart = false): Promise<void> {
    if (this.loading) return
    this.waitingForGateway = false
    this.onboarding = quickStart
    this.footer.content = "↑/↓ move · Enter select · / search · Esc back · Ctrl+C exit"
    this.root.visible = true
    this.options.onVisibilityChange?.(true)
    this.loading = true
    this.feedback.fg = this.theme.muted
    this.feedback.content = "Loading configuration…"
    this.renderRows()
    try {
      const snapshot = await this.options.load()
      if (!this.destroyed) {
        this.useSnapshot(snapshot)
        this.feedback.content = ""
        if (this.options.read) {
          try {
            const settings = await this.options.read("/api/settings")
            this.providers = decodeSetupProviders(settings)
            this.resolvedProvider = record(settings) && record(settings.agent) && typeof settings.agent.resolved_provider === "string"
              ? settings.agent.resolved_provider : ""
          }
          catch { this.feedback.content = "Provider status unavailable. Choose a connection to retry, or open Advanced settings." }
        }
        if (quickStart) this.options.onStatus?.("Quick start")
        this.rebuildRows()
      }
    } catch (error) {
      if (!this.destroyed) {
        this.feedback.fg = this.theme.error
        this.feedback.content = errorMessage(error)
      }
    } finally {
      this.loading = false
      if (!this.destroyed) this.renderRows()
    }
  }

  hide(force = false): boolean {
    if (!this.visible) return true
    if (this.saving && !force) return false
    if (!force && this.dirty.size && !this.discardArmed) {
      this.discardArmed = true
      this.feedback.fg = this.theme.error
      this.feedback.content = "Unsaved changes. Press Esc again to discard them, or Ctrl+S to save."
      return false
    }
    this.cancelInput()
    this.root.visible = false
    this.generation += 1
    this.cancelSignIn()
    this.discardArmed = false
    this.options.onVisibilityChange?.(false)
    return true
  }

  handleKey(key: KeyEvent): boolean {
    if (!this.visible) return false
    if (this.saving || this.loading || this.waitingForGateway) return true
    if (this.editPurpose) return this.handleEditKey(key)
    if (key.name !== "escape") this.discardArmed = false
    if (key.ctrl && key.name === "s") {
      if (this.page === "setup") {
        if (this.setupStep === "review") void this.finishSetup()
      } else void this.save()
      return true
    }
    if (key.name === "escape") {
      if (this.saving) return true
      if (this.page === "setup" && this.setupStep !== "provider" && this.setupStep !== "done") {
        if (this.setupStep === "review" && this.preset && !this.discardArmed) {
          this.discardArmed = true
          this.feedback.content = "Press Esc again to discard the preset form, or Ctrl+S to save it."
          return true
        }
        if (this.setupStep === "review") this.preset = null
        this.setupStep = this.setupStep === "model" ? "review" : "provider"
        this.cancelSignIn()
        this.selected = 0
        this.rebuildRows()
        return true
      }
      if (this.page !== "home") this.goHome()
      else this.hide()
      return true
    }
    if (!key.ctrl && !key.meta && key.name === "/" && this.page !== "setup") {
      this.beginSearch()
      return true
    }
    if (["up", "down", "pageup", "pagedown", "home", "end"].includes(key.name)) {
      const page = Math.max(4, Math.floor(this.scroll.height * 0.7))
      const destination = key.name === "home" ? 0
        : key.name === "end" ? this.rows.length - 1
        : this.selected + (key.name === "up" ? -1
          : key.name === "down" ? 1
            : key.name === "pageup" ? -page : page)
      this.select(destination)
      return true
    }
    if (key.name === "delete") {
      if (this.filterInput.visible) return false
      const field = this.currentField()
      if (field?.secret && field.configured) this.clearSecret(field)
      return true
    }
    if (["left", "right"].includes(key.name)) {
      if (this.filterInput.visible) return false
      const field = this.currentField()
      if (field?.enumValues.length) this.cycle(field, key.name === "left" ? -1 : 1)
      else if (field?.type === "boolean") this.toggle(field)
      return true
    }
    if (key.name === "return" || key.name === "space") {
      if (key.name === "space" && this.filterInput.visible) return false
      this.activate()
      return true
    }
    return !this.filterInput.visible
  }

  resize(width: number, height: number): void {
    this.terminalWidth = width
    this.root.paddingLeft = width >= 96 ? 3 : 1
    this.root.paddingRight = width >= 96 ? 3 : 1
    this.intro.visible = height >= 13
    this.intro.height = height >= 18 ? 2 : 1
    this.detail.height = height >= 18 ? 2 : 1
    this.footer.content = width >= 72
      ? "↑/↓ move · enter edit · / search · ctrl+s save · esc back/close"
      : "↑/↓ · enter · / search · ctrl+s · esc"
    this.renderRows()
  }

  setTheme(theme: ConfigEditorTheme): void {
    this.theme = theme
    this.header.fg = theme.text
    this.intro.fg = theme.muted
    this.detail.fg = theme.faint
    this.editorFrame.borderColor = theme.accent
    this.editorLabel.fg = theme.muted
    this.editorInput.textColor = theme.text
    this.editorInput.focusedTextColor = theme.text
    this.editorInput.cursorColor = theme.accent
    this.secretInput.fg = theme.text
    this.feedback.fg = theme.muted
    this.footer.fg = theme.muted
    this.renderRows()
  }

  destroy(): void {
    if (this.destroyed) return
    this.destroyed = true
    this.cancelSignIn()
    this.generation += 1
    this.renderer.keyInput.off("paste", this.handlePaste)
  }

  private useSnapshot(snapshot: ConfigEditorSnapshot): void {
    this.preset = null
    this.snapshot = snapshot
    this.draft = cloneConfig(snapshot.config)
    this.dirty.clear()
    this.page = "home"
    this.sectionId = ""
    this.advanced = false
    this.query = ""
    this.selected = 0
    this.refreshFields()
  }

  private refreshFields(): void {
    if (!this.snapshot) {
      this.fields = []
      this.rows = []
      return
    }
    this.fields = buildConfigFields({ ...this.snapshot, config: this.draft })
    this.rebuildRows()
  }

  private rebuildRows(): void {
    if (!this.snapshot && this.page !== "home") {
      this.rows = []
      return
    }
    if (this.page === "home") {
      const connected = this.activeProvider()
      this.rows = [
        ...(connected ? [
          this.action("Continue chatting", "Use your current model. A reply confirms that the connection works.", () => this.hide()),
          this.action("Configure preset", "Choose another model using your saved connection.", () => {
            this.provider = connected
            this.page = "setup"
            this.beginPreset()
          }),
        ] : []),
        this.action("Sign in with an account", "Quick start · Use your existing subscription in a browser. No API key needed.", () => { void this.startSetup("account") }),
        this.action("Use an API key", "Quick start · Connect a hosted API or cloud account using its developer credentials.", () => { void this.startSetup("api") }),
        this.action("Connect a local model", "Quick start · Connect a running local model server, such as Ollama.", () => { void this.startSetup("local") }),
        this.action("Advanced settings", "Configure channels, tools, workspace, and other optional settings.", () => {
          this.page = "advanced-home"
          this.selected = 0
          this.rebuildRows()
        }),
      ]
    } else if (this.page === "advanced-home") {
      this.rows = [{ kind: "back" },
        ...this.snapshot!.presentation.sections.map((section): ConfigRow => ({
          kind: "section",
          section,
          count: this.fields.filter((field) => field.sectionId === section.id).length,
        })),
      ]
    } else if (this.page === "setup") {
      this.rows = this.setupRows()
    } else if (this.page === "section") {
      const fields = this.fields.filter((field) => field.sectionId === this.sectionId)
      const basic = fields.filter((field) => !field.advanced)
      const advanced = fields.filter((field) => field.advanced)
      this.rows = [
        { kind: "back" },
        ...basic.map((field): ConfigRow => ({ kind: "field", field })),
        ...(advanced.length ? [{ kind: "advanced" as const, count: advanced.length }] : []),
        ...(this.advanced ? advanced.map((field): ConfigRow => ({ kind: "field", field })) : []),
      ]
    } else {
      const query = this.query.trim().toLocaleLowerCase()
      const matches = query
        ? this.fields.filter((field) => searchText(field).includes(query)).slice(0, 200)
        : []
      this.rows = [
        { kind: "back" },
        ...matches.map((field): ConfigRow => ({ kind: "field", field })),
      ]
    }
    this.selected = Math.max(0, Math.min(this.selected, Math.max(0, this.rows.length - 1)))
    this.renderRows()
  }

  private renderRows(): void {
    if (this.destroyed) return
    const filtering = this.page === "setup" && ["provider", "model"].includes(this.setupStep) && !this.editPurpose
    this.filterInput.visible = filtering
    if (filtering) {
      const query = this.setupStep === "provider" ? this.providerQuery : this.modelQuery
      if (this.filterInput.plainText !== query) this.filterInput.setText(query)
      this.filterInput.focus()
    }
    else this.filterInput.blur()
    for (const child of [...this.scroll.getChildren()]) {
      this.scroll.remove(child)
      child.destroyRecursively()
    }
    this.updateHeader()
    if (this.page === "setup" && !this.editPurpose) this.footer.content = filtering
      ? "Type to search · ↑/↓ move · Enter select · Esc back"
      : "↑/↓ move · Enter select · Esc back"
    if (this.loading && !this.rows.length) {
      this.scroll.add(this.rowText("  Preparing the complete settings map…", false, this.theme.muted))
      return
    }
    if (!this.rows.length) {
      this.scroll.add(this.rowText("  No matching settings.", false, this.theme.muted))
      return
    }
    this.rows.forEach((row, index) => {
      const selected = index === this.selected
      const text = this.describeRow(row, selected)
      const renderable = this.rowText(text, selected, selected ? this.theme.text : this.theme.muted)
      renderable.onMouseDown = (event) => {
        if (event.button !== 0) return
        event.preventDefault()
        event.stopPropagation()
        this.selected = index
        this.activate()
      }
      this.scroll.add(renderable)
    })
    const viewport = Math.max(3, this.scroll.height - 1)
    if (this.selected < this.scroll.scrollTop) this.scroll.scrollTo(this.selected)
    else if (this.selected >= this.scroll.scrollTop + viewport) {
      this.scroll.scrollTo(this.selected - viewport + 1)
    }
    this.updateDetail()
  }

  private rowText(content: string, selected: boolean, fg: string): TextRenderable {
    return new TextRenderable(this.renderer, {
      id: `nanobot-tui-config-row-${crypto.randomUUID()}`,
      content,
      width: "100%",
      height: 1,
      flexShrink: 0,
      fg,
      truncate: true,
      selectable: false,
      ...(selected ? { backgroundColor: RGBA.fromHex(this.theme.selectedBackground) } : {}),
    })
  }

  private describeRow(row: ConfigRow, selected: boolean): string {
    const marker = selected ? "›" : " "
    if (row.kind === "back") return `${marker} ← Configuration`
    if (row.kind === "action") return `${marker} ${row.label}`
    if (row.kind === "advanced") {
      return `${marker} ${this.advanced ? "▾" : "▸"} Advanced · ${row.count} settings`
    }
    if (row.kind === "section") {
      return `${marker} → ${row.section.label} · ${row.count} settings`
    }
    const suffix = row.field.deprecated ? " [legacy]" : ""
    const value = this.page === "setup" && row.field.path.endsWith("/apiBase") && !row.field.value
      ? "Provider default" : displayConfigValue(row.field)
    const label = this.page === "home" ? row.field.label : row.field.breadcrumb
    const available = Math.max(8, this.terminalWidth - value.length - 8)
    return `${marker} ${label.slice(0, available)}${suffix}  ${value}`
  }

  private updateHeader(): void {
    const page = this.page === "home" ? this.onboarding ? "Quick start" : "Overview"
      : this.page === "advanced-home" ? "Advanced settings"
      : this.page === "setup" ? `Quick start · ${this.setupStep === "provider" ? "1/4 Choose a provider"
        : this.setupStep === "credentials" ? "2/4 Connect your account"
          : this.setupStep === "model" ? "3/4 Preset · Choose model"
            : this.setupStep === "review" ? "3/4 Configure preset" : "4/4 Test and chat"}`
      : this.page === "search" ? `Search · ${this.query || "all settings"}`
        : this.snapshot?.presentation.sections.find((section) => section.id === this.sectionId)?.label
          || "Settings"
    const dirty = this.dirty.size ? ` · ${this.dirty.size} unsaved` : ""
    this.header.content = `Configuration · ${page}${dirty}${this.saving ? " · Loading…" : ""}`
    this.intro.content = this.page === "home"
      ? this.activeProvider() ? `${this.activeProvider()!.label} · ${this.snapshot ? activeSetupModel(this.snapshot) : ""}\n${this.tested && this.testedRevision === this.snapshot?.revision ? "Model replied successfully." : "Credentials saved · Model reply not checked in this setup."}`
        : "Get started with nanobot.\nConnect a model to send your first message."
      : this.page === "setup" ? this.setupIntro()
      : this.page === "search"
        ? "Search spans the complete configuration, including provider, channel, tool, and gateway fields."
        : this.snapshot?.presentation.sections.find((section) => section.id === this.sectionId)
          ?.description || ""
  }

  private updateDetail(): void {
    const row = this.rows[this.selected]
    if (!row) {
      this.detail.content = ""
      return
    }
    if (row.kind === "field") {
      const secret = row.field.secret
        ? row.field.configured ? " · secret is configured" : " · secret is not set"
        : ""
      const choices = row.field.enumValues.length
        ? ` · choices: ${row.field.enumValues.map(String).join(", ")}` : ""
      this.detail.content = `${row.field.description || row.field.breadcrumb}${secret}${choices}`
    } else if (row.kind === "action") {
      this.detail.content = row.description
    } else if (row.kind === "section") {
      this.detail.content = row.section.description
    } else if (row.kind === "advanced") {
      this.detail.content = "Low-frequency and expert settings stay folded until you need them."
    } else {
      this.detail.content = "Return to the minimal setup view."
    }
  }

  private select(destination: number): void {
    if (!this.rows.length) return
    this.selected = Math.max(0, Math.min(destination, this.rows.length - 1))
    this.renderRows()
  }

  private currentField(): ConfigField | null {
    const row = this.rows[this.selected]
    return row?.kind === "field" ? row.field : null
  }

  private activate(): void {
    const row = this.rows[this.selected]
    if (!row || this.loading || this.saving || this.waitingForGateway) return
    if (row.kind === "action") {
      row.run()
    } else if (row.kind === "back") {
      this.goHome()
    } else if (row.kind === "section") {
      this.page = "section"
      this.sectionId = row.section.id
      this.advanced = false
      this.selected = 0
      this.rebuildRows()
    } else if (row.kind === "advanced") {
      this.advanced = !this.advanced
      this.rebuildRows()
    } else if (row.field.type === "boolean") {
      this.toggle(row.field)
    } else if (row.field.enumValues.length) {
      this.cycle(row.field, 1)
    } else {
      this.beginFieldEdit(row.field)
    }
  }

  private goHome(): void {
    this.generation += 1
    this.cancelSignIn()
    this.cancelInput()
    this.page = "home"
    this.sectionId = ""
    this.advanced = false
    this.query = ""
    this.selected = 0
    this.rebuildRows()
  }

  private toggle(field: ConfigField): void {
    this.change(field, !Boolean(field.value))
  }

  private cycle(field: ConfigField, direction: -1 | 1): void {
    if (!field.enumValues.length) return
    const index = field.enumValues.findIndex((value) => value === field.value)
    const next = (Math.max(0, index) + direction + field.enumValues.length) % field.enumValues.length
    this.change(field, field.enumValues[next])
  }

  private clearSecret(field: ConfigField): void {
    writeConfigValue(this.draft, field.path, "")
    const secret = this.snapshot?.secrets.find((candidate) => candidate.path === field.path)
    if (secret) secret.configured = false
    this.dirty.add(field.path)
    this.feedback.fg = this.theme.error
    this.feedback.content = `${field.label} will be cleared when you save.`
    this.refreshFields()
  }

  private change(field: ConfigField, value: unknown): void {
    if (field.raw && value && typeof value === "object" && !Array.isArray(value)) {
      for (const secret of this.snapshot?.secrets || []) {
        if (!secret.path.startsWith(`${field.path}/`)) continue
        const relativePath = secret.path.slice(field.path.length)
        if (readConfigValue(value as Record<string, unknown>, relativePath) !== null) continue
        const current = readConfigValue(this.draft, secret.path)
        if (current !== null && current !== undefined) {
          writeConfigValue(value as Record<string, unknown>, relativePath, current)
        }
      }
    }
    writeConfigValue(this.draft, field.path, value)
    if (field.secret) {
      const secret = this.snapshot?.secrets.find((candidate) => candidate.path === field.path)
      if (secret) secret.configured = value !== null && value !== ""
    }
    this.dirty.add(field.path)
    this.feedback.fg = this.theme.muted
    this.feedback.content = this.page === "setup"
      ? "Change staged. Select the save action below to continue."
      : "Change staged. Press Ctrl+S to save."
    const selectedPath = field.path
    this.refreshFields()
    const next = this.rows.findIndex((row) => row.kind === "field" && row.field.path === selectedPath)
    if (next >= 0) this.selected = next
    this.renderRows()
  }

  private beginFieldEdit(field: ConfigField): void {
    this.editPurpose = "field"
    this.editingField = field
    this.secretValue = ""
    this.editorFrame.visible = true
    this.editorLabel.content = field.secret
      ? `${field.breadcrumb} · type a replacement · Enter apply · Esc cancel`
      : `${field.breadcrumb} · Enter apply · Shift+Enter newline · Esc cancel`
    this.editorInput.visible = !field.secret
    this.secretInput.visible = field.secret
    if (field.secret) {
      this.secretInput.content = "New value: "
      this.editorInput.blur()
    } else {
      this.editorInput.setText(editorInitialValue(field))
      this.editorInput.cursorOffset = this.editorInput.plainText.length
      this.editorInput.focus()
    }
    this.feedback.content = ""
    this.updateFooterForInput()
  }

  private beginSearch(): void {
    this.editPurpose = "search"
    this.editingField = null
    this.editorFrame.visible = true
    this.editorInput.visible = true
    this.secretInput.visible = false
    this.editorLabel.content = "Search every setting · Enter search · Esc cancel"
    this.editorInput.setText(this.query)
    this.editorInput.cursorOffset = this.query.length
    this.editorInput.focus()
    this.feedback.content = ""
    this.updateFooterForInput()
  }

  private handleEditKey(key: KeyEvent): boolean {
    if (key.name === "escape") {
      this.cancelInput()
      return true
    }
    if (this.editingField?.secret) {
      if (key.name === "return") {
        this.commitInput()
        return true
      }
      if (key.name === "backspace") {
        this.secretValue = Array.from(this.secretValue).slice(0, -1).join("")
        this.renderSecretInput()
        return true
      }
      if (!key.ctrl && !key.meta && key.sequence && key.sequence >= " ") {
        this.secretValue += key.sequence
        this.renderSecretInput()
      }
      return true
    }
    return false
  }

  private commitInput(): void {
    if (this.editPurpose === "search") {
      this.query = this.editorInput.plainText.trim()
      this.cancelInput()
      this.page = "search"
      this.selected = 0
      this.rebuildRows()
      return
    }
    const field = this.editingField
    if (!field) return
    const input = field.secret ? this.secretValue : this.editorInput.plainText
    try {
      if (this.inputAction) {
        const action = this.inputAction
        action(input.trim())
        this.cancelInput()
        return
      }
      const value = parseConfigValue(field, input)
      if (value !== undefined) this.change(field, value)
      this.cancelInput()
    } catch (error) {
      this.feedback.fg = this.theme.error
      this.feedback.content = errorMessage(error)
    }
  }

  private cancelInput(): void {
    this.inputAction = null
    this.editPurpose = null
    this.editingField = null
    this.secretValue = ""
    this.editorInput.blur()
    this.editorInput.setText("")
    this.editorFrame.visible = false
    this.editorInput.visible = true
    this.secretInput.visible = false
    this.footer.content = this.terminalWidth >= 72
      ? "↑/↓ move · enter edit · / search · ctrl+s save · esc back/close"
      : "↑/↓ · enter · / search · ctrl+s · esc"
  }

  private renderSecretInput(): void {
    const bullets = "•".repeat(Array.from(this.secretValue).length)
    this.secretInput.content = `New value: ${bullets}`
  }

  private updateFooterForInput(): void {
    this.footer.content = this.editingField?.secret
      ? "Input is hidden · enter apply · backspace erase · esc cancel"
      : "enter apply · shift+enter newline · esc cancel"
  }

  private handlePaste = (event: PasteEvent): void => {
    if (!this.visible || !this.editingField?.secret) return
    event.preventDefault()
    event.stopPropagation()
    this.secretValue += stripAnsiSequences(decodePasteBytes(event.bytes)).replace(/[\r\n]+/gu, "")
    this.renderSecretInput()
  }

  private action(label: string, description: string, run: () => void): ConfigRow {
    return { kind: "action", label, description, run }
  }

  private setupIntro(): string {
    if (this.setupStep === "provider") return `${this.providerGroup === "account" ? "Sign in with an account" : this.providerGroup === "local" ? "Connect a local model" : "Use an API key or cloud credentials"}\nType a provider name to narrow the list.`
    if (this.authorization?.userCode) return `Open the sign-in page and enter code: ${this.authorization.userCode}`
    if (this.setupStep === "credentials") return `${this.provider?.label || "Provider"} · ${this.provider?.oauth
      ? `${setupProviderStatus(this.provider)}\n${this.provider.configured ? "Sign in again, or continue with saved credentials and test access." : "Sign in with your account. No API key needed."}` : "Use credentials from this provider's developer console."}`
    if (this.setupStep === "model") return `${this.provider?.label} · ${this.provider ? setupProviderStatus(this.provider) : ""}\nType to find a model, or enter its exact ID below.`
    if (this.setupStep === "review") return `${this.provider?.label} · ${this.existingPresetName ? "Edit saved preset" : "Create a model preset"}\nA preset saves your model and generation settings together.`
    return this.tested ? "Model replied successfully. You're ready to chat."
      : `Preset ${this.presetName} saved · Model reply not verified.\nSend one short test message. Provider charges may apply.`
  }

  private activeProvider(): SetupProvider | undefined {
    if (!this.snapshot) return undefined
    const presetName = readConfigValue(this.snapshot.config, "/agents/defaults/modelPreset")
    const preset = typeof presetName === "string" && record(this.snapshot.config.modelPresets)
      ? this.snapshot.config.modelPresets[presetName] : null
    const name = record(preset) ? preset.provider : readConfigValue(this.snapshot.config, "/agents/defaults/provider")
    return this.providers.find((item) => item.configured && item.name === (name === "auto" ? this.resolvedProvider : name))
  }

  private pageRows(rows: ConfigRow[]): ConfigRow[] {
    const offset = this.listOffset
    return [
      ...rows.slice(offset, offset + 8),
      ...(offset > 0 ? [this.action("Previous results", "Show the previous eight matches.", () => {
        this.listOffset = Math.max(0, offset - 8); this.selected = 0; this.rebuildRows()
      })] : []),
      ...(offset + 8 < rows.length ? [this.action(`More results (${offset + 8}/${rows.length})`, "Show the next eight matches, or type to narrow the list.", () => {
        this.listOffset = offset + 8; this.selected = 0; this.rebuildRows()
      })] : []),
    ]
  }

  private setupRows(): ConfigRow[] {
    if (this.setupStep === "provider") return [
      ...this.pageRows(this.providers.filter((provider) =>
        (this.providerGroup === "account" ? provider.oauth : this.providerGroup === "local" ? provider.local : !provider.oauth && !provider.local)
        && `${provider.name} ${provider.label}`.toLocaleLowerCase().includes(this.providerQuery.toLocaleLowerCase()),
      ).map((provider) => this.action(
        `${provider.label} · ${setupProviderStatus(provider)}`,
        provider.oauth ? "Saved credentials may have expired or been revoked. Sign in again, or continue and test your preset."
          : "Use this provider's API key and endpoint. You will configure a model preset next.",
        () => {
          this.cancelSignIn()
          this.provider = provider
          this.connectionOptions = false
          if (provider.configured && !provider.oauth) { this.beginPreset(); return }
          this.setupStep = "credentials"
          this.selected = 0
          this.feedback.content = ""
          this.rebuildRows()
        },
      ))),
      this.action("Reload providers", "Retry loading the available services.", () => { void this.startSetup(this.providerGroup) }),
      { kind: "back" },
    ]
    if (this.setupStep === "credentials" && this.provider) {
      const provider = this.provider
      const rows: ConfigRow[] = []
      if (provider.oauth) {
        if (this.authorization) {
          const auth = this.authorization
          rows.push(this.action("Open sign-in page", auth.userCode ? `Enter this code in your browser: ${auth.userCode}`
            : "Finish signing in in your browser. Return here if a manual response is needed.",
          () => { void this.runSetup(async () => {
            if (!this.options.openUrl) throw new Error("Open the sign-in link shown below in your browser.")
            await this.options.openUrl(auth.url)
            this.feedback.content = auth.userCode ? `Browser opened. Enter code: ${auth.userCode}` : "Browser opened. Finish signing in to continue."
          }) }))
          if (auth.input === "authorization_code" || this.signInHelp) {
            if (auth.input !== "device_code") rows.push(this.action(
              auth.input === "callback_url" ? "Paste callback URL" : "Paste authorization code",
              auth.input === "callback_url" ? "If your browser could not connect after sign-in, paste its full address here."
                : "Copy the authorization code shown after sign-in and paste it here.",
              () => this.askSetup("Complete sign-in", true, (value) => {
                if (!value) throw new Error("Paste the response from your browser.")
                void this.completeSignIn(value)
              }),
            ))
            rows.push(this.action("Copy sign-in link", "Copy the full sign-in URL to open it on another device.", () => {
              void this.runSetup(async () => {
                if (this.options.copyText) await this.options.copyText(auth.url)
                else if (!this.renderer.copyToClipboardOSC52(auth.url)) throw new Error("This terminal could not copy the sign-in link. Try Open sign-in page.")
                this.feedback.content = "Sign-in link copied."
              })
            }))
            rows.push(this.action("Restart sign-in", "Cancel this authorization and get a fresh sign-in link.", () => {
              this.cancelSignIn()
              void this.startSignIn()
            }))
          }
          rows.push(this.action(this.signInHelp ? "Hide sign-in help" : "Browser didn't open?", "Show copy-link, manual completion, and restart options.", () => {
            this.signInHelp = !this.signInHelp; this.rebuildRows()
          }))
        } else {
          if (provider.configured) rows.push(this.action("Continue with saved credentials", "Configure a preset, then test access. Expired tokens may refresh automatically; revoked credentials require sign-in.", () => { this.beginPreset() }))
          if (provider.loginSupported) rows.push(this.action(
            provider.configured ? "Sign in again" : `Sign in to ${provider.label}`,
            "Start browser authorization. Account credentials are saved when sign-in completes.",
            () => { void this.startSignIn() },
          ))
          else if (!provider.configured) rows.push(this.action("Reload account status", "Sign in using the provider's CLI, then reload your account status.", () => { void this.startSetup() }))
        }
      } else {
        for (const [name, label, description] of [
          ["apiKey", provider.keyRequired ? "API key" : "API key (optional)", provider.keyRequired
            ? "Create an API key in your provider's developer console, then paste it here. Input is hidden."
            : "Leave empty for a local server or credentials from your cloud environment. Paste a key only if your service requires it."],
          ["apiBase", "API endpoint", "Use the provider's API base URL. Keep the default unless you use a proxy or local server."],
          ["region", "AWS region", "Enter the AWS region where you enabled model access, or use your AWS environment's default."],
          ["profile", "AWS profile", "Use an existing AWS credentials profile, or leave empty to use your environment's credentials."],
        ]) {
          if ((name === "region" || name === "profile") && !provider.advancedFields.includes(name)) continue
          const optional = name === "apiKey" && !provider.keyRequired
            || name === "apiBase" && !provider.baseRequired && !provider.local
          if (optional && !this.connectionOptions) continue
          const field = this.fields.find((item) => item.path === this.providerPath(name!))
          if (field) rows.push({ kind: "field", field: {
            ...field, label: label!, breadcrumb: label!, description: description!,
            ...(name === "apiBase" && !field.value ? { value: provider.apiBase } : {}),
          } })
        }
        rows.push(this.action("Save connection and configure preset", "Save the connection, then configure a named model preset.", () => {
          void this.runSetup(async () => {
            const key = this.fields.find((field) => field.path === this.providerPath("apiKey"))
            if (provider.keyRequired && !key?.configured) throw new Error("Enter an API key before continuing.")
            const base = readConfigValue(this.draft, this.providerPath("apiBase")) || provider.apiBase
            if (!base && provider.baseRequired) throw new Error("Enter your provider's API endpoint before continuing.")
            if (base) {
              const url = new URL(String(base))
              if (!["http:", "https:"].includes(url.protocol)) throw new Error("Use an http:// or https:// API endpoint.")
            }
            if (this.dirty.size) await this.persistSetup()
            provider.configured = true
          }, () => { this.beginPreset() })
        }))
        rows.push(this.action(this.connectionOptions ? "Hide connection options" : "More connection options", "Change the default endpoint or add optional authentication.", () => {
          this.connectionOptions = !this.connectionOptions
          this.rebuildRows()
        }))
      }
      rows.push(this.action("Choose another provider", "Return to the provider list. Saved credentials remain available.", () => {
        this.cancelSignIn()
        this.setupStep = "provider"
        this.selected = 0
        this.rebuildRows()
      }))
      return rows
    }
    if (this.setupStep === "model") return [
      ...this.pageRows(this.models.filter((model) => `${model.id} ${model.label}`.toLocaleLowerCase().includes(this.modelQuery.toLocaleLowerCase())).map((model) => this.action(
        model.label, model.description || model.id, () => this.chooseSetupModel(model.id),
      ))),
      this.action("Enter a model ID", "Use the exact model ID listed by your provider. Availability is checked when you send a message.", () => this.askSetup("Model ID", false, (value) => {
        if (!value) throw new Error("Enter a model ID.")
        this.chooseSetupModel(value)
      })),
      this.action("Reload model list", "Retry fetching the models available to this account.", () => { void this.loadSetupModels() }),
      this.action("Back to preset", "Keep the preset and return without changing the model.", () => {
        this.setupStep = "review"
        this.selected = 0
        this.rebuildRows()
      }),
    ]
    if (this.setupStep === "review" && this.preset) {
      const preset = this.preset
      const presets = record(this.snapshot?.config.modelPresets) ? this.snapshot!.config.modelPresets : {}
      return [
        this.action(`Preset name · ${this.presetName}`, this.existingPresetName
          ? "Editing this saved preset also affects chats that use it. Rename in Advanced settings."
          : "Give this configuration a name, such as Coding or Fast replies.", () => {
          if (!this.existingPresetName) this.askSetup("Preset name", false, (value) => {
            this.presetName = value.trim(); this.rebuildRows()
          }, this.presetName)
        }),
        this.action(`Model · ${preset.model || "Choose a model"}`, "Choose the model this preset will use.", () => { void this.loadSetupModels() }),
        this.action(`Use as default · ${this.makeDefault ? "Yes" : "No"}`, "Use this preset for new chats. Existing chats keep their selection.", () => {
          this.makeDefault = !this.makeDefault; this.rebuildRows()
        }),
        this.action(this.generationOptions ? "Hide generation settings" : "Generation settings", "Adjust output length, context window, temperature, and reasoning effort.", () => {
          this.generationOptions = !this.generationOptions; this.rebuildRows()
        }),
        ...(this.generationOptions ? ([
          ["maxTokens", "Output token limit", "Maximum tokens generated in one response."],
          ["contextWindowTokens", "Context window", "Set the context capacity supported by your model."],
          ["temperature", "Temperature", "Randomness from 0 to 2; lower values give more consistent replies."],
          ["reasoningEffort", "Reasoning effort", "Use a value supported by your model, or leave empty for its default."],
        ] as const).map(([key, label, description]) => this.action(`${label} · ${preset[key] ?? "Model default"}`, description, () => {
          this.askSetup(label, false, (value) => {
            if (key === "reasoningEffort") preset[key] = value.trim() || null
            else {
              if (!value.trim() || !Number.isFinite(Number(value))) throw new Error("Enter a number.")
              preset[key] = Number(value)
            }
            this.rebuildRows()
          }, String(preset[key] ?? ""))
        })) : []),
        this.action(this.makeDefault ? "Save preset and use as default" : "Save preset", "Save the named preset and its generation settings together.", () => { void this.finishSetup() }),
        ...Object.entries(presets).filter(([name, value]) => name !== this.existingPresetName && record(value) && value.provider === this.provider?.name)
          .map(([name, value]) => this.action(`Edit preset · ${name}`, "Load this saved preset. This replaces the unsaved preset form.", () => {
            this.preset = { ...newSetupPreset(this.snapshot!, this.provider!.name), ...value as SetupPreset }
            this.presetName = name; this.existingPresetName = name; this.rebuildRows()
          })),
        ...(this.existingPresetName ? [this.action("Create a new preset", "Start a separate preset for this provider.", () => {
          this.preset = null; this.beginPreset()
        })] : []),
        this.action("Discard draft and reload", "Discard unsaved preset and workspace changes.", () => {
          this.preset = null
          void this.runSetup(async () => { this.useSnapshot(await this.options.load()) })
        }),
      ]
    }
    return [
      this.action(this.tested ? "Send another test message" : "Send a test message", "Sends ‘Reply with a short hello.’ to this model once. Provider charges may apply.", () => { void this.testConnection() }),
      this.action(this.makeDefault ? "Start a new chat" : "Return to chat", this.makeDefault ? "Start a fresh conversation with your saved default preset." : "Select this preset from the model menu when you want to use it.", () => {
        if (this.hide() && this.makeDefault) this.options.startChat?.()
      }),
      this.action("Change connection", "Update the API key or endpoint, or sign in again. Your saved model is kept.", () => {
        this.setupStep = "credentials"; this.selected = 0; this.rebuildRows()
      }),
      this.action("Choose a different model", "Keep the connection and choose another model.", () => { this.beginPreset() }),
      { kind: "back" },
    ]
  }

  private providerPath(field: string): string {
    const normalize = (value: string) => value.replace(/[^a-z0-9]/giu, "").toLocaleLowerCase()
    const key = Object.keys(record(this.draft.providers) ? this.draft.providers : {})
      .find((name) => normalize(name) === normalize(this.provider?.name || "")) || this.provider?.name || ""
    return `/providers/${escapePointer(key)}/${field}`
  }

  private async startSetup(group = this.providerGroup): Promise<void> {
    if (this.dirty.size && this.page !== "setup") {
      this.feedback.content = "Save your advanced changes with Ctrl+S before starting Quick start."
      return
    }
    this.page = "setup"
    this.providerGroup = group
    this.setupStep = "provider"
    this.providerQuery = ""
    this.filterInput.setText("")
    this.listOffset = 0
    this.selected = 0
    this.cancelSignIn()
    await this.runSetup(async () => {
      if (!this.options.read) throw new Error("Update the gateway to use guided setup.")
      this.providers = decodeSetupProviders(await this.options.read("/api/settings"))
    })
  }

  private async runSetup(work: () => Promise<void>, next?: () => void): Promise<void> {
    if (this.saving) return
    const generation = this.generation
    this.saving = true
    this.feedback.fg = this.theme.muted
    this.feedback.content = ""
    this.rebuildRows()
    let succeeded = false
    try {
      await work()
      succeeded = true
    } catch (error) {
      if (this.destroyed || generation !== this.generation) return
      this.feedback.fg = this.theme.error
      this.feedback.content = errorMessage(error)
    } finally {
      this.saving = false
      if (!this.destroyed && generation === this.generation) {
        this.rebuildRows()
        if (succeeded) next?.()
      }
    }
  }

  private async persistSetup(config = this.draft): Promise<void> {
    if (!this.snapshot) throw new Error("Reload configuration before saving.")
    const saved = await this.options.save(this.snapshot.revision, cloneConfig(config))
    if (this.destroyed) return
    this.snapshot = saved
    this.draft = cloneConfig(saved.config)
    this.dirty.clear()
    this.refreshFields()
  }

  private cancelSignIn(): void {
    this.stopCallback?.()
    this.stopCallback = null
    this.pendingCallback = null
    this.authorizationSubmitted = false
    if (this.signInTimer) clearTimeout(this.signInTimer)
    this.signInTimer = null
    this.signInHelp = false
    const auth = this.authorization
    this.authorization = null
    if (auth && this.provider && this.options.request) {
      void this.options.request("settings.provider.oauth_complete", {
        provider: this.provider.name, flow_id: auth.flowId, cancel: true,
      }).catch(() => {})
    }
  }

  private async startSignIn(): Promise<void> {
    const provider = this.provider
    if (!provider) return
    await this.runSetup(async () => {
      if (!this.options.request) throw new Error("Update the gateway to sign in.")
      const result = await this.options.request("settings.provider.oauth_login", {
        provider: provider.name, remote_browser: true, interactive_flow: true,
      })
      if (this.destroyed || !this.visible) return
      this.authorization = decodeSetupAuthorization(result)
      if (!this.authorization) {
        const connected = decodeSetupProviders(result).find((item) => item.name === provider.name)
        provider.configured = connected?.configured === true
        provider.expiresAt = connected?.expiresAt ?? null
      }
      if (this.authorization) {
        this.feedback.content = "Waiting for browser sign-in… Esc goes back; Ctrl+C exits."
        if (this.authorization.input === "callback_url") {
          try {
            if (!this.options.listenForCallback) throw new Error("Callback listener unavailable")
            const auth = this.authorization
            this.stopCallback = this.options.listenForCallback(auth.url, (url) => {
              if (this.authorization === auth) void this.completeSignIn(url)
            })
          } catch {
            this.signInHelp = true
            this.feedback.content = "After signing in, paste the callback URL from your browser here."
          }
        }
        try {
          if (!this.options.openUrl) throw new Error("Browser unavailable")
          await this.options.openUrl(this.authorization.url)
        } catch {
          this.signInHelp = true
          this.feedback.content = "Could not open a browser. Copy the sign-in link to continue."
        }
      }
    }, () => {
      if (this.authorization) this.scheduleSignIn()
      else if (provider.configured) this.beginPreset()
    })
  }

  private scheduleSignIn(): void {
    if (this.signInTimer) clearTimeout(this.signInTimer)
    if (!this.authorization || (this.authorization.input === "authorization_code" && !this.authorizationSubmitted) || this.destroyed || !this.visible) return
    this.signInTimer = setTimeout(() => { void this.completeSignIn() }, 1500)
  }

  private async completeSignIn(response?: string): Promise<void> {
    const auth = this.authorization
    const provider = this.provider
    if (!auth || !provider) return
    if (this.signInBusy) {
      if (response) this.pendingCallback = { auth, response }
      else this.scheduleSignIn()
      return
    }
    this.signInBusy = true
    if (response) this.authorizationSubmitted = true
    if (this.signInTimer) clearTimeout(this.signInTimer)
    try {
      if (!this.options.request) throw new Error("Update the gateway to sign in.")
      const result = await this.options.request("settings.provider.oauth_complete", {
        provider: provider.name, flow_id: auth.flowId,
        ...(response ? { authorization_response: response } : {}),
      })
      if (this.destroyed || this.authorization !== auth) return
      if (record(result) && result.status === "pending") {
        this.scheduleSignIn()
        return
      }
      const connected = decodeSetupProviders(result).find((item) => item.name === provider.name)
      if (!connected?.configured) throw new Error("Sign-in did not complete. Try signing in again.")
      provider.configured = true
      provider.expiresAt = connected.expiresAt
      this.authorization = null
      this.stopCallback?.()
      this.stopCallback = null
      this.cancelInput()
      this.beginPreset()
    } catch (error) {
      if (!this.destroyed && this.authorization === auth) {
        this.signInHelp = true
        this.feedback.fg = this.theme.error
        this.feedback.content = `${errorMessage(error)} Use Restart sign-in to try again.`
        this.rebuildRows()
      }
    } finally {
      this.signInBusy = false
      const pending = this.pendingCallback
      this.pendingCallback = null
      if (pending && this.authorization === pending.auth) void this.completeSignIn(pending.response)
    }
  }

  private async testConnection(): Promise<void> {
    if (!this.provider || !this.snapshot) return
    this.tested = false
    this.testedRevision = ""
    await this.runSetup(async () => {
      if (!this.options.request) throw new Error("Update the gateway to send a test message.")
      this.feedback.content = "Sending one test message…"
      const result = await this.options.request("settings.provider.test", {
        preset_name: this.presetName,
      })
      if (this.destroyed) return
      if (!record(result) || typeof result.message !== "string") throw new Error("No test result returned. Retry or check the connection.")
      this.tested = result.status === "ok"
      this.testedRevision = this.snapshot!.revision
      this.feedback.fg = this.tested ? this.theme.success : this.theme.error
      const message = stripAnsiSequences(result.message).replace(/[\r\n]+/gu, " ")
      this.feedback.content = this.tested && typeof result.elapsed_seconds === "number"
        ? `Reply (${result.elapsed_seconds}s): ${message}` : message
    })
  }

  private beginPreset(): void {
    if (!this.provider || !this.snapshot) return
    if (!this.preset || this.preset.provider !== this.provider.name) {
      this.preset = newSetupPreset(this.snapshot, this.provider.name)
      const presets = record(this.snapshot.config.modelPresets) ? this.snapshot.config.modelPresets : {}
      const base = this.provider.label.slice(0, 40)
      this.presetName = base
      let suffix = 2
      while (Object.keys(presets).some((name) => name.toLowerCase() === this.presetName.toLowerCase()) || this.presetName.toLowerCase() === "default") this.presetName = `${base} ${suffix++}`
      this.existingPresetName = null
      this.makeDefault = true
    }
    this.setupStep = "review"
    this.listOffset = 0
    this.selected = 0
    this.feedback.content = ""
    this.rebuildRows()
  }

  private async loadSetupModels(): Promise<void> {
    if (!this.provider) return
    this.setupStep = "model"
    this.selected = 0
    this.models = []
    this.modelQuery = ""
    this.filterInput.setText("")
    this.listOffset = 0
    await this.runSetup(async () => {
      if (!this.options.read) throw new Error("Enter a model ID to continue.")
      const result = decodeSetupModels(await this.options.read(`/api/settings/provider-models?provider=${encodeURIComponent(this.provider!.name)}`))
      if (this.destroyed) return
      this.models = result.models
      this.feedback.content = result.message || (result.models.length ? "" : "No models listed. Enter a model ID or reload the list.")
    })
  }

  private chooseSetupModel(model: string): void {
    if (this.preset) this.preset.model = model
    this.setupStep = "review"
    this.listOffset = 0
    this.selected = 0
    this.feedback.content = "Configure the preset, then save it. A test message is optional."
    this.rebuildRows()
  }

  private async finishSetup(): Promise<void> {
    if (!this.snapshot || !this.provider || !this.preset) return
    await this.runSetup(async () => {
      const candidate = setupDraft({ ...this.snapshot!, config: this.draft }, this.presetName, this.preset!, this.makeDefault, this.existingPresetName)
      await this.persistSetup(candidate)
      if (this.destroyed) return
      this.existingPresetName = this.presetName.trim()
      this.presetName = this.existingPresetName
      this.setupStep = "done"
      this.tested = false
      this.testedRevision = ""
      this.selected = 0
      this.feedback.fg = this.theme.success
      this.feedback.content = this.makeDefault ? "Preset saved as default for new chats." : "Preset saved. Select it from the model menu when you want to use it."
      this.options.onStatus?.("Model preset saved")
    })
  }

  private askSetup(label: string, secret: boolean, action: (value: string) => void, initialValue = ""): void {
    this.beginFieldEdit({ path: "", label, breadcrumb: label, description: "", sectionId: "models",
      type: "string", value: initialValue, enumValues: [], nullable: false, secret, configured: false,
      deprecated: false, advanced: false, raw: false })
    this.inputAction = action
  }

  private async save(): Promise<void> {
    if (!this.snapshot || !this.dirty.size || this.saving) {
      if (!this.dirty.size) {
        this.feedback.fg = this.theme.muted
        this.feedback.content = "No changes to save."
      }
      return
    }
    this.saving = true
    this.feedback.fg = this.theme.muted
    this.feedback.content = "Saving configuration…"
    try {
      const snapshot = await this.options.save(this.snapshot.revision, cloneConfig(this.draft))
      if (this.destroyed) return
      this.useSnapshot(snapshot)
      this.feedback.fg = this.theme.success
      this.feedback.content = snapshot.requires_restart
        ? "Saved. Restart nanobot to apply settings that cannot reload live."
        : "Configuration saved."
      this.options.onStatus?.("Configuration saved")
    } catch (error) {
      if (!this.destroyed) {
        this.feedback.fg = this.theme.error
        this.feedback.content = errorMessage(error)
      }
    } finally {
      this.saving = false
      if (!this.destroyed) this.renderRows()
    }
  }
}
