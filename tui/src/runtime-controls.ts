import {
  TextRenderable,
  type BoxRenderable,
  type CliRenderer,
  type KeyEvent,
} from "@opentui/core"

import {
  fetchRuntimeControls,
  type ApiReauthenticator,
  type WorkspaceScopePayload,
} from "./protocol"
import { PickerMenu, type PickerMenuTheme } from "./picker-menu"

interface RuntimeControlsTheme extends PickerMenuTheme {
  accent: string
  faint: string
}

type Choice =
  | { kind: "model"; name: string; label: string; detail: string }
  | { kind: "access"; mode: "restricted" | "full"; label: string; detail: string }

const CONTROLS_CACHE_MS = 10_000

interface RuntimeControlsOptions {
  apiUrl: string
  apiToken: string
  model: string
  modelPreset: string
  workspace: string
  access: string
  reauthenticateApi?: ApiReauthenticator
  available: () => boolean
  beforeOpen: () => void
  refreshScope: () => Promise<void>
  onModel: (name: string) => void
  onAccess: (scope: WorkspaceScopePayload) => void
  onStatus: (message: string) => void
  onVisibilityChange: (visible: boolean) => void
}

/** Model and workspace policy controls expose one small, mouse-optional interface. */
export class RuntimeControls {
  readonly modelText: TextRenderable
  readonly accessText: TextRenderable
  readonly contextText: TextRenderable
  readonly menuRoot: BoxRenderable
  private readonly menu: PickerMenu<Choice>
  private kind: Choice["kind"] | null = null
  private model: string
  private modelPreset: string
  private modelPresets: Array<{ name: string; model: string }>
  private canUseFullAccess: boolean
  private controlsLoaded = false
  private controlsLoadedAt = 0
  private controlsPromise: Promise<void> | null = null
  private scope: WorkspaceScopePayload

  constructor(
    private readonly renderer: CliRenderer,
    private theme: RuntimeControlsTheme,
    private readonly options: RuntimeControlsOptions,
  ) {
    this.model = options.model
    this.modelPreset = options.modelPreset
    this.modelPresets = [{ name: options.modelPreset, model: options.model }]
    this.scope = {
      project_path: options.workspace,
      access_mode: options.access.toLocaleLowerCase().includes("full") ? "full" : "restricted",
    }
    this.canUseFullAccess = this.scope.access_mode === "full"
    this.menu = new PickerMenu<Choice>(renderer, theme, {
      id: "nanobot-tui-runtime-menu",
      maxWidth: 64,
      searchText: (choice) => `${choice.label} ${choice.detail}`,
      render: (choice) => `${choice.label}${choice.detail ? `  ${choice.detail}` : ""}`,
      onSelect: (choice) => this.apply(choice),
    })
    this.menuRoot = this.menu.root
    this.modelText = this.controlText(renderer, "model", () => void this.openModel())
    this.accessText = this.controlText(renderer, "access", () => void this.openAccess())
    this.contextText = new TextRenderable(renderer, {
      id: "nanobot-tui-context-text",
      content: "",
      height: 1,
      flexShrink: 0,
      fg: theme.faint,
      selectable: false,
    })
    this.render()
  }

  get visible(): boolean {
    return this.menu.visible
  }

  get workspaceScope(): WorkspaceScopePayload {
    return this.scope
  }

  updateModel(model: string, preset: string): void {
    this.model = model
    this.modelPreset = preset
    this.render()
  }

  updateContext(text: string): void {
    this.contextText.content = text
  }

  /** Warm the small settings payload while the user is reading the first frame. */
  preload(): void {
    void this.load().catch(() => {})
  }

  useApiConnection(apiUrl: string, apiToken: string): void {
    this.options.apiUrl = apiUrl
    this.options.apiToken = apiToken
    this.controlsLoaded = false
    this.controlsLoadedAt = 0
    this.preload()
  }

  updateWorkspaceScope(scope: WorkspaceScopePayload): void {
    this.scope = scope
    this.render()
  }

  resize(width: number): void {
    this.accessText.visible = width >= 58
    this.contextText.visible = width >= 96
  }

  choose(): boolean {
    const choice = this.menu.current()
    if (!choice) return false
    this.apply(choice)
    return true
  }

  handleKey(key: KeyEvent): boolean {
    if (!this.visible) return false
    if (!key.ctrl && !key.meta && (key.name === "up" || key.name === "down")) {
      this.menu.move(key.name === "up" ? -1 : 1)
    } else if (key.name === "escape") {
      this.hide()
    } else {
      return false
    }
    key.preventDefault()
    return true
  }

  hide(): void {
    if (!this.visible) return
    this.kind = null
    this.menu.hide()
    this.renderColors()
    this.options.onVisibilityChange(false)
  }

  setTheme(theme: RuntimeControlsTheme): void {
    this.theme = theme
    this.menu.setTheme(theme)
    this.contextText.fg = theme.faint
    this.renderColors()
  }

