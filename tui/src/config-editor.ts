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
  primaryConfigPaths,
  readConfigValue,
  writeConfigValue,
  type ConfigField,
} from "./config-editor-model"
import { hideScrollbars } from "./scrollbox"
import type { ConfigEditorSection, ConfigEditorSnapshot } from "./protocol"

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
}

type EditorPage = "home" | "section" | "search"
type EditPurpose = "field" | "search"
type ConfigRow =
  | { kind: "field"; field: ConfigField }
  | { kind: "section"; section: ConfigEditorSection; count: number }
  | { kind: "advanced"; count: number }
  | { kind: "back" }

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
      height: 1,
      flexShrink: 0,
      fg: theme.muted,
      truncate: true,
      selectable: false,
    })
    this.detail = new TextRenderable(renderer, {
      id: "nanobot-tui-config-detail",
      content: "",
      width: "100%",
      minHeight: 1,
      maxHeight: 2,
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

  async show(): Promise<void> {
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
    if (!force && this.dirty.size && !this.discardArmed) {
      this.discardArmed = true
      this.feedback.fg = this.theme.error
      this.feedback.content = "Unsaved changes. Press Esc again to discard them, or Ctrl+S to save."
      return false
    }
    this.cancelInput()
    this.root.visible = false
    this.discardArmed = false
    this.options.onVisibilityChange?.(false)
    return true
  }

  handleKey(key: KeyEvent): boolean {
    if (!this.visible) return false
    if (this.editPurpose) return this.handleEditKey(key)
    if (key.name !== "escape") this.discardArmed = false
    if (key.ctrl && key.name === "s") {
      void this.save()
      return true
    }
    if (key.name === "escape") {
      if (this.page !== "home") this.goHome()
      else this.hide()
      return true
    }
    if (!key.ctrl && !key.meta && key.name === "/") {
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
    this.detail.maxHeight = height >= 18 ? 2 : 1
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
      const fields = primaryConfigPaths(this.snapshot).flatMap((path) => {
        const field = this.fields.find((candidate) => candidate.path === path && !candidate.raw)
        return field ? [field] : []
      })
      this.rows = [
        ...fields.map((field): ConfigRow => ({ kind: "field", field })),
        ...this.snapshot.presentation.sections.map((section): ConfigRow => ({
          kind: "section",
          section,
          count: this.fields.filter((field) => field.sectionId === section.id).length,
        })),
      ]
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
    for (const child of [...this.scroll.getChildren()]) {
      this.scroll.remove(child)
      child.destroyRecursively()
    }
    this.updateHeader()
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
    if (row.kind === "back") return `${marker} ← Essentials`
    if (row.kind === "advanced") {
      return `${marker} ${this.advanced ? "▾" : "▸"} Advanced · ${row.count} settings`
    }
    if (row.kind === "section") {
      return `${marker} → ${row.section.label} · ${row.count} settings`
    }
    const suffix = row.field.deprecated ? " [legacy]" : ""
    const value = displayConfigValue(row.field)
    const label = this.page === "home" ? row.field.label : row.field.breadcrumb
    const available = Math.max(8, this.terminalWidth - value.length - 8)
    return `${marker} ${label.slice(0, available)}${suffix}  ${value}`
  }

  private updateHeader(): void {
    const page = this.page === "home" ? "Essentials"
      : this.page === "search" ? `Search · ${this.query || "all settings"}`
        : this.snapshot?.presentation.sections.find((section) => section.id === this.sectionId)?.label
          || "Settings"
    const dirty = this.dirty.size ? ` · ${this.dirty.size} unsaved` : ""
    this.header.content = `Configuration · ${page}${dirty}`
    this.intro.content = this.page === "home"
      ? "Set up what nanobot needs first. Every other setting remains available below."
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
      this.detail.content = `${row.field.path}${secret}${choices}${row.field.description
        ? `\n${row.field.description}` : ""}`
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
    if (row.kind === "back") {
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
    this.feedback.content = "Change staged. Press Ctrl+S to save."
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
      const value = parseConfigValue(field, input)
      if (value !== undefined) this.change(field, value)
      this.cancelInput()
    } catch (error) {
      this.feedback.fg = this.theme.error
      this.feedback.content = errorMessage(error)
    }
  }

  private cancelInput(): void {
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
