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
  record, setupDraft,
  type SetupAuthorization, type SetupModel, type SetupProvider,
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
}

type EditorPage = "home" | "section" | "search" | "setup"
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
  private saving = false
  private destroyed = false
  private discardArmed = false
  private terminalWidth = 80
  private setupStep: "provider" | "credentials" | "model" | "review" | "done" = "provider"
  private providers: SetupProvider[] = []
  private provider: SetupProvider | null = null
  private models: SetupModel[] = []
  private model = ""
  private authorization: SetupAuthorization | null = null
  private inputAction: ((value: string) => void) | null = null
  private generation = 0
  private modelQuery = ""

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
      minHeight: 1,
      maxHeight: 3,
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
    this.root.add(this.scroll)
    this.root.add(this.editorFrame)
    this.root.add(this.feedback)
    this.root.add(this.footer)
    this.renderer.keyInput.on("paste", this.handlePaste)
  }

  get visible(): boolean {
    return this.root.visible
  }

  async show(quickStart = false): Promise<void> {
    if (this.loading) return
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
        if (quickStart) void this.startSetup()
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
    if (this.saving || this.loading) return true
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
        this.setupStep = "provider"
        this.cancelSignIn()
        this.selected = 0
        this.rebuildRows()
        return true
      }
      if (this.page !== "home") this.goHome()
      else this.hide()
      return true
    }
    if (!key.ctrl && !key.meta && key.name === "/") {
      if (this.page === "setup") return true
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
      const field = this.currentField()
      if (field?.secret && field.configured) this.clearSecret(field)
      return true
    }
    if (["left", "right"].includes(key.name)) {
      const field = this.currentField()
      if (field?.enumValues.length) this.cycle(field, key.name === "left" ? -1 : 1)
      else if (field?.type === "boolean") this.toggle(field)
      return true
    }
    if (key.name === "return" || key.name === "space") {
      this.activate()
      return true
    }
    return true
  }

  resize(width: number, height: number): void {
    this.terminalWidth = width
    this.root.paddingLeft = width >= 96 ? 3 : 1
    this.root.paddingRight = width >= 96 ? 3 : 1
    this.intro.visible = height >= 13
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
    this.destroyed = true
    this.cancelSignIn()
    this.generation += 1
    this.renderer.keyInput.off("paste", this.handlePaste)
  }

  private useSnapshot(snapshot: ConfigEditorSnapshot): void {
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
    if (!this.snapshot) {
      this.rows = []
      return
    }
    if (this.page === "home") {
      this.rows = [
        this.action("Quick start",
          "New here? Start with guided setup. You can sign in with an account or use an API key.",
          () => { void this.startSetup() }),
        ...this.snapshot.presentation.sections.map((section): ConfigRow => ({
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
    for (const child of [...this.scroll.getChildren()]) {
      this.scroll.remove(child)
      child.destroyRecursively()
    }
    this.updateHeader()
    if (this.page === "setup" && !this.editPurpose) this.footer.content = "↑/↓ move · Enter select · Esc back"
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
    const page = this.page === "home" ? "Overview"
      : this.page === "setup" ? `Quick start · ${this.setupStep === "provider" ? "1/4 Choose a provider"
        : this.setupStep === "credentials" ? "2/4 Connect your account"
          : this.setupStep === "model" ? "3/4 Choose a model"
            : this.setupStep === "review" ? "4/4 Review and save" : "Saved"}`
      : this.page === "search" ? `Search · ${this.query || "all settings"}`
        : this.snapshot?.presentation.sections.find((section) => section.id === this.sectionId)?.label
          || "Settings"
    const dirty = this.dirty.size ? ` · ${this.dirty.size} unsaved` : ""
    this.header.content = `Configuration · ${page}${dirty}${this.saving ? " · Loading…" : ""}`
    this.intro.content = this.page === "home"
      ? `Current model: ${this.snapshot ? activeSetupModel(this.snapshot) : "Loading…"}. Advanced settings below.`
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
    if (!row || this.loading || this.saving) return
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
    if (this.setupStep === "provider") return "Choose the service you have an account with. Connected services appear first."
    if (this.authorization?.userCode) return `Open the sign-in page and enter code: ${this.authorization.userCode}`
    if (this.setupStep === "credentials") return `${this.provider?.label || "Provider"} · ${this.provider?.oauth
      ? "Sign in with your account. No API key needed." : "Use credentials from this provider's developer console."}`
    if (this.setupStep === "model") return "Choose a model available to your account, or enter its exact ID."
    if (this.setupStep === "review") return `${this.provider?.label} · ${this.model}`
    return "Your default model is saved. Close setup and send a message to try it."
  }

  private setupRows(): ConfigRow[] {
    if (this.setupStep === "provider") return [
      ...this.providers.map((provider) => this.action(
        `${provider.label} · ${provider.configured ? "Connected" : provider.oauth ? "Sign in with account" : provider.keyRequired ? "API key" : "API connection"}`,
        provider.oauth ? "Use browser sign-in with your existing account."
          : "Use this provider's API key and endpoint. You will choose the model next.",
        () => {
          this.provider = provider
          this.cancelSignIn()
          this.setupStep = "credentials"
          this.selected = 0
          this.feedback.content = ""
          this.rebuildRows()
        },
      )),
      this.action("Reload providers", "Retry loading the available services.", () => { void this.startSetup() }),
      { kind: "back" },
    ]
    if (this.setupStep === "credentials" && this.provider) {
      const provider = this.provider
      const rows: ConfigRow[] = []
      if (provider.oauth) {
        if (this.authorization) {
          const auth = this.authorization
          rows.push(this.action("Open sign-in page", auth.userCode ? `Enter this code in your browser: ${auth.userCode}`
            : "Finish signing in in your browser, then check sign-in here.",
          () => { void this.runSetup(async () => {
            if (!this.options.openUrl) throw new Error("Open the sign-in link shown below in your browser.")
            await this.options.openUrl(auth.url)
            this.feedback.content = auth.userCode ? `Browser opened. Enter code: ${auth.userCode}` : "Browser opened. Complete sign-in, then check sign-in here."
          }) }))
          rows.push(this.action("Check sign-in", "Check whether browser sign-in is complete.", () => { void this.completeSignIn() }))
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
        } else {
          if (provider.configured) rows.push(this.action("Continue with connected account", "Keep your current sign-in and choose a model.", () => { void this.loadSetupModels() }))
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
          const field = this.fields.find((item) => item.path === this.providerPath(name!))
          if (field) rows.push({ kind: "field", field: {
            ...field, label: label!, breadcrumb: label!, description: description!,
            ...(name === "apiBase" && !field.value ? { value: provider.apiBase } : {}),
          } })
        }
        rows.push(this.action("Save connection and choose a model", "Save the API connection now so nanobot can load your available models. The default model is unchanged until the final step.", () => {
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
          }, () => { void this.loadSetupModels() })
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
      this.action("Find a model", "Filter the model list by name.", () => this.askSetup("Find a model", false, (value) => {
        this.modelQuery = value.toLocaleLowerCase()
        this.selected = 0
        this.rebuildRows()
      })),
      ...this.models.filter((model) => `${model.id} ${model.label}`.toLocaleLowerCase().includes(this.modelQuery)).map((model) => this.action(
        model.label, model.description || model.id, () => this.chooseSetupModel(model.id),
      )),
      this.action("Enter a model ID", "Use the exact model ID listed by your provider. Availability is checked when you send a message.", () => this.askSetup("Model ID", false, (value) => {
        if (!value) throw new Error("Enter a model ID.")
        this.chooseSetupModel(value)
      })),
      this.action("Reload model list", "Retry fetching the models available to this account.", () => { void this.loadSetupModels() }),
      this.action("Back to connection", "Change credentials or sign in again.", () => {
        this.setupStep = "credentials"
        this.selected = 0
        this.rebuildRows()
      }),
    ]
    if (this.setupStep === "review") {
      const workspace = this.fields.find((field) => field.path === "/agents/defaults/workspace")
      return [
        ...(workspace ? [{ kind: "field" as const, field: { ...workspace, breadcrumb: "Workspace", description: "The folder where nanobot keeps its workspace files. Keep the default to get started." } }] : []),
        this.action("Save as default model", "Use this provider and model for new chats. Existing named model presets are preserved.", () => { void this.finishSetup() }),
        this.action("Choose a different model", "Return to the model list.", () => {
          this.setupStep = "model"
          this.selected = 0
          this.rebuildRows()
        }),
        this.action("Discard draft and reload", "Discard unsaved model and workspace changes and reload the saved configuration.", () => {
          void this.runSetup(async () => { this.useSnapshot(await this.options.load()) })
        }),
      ]
    }
    return [
      this.action("Close setup and chat", "Send a message to try your selected model. If credentials or access are rejected, reopen /config to update the connection.", () => this.hide()),
      { kind: "back" },
    ]
  }

  private providerPath(field: string): string {
    const normalize = (value: string) => value.replace(/[^a-z0-9]/giu, "").toLocaleLowerCase()
    const key = Object.keys(record(this.draft.providers) ? this.draft.providers : {})
      .find((name) => normalize(name) === normalize(this.provider?.name || "")) || this.provider?.name || ""
    return `/providers/${escapePointer(key)}/${field}`
  }

  private async startSetup(): Promise<void> {
    if (this.dirty.size && this.page !== "setup") {
      this.feedback.content = "Save your advanced changes with Ctrl+S before starting Quick start."
      return
    }
    this.page = "setup"
    this.setupStep = "provider"
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

  private async persistSetup(): Promise<void> {
    if (!this.snapshot) throw new Error("Reload configuration before saving.")
    const saved = await this.options.save(this.snapshot.revision, cloneConfig(this.draft))
    this.snapshot = saved
    this.draft = cloneConfig(saved.config)
    this.dirty.clear()
    this.refreshFields()
  }

  private cancelSignIn(): void {
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
      this.authorization = decodeSetupAuthorization(result)
      if (!this.authorization) provider.configured = true
      this.feedback.content = this.authorization?.userCode
        ? `Enter code in your browser: ${this.authorization.userCode}`
        : this.authorization ? "Select Open sign-in page to continue in your browser." : "Signed in. Continue to choose a model."
    })
  }

  private async completeSignIn(response?: string): Promise<void> {
    const auth = this.authorization
    const provider = this.provider
    if (!auth || !provider) return
    await this.runSetup(async () => {
      if (!this.options.request) throw new Error("Update the gateway to sign in.")
      const result = await this.options.request("settings.provider.oauth_complete", {
        provider: provider.name, flow_id: auth.flowId,
        ...(response ? { authorization_response: response } : {}),
      })
      if (record(result) && result.status === "pending") {
        this.feedback.content = "Waiting for browser sign-in. Complete it, then check again."
        return
      }
      const connected = decodeSetupProviders(result).find((item) => item.name === provider.name)
      if (!connected?.configured) throw new Error("Sign-in did not complete. Try signing in again.")
      provider.configured = true
      this.authorization = null
      this.feedback.content = "Signed in. Continue with your connected account to choose a model."
    })
  }

  private async loadSetupModels(): Promise<void> {
    if (!this.provider) return
    this.setupStep = "model"
    this.selected = 0
    this.models = []
    this.modelQuery = ""
    await this.runSetup(async () => {
      if (!this.options.read) throw new Error("Enter a model ID to continue.")
      const result = decodeSetupModels(await this.options.read(`/api/settings/provider-models?provider=${encodeURIComponent(this.provider!.name)}`))
      this.models = result.models
      this.feedback.content = result.message || (result.models.length ? "" : "No models listed. Enter a model ID or reload the list.")
    })
  }

  private chooseSetupModel(model: string): void {
    this.model = model
    this.setupStep = "review"
    this.selected = 0
    this.feedback.content = "Review your workspace, then save your default model."
    this.rebuildRows()
  }

  private async finishSetup(): Promise<void> {
    if (!this.snapshot || !this.provider || !this.model) return
    await this.runSetup(async () => {
      this.draft = setupDraft({ ...this.snapshot!, config: this.draft }, this.provider!.name, this.model)
      this.dirty.add("/agents/defaults/model")
      await this.persistSetup()
      this.setupStep = "done"
      this.selected = 0
      this.feedback.fg = this.theme.success
      this.feedback.content = "Saved. New chats will use your selected model."
      this.options.onStatus?.("Default model saved")
    })
  }

  private askSetup(label: string, secret: boolean, action: (value: string) => void): void {
    this.beginFieldEdit({ path: "", label, breadcrumb: label, description: "", sectionId: "models",
      type: "string", value: "", enumValues: [], nullable: false, secret, configured: false,
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