  private controlText(
    renderer: CliRenderer,
    id: "model" | "access",
    open: () => void,
  ): TextRenderable {
    const text = new TextRenderable(renderer, {
      id: `nanobot-tui-${id}-text`,
      content: "",
      height: 1,
      flexShrink: id === "model" ? 1 : 0,
      fg: this.theme.muted,
      selectable: false,
      onMouseOver: () => { text.fg = this.theme.accent },
      onMouseOut: () => this.renderColors(),
      onMouseDown: (event) => {
        if (event.button !== 0) return
        event.preventDefault()
        event.stopPropagation()
        this.renderer.clearSelection()
        open()
      },
    })
    return text
  }

  private async load(force = false): Promise<void> {
    if (force && Date.now() - this.controlsLoadedAt >= CONTROLS_CACHE_MS) {
      this.controlsLoaded = false
    }
    if (this.controlsLoaded) return
    if (this.controlsPromise) return this.controlsPromise
    if (!this.options.apiUrl || !this.options.apiToken) {
      this.controlsLoaded = true
      this.controlsLoadedAt = Date.now()
      return
    }
    this.controlsPromise = (async () => {
      const controls = await fetchRuntimeControls(
        this.options.apiUrl,
        this.options.apiToken,
        this.options.reauthenticateApi,
      )
      const presets = new Map(controls.modelPresets.map((preset) => [
        preset.name.toLocaleLowerCase(),
        preset,
      ]))
      if (!presets.has(this.modelPreset.toLocaleLowerCase())) {
        presets.set(this.modelPreset.toLocaleLowerCase(), {
          name: this.modelPreset,
          model: this.model,
        })
      }
      this.modelPresets = [...presets.values()]
      this.canUseFullAccess = controls.canUseFullAccess
      this.controlsLoaded = true
      this.controlsLoadedAt = Date.now()
    })().finally(() => { this.controlsPromise = null })
    return this.controlsPromise
  }

  private async openModel(): Promise<void> {
    if (!this.canOpen()) return
    try {
      await this.load(true)
    } catch (error) {
      this.options.onStatus(error instanceof Error ? error.message : String(error))
      return
    }
    this.options.beforeOpen()
    this.kind = "model"
    const choices: Choice[] = this.modelPresets
      .map((preset) => ({
        kind: "model" as const,
        name: preset.name,
        label: `${preset.name === this.modelPreset ? "●" : " "} ${preset.name}`,
        detail: preset.model,
      }))
      .sort((left, right) => Number(right.name === this.modelPreset)
        - Number(left.name === this.modelPreset))
    this.menu.show(choices, "", rendererLimit(this.renderer.height))
    this.opened()
  }

  private async openAccess(): Promise<void> {
    if (!this.canOpen()) return
    try {
      await Promise.all([this.load(true), this.options.refreshScope()])
    } catch (error) {
      this.options.onStatus(error instanceof Error ? error.message : String(error))
      return
    }
    this.options.beforeOpen()
    this.kind = "access"
    const choices: Choice[] = [{
      kind: "access",
      mode: "restricted",
      label: `${this.scope.access_mode === "restricted" ? "●" : " "} Workspace access`,
      detail: "project files only",
    }]
    if (this.canUseFullAccess || this.scope.access_mode === "full") choices.push({
      kind: "access",
      mode: "full",
      label: `${this.scope.access_mode === "full" ? "●" : " "} Full access`,
      detail: "all local files and tools",
    })
    choices.sort((left, right) => Number(
      right.kind === "access" && right.mode === this.scope.access_mode,
    ) - Number(left.kind === "access" && left.mode === this.scope.access_mode))
    this.menu.show(choices)
    this.opened()
  }

  private canOpen(): boolean {
    if (this.options.available()) return true
    this.options.onStatus("Preparing chat…")
    return false
  }

  private opened(): void {
    this.renderColors()
    this.options.onVisibilityChange(true)
  }

  private apply(choice: Choice): void {
    this.hide()
    if (choice.kind === "model") {
      if (choice.name !== this.modelPreset) this.options.onModel(choice.name)
      return
    }
    if (choice.mode === this.scope.access_mode) return
    if (choice.mode === "full" && !this.canUseFullAccess) {
      this.options.onStatus("Full access is only available from a trusted local gateway")
      return
    }
    this.options.onAccess({
      ...this.scope,
      access_mode: choice.mode,
      restrict_to_workspace: choice.mode === "restricted",
    })
  }

  private render(): void {
    this.modelText.content = `${this.modelPreset} ▾`
    const access = this.scope.access_mode === "full" ? "full access" : "workspace access"
    this.accessText.content = `     ${access} ▾`
    this.renderColors()
  }

  private renderColors(): void {
    this.modelText.fg = this.kind === "model" && this.visible
      ? this.theme.accent
      : this.theme.muted
    this.accessText.fg = (
      (this.kind === "access" && this.visible) || this.scope.access_mode === "full"
    ) ? this.theme.accent : this.theme.muted
  }
}

function rendererLimit(height: number): number {
  return height >= 20 ? 8 : 4
}
