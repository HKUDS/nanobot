import {
  BoxRenderable, ImageRenderable, NativeImage, RGBA, ScrollBoxRenderable, TextRenderable,
  type CliRenderer, type KeyEvent,
} from "@opentui/core"
import { copyWithSystemClipboard } from "../../platform/clipboard"
import { hideScrollbars } from "../scrollbox"
import { diagramProtocol, type DiagramOwner, type MermaidBlock } from "./block"

/** A read-only overlay: opening it never edits the composer or transcript scroll. */
export class DiagramViewer {
  readonly root: BoxRenderable
  private readonly header: TextRenderable
  private readonly note: TextRenderable
  private readonly viewport: BoxRenderable
  private readonly sourceScroll: ScrollBoxRenderable
  private readonly sourceText: TextRenderable
  private readonly footer: TextRenderable
  private items: MermaidBlock[] = []
  private selected = 0
  private request: AbortController | null = null
  private original: NativeImage | null = null
  private picture: ImageRenderable | null = null
  private pixels = 0
  private zoom = 1
  private panX = 0
  private panY = 0
  private sourceMode = false
  private revision = 0
  onClose?: () => void

  constructor(private readonly renderer: CliRenderer, private readonly owner: DiagramOwner) {
    const colors = owner.colors()
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-diagrams", position: "absolute", top: 0, left: 0,
      width: "100%", height: "100%", zIndex: 110, padding: 1,
      flexDirection: "column", backgroundColor: RGBA.defaultBackground(), visible: false,
    })
    this.header = new TextRenderable(renderer, { id: "diagrams-header", content: "Mermaid", fg: colors.foreground, height: 1, flexShrink: 0 })
    this.note = new TextRenderable(renderer, { id: "diagrams-note", content: "", fg: colors.muted, minHeight: 1, flexShrink: 0, width: "100%" })
    this.viewport = new BoxRenderable(renderer, {
      id: "diagrams-viewport", width: "100%", minHeight: 0, flexGrow: 1,
      overflow: "hidden", alignItems: "center", justifyContent: "center",
      onSizeChange: () => this.paint(),
    })
    this.sourceScroll = new ScrollBoxRenderable(renderer, {
      id: "diagrams-source-scroll", width: "100%", minHeight: 0, flexGrow: 1,
      scrollY: true, scrollX: false, visible: false,
      verticalScrollbarOptions: { visible: false }, horizontalScrollbarOptions: { visible: false },
    })
    hideScrollbars(this.sourceScroll)
    this.sourceText = new TextRenderable(renderer, { id: "diagrams-source", content: "", fg: colors.foreground, width: "100%", wrapMode: "char", selectable: true })
    this.sourceScroll.add(this.sourceText)
    this.footer = new TextRenderable(renderer, { id: "diagrams-footer", content: "", fg: colors.muted, minHeight: 1, width: "100%", flexShrink: 0 })
    this.root.add(this.header)
    this.root.add(this.note)
    this.root.add(this.viewport)
    this.root.add(this.sourceScroll)
    this.root.add(this.footer)
  }

  get visible(): boolean { return this.root.visible }

  show(items: MermaidBlock[], selected: number): void {
    this.items = items
    this.selected = selected
    this.root.visible = true
    this.load()
  }

  hide(): void {
    this.root.visible = false
    this.revision++
    this.releaseImage()
    this.items = []
    this.sourceText.content = ""
  }

  setTheme(): void {
    const colors = this.owner.colors()
    this.header.fg = colors.foreground
    this.sourceText.fg = colors.foreground
    this.note.fg = this.footer.fg = colors.muted
    if (this.visible) this.load()
  }

  handleKey(key: KeyEvent): void {
    if (key.name === "escape" || (!key.ctrl && key.name === "q")) { this.hide(); this.onClose?.(); return }
    if (key.ctrl || key.meta) return
    if (key.name === "c") { void this.copy(); return }
    if (key.name === "s") { this.sourceMode = !this.sourceMode; this.showMode(); return }
    if (key.name === "x") {
      this.releaseImage()
      this.sourceMode = true
      this.note.content = "Rendering cancelled · original source retained · r retry"
      this.showMode()
      return
    }
    if (key.name === "r") { this.load(); return }
    if (this.items.length && (key.name === "[" || key.name === "]")) {
      this.selected = (this.selected + (key.name === "[" ? -1 : 1) + this.items.length) % this.items.length
      this.load()
      return
    }
    if (this.sourceMode) {
      if (["up", "down", "pageup", "pagedown", "home", "end"].includes(key.name)) this.sourceScroll.handleKeyPress(key)
      return
    }
    if (key.sequence === "+" || key.name === "=" || key.name === "+") this.zoom = Math.min(8, this.zoom * 1.5)
    else if (key.name === "-") this.zoom = Math.max(0.5, this.zoom / 1.5)
    else if (key.name === "0") { this.zoom = 1; this.panX = this.panY = 0 }
    else if (key.name === "left") this.panX -= 0.12
    else if (key.name === "right") this.panX += 0.12
    else if (key.name === "up") this.panY -= 0.12
    else if (key.name === "down") this.panY += 0.12
    else return
    this.paint()
  }

  private load(): void {
    const item = this.items[this.selected]
    this.revision++
    this.releaseImage()
    this.zoom = 1
    this.panX = this.panY = 0
    this.sourceMode = false
    this.header.content = this.items.length ? `Mermaid ${this.selected + 1}/${this.items.length}` : "Mermaid"
    this.sourceText.content = item?.source || "No Mermaid diagrams in this conversation."
    this.sourceScroll.scrollTo(0)
    this.showMode()
    if (!item) { this.sourceMode = true; this.showMode(); this.note.content = ""; return }
    if (!item.settled) {
      this.sourceMode = true
      this.note.content = "Replying · original source (r refresh after completion)"
      this.showMode()
      return
    }
    if (!diagramProtocol(this.renderer)) {
      this.sourceMode = true
      this.note.content = "No image protocol · original Mermaid source"
      this.showMode()
      return
    }
    this.note.content = "Rendering… · x cancel · s source"
    const request = new AbortController()
    this.request = request
    void this.owner.jobs.render({ source: item.source, width: Math.min(1600, Math.max(100, this.renderer.width * 10)), scale: 2, colors: this.owner.colors() }, request.signal)
      .then(image => {
        if (this.request !== request || !this.visible) return
        // Reserve both the original and one worst-case extracted view.
        const pixels = image.width * image.height * 2
        if (!this.owner.reserve(pixels)) throw new Error("Visible image memory limit")
        this.pixels = pixels
        this.original = NativeImage.decode(image.png)
        this.paint()
      })
      .catch(error => {
        if (this.request !== request || request.signal.aborted || !this.visible) return
        this.fail(error instanceof Error ? error.message : "Rendering failed")
      })
      .finally(() => { if (this.request === request) this.request = null })
  }

  private showMode(): void {
    this.sourceScroll.visible = this.sourceMode
    this.viewport.visible = !this.sourceMode
    this.footer.content = !this.items.length ? "q/esc back" : this.renderer.width < 85
      ? "+/- zoom · arrows pan · s source · c copy · [] diagram · q/esc back"
      : "+/- zoom   arrows pan   0 fit   s source/image   c copy source   [/] diagram   x cancel   q/esc back"
    this.root.requestRender()
  }

  private paint(): void {
    const original = this.original
    const protocol = diagramProtocol(this.renderer)
    if (!original || !protocol || !this.visible || this.viewport.width < 1 || this.viewport.height < 1) return
    const cellWidth = this.renderer.resolution ? this.renderer.resolution.width / this.renderer.width : 10
    const cellHeight = this.renderer.resolution ? this.renderer.resolution.height / this.renderer.height : 20
    const width = this.viewport.width * cellWidth
    const height = this.viewport.height * cellHeight
    const fit = Math.min(width / original.width, height / original.height)
    const scale = fit * this.zoom
    const cropWidth = Math.min(original.width, Math.max(1, Math.floor(width / scale)))
    const cropHeight = Math.min(original.height, Math.max(1, Math.floor(height / scale)))
    this.panX = Math.max(0, Math.min(1, this.panX))
    this.panY = Math.max(0, Math.min(1, this.panY))
    const crop = original.extract({
      left: Math.round((original.width - cropWidth) * this.panX), top: Math.round((original.height - cropHeight) * this.panY),
      width: cropWidth, height: cropHeight,
    })
    if (this.picture) { this.viewport.remove(this.picture); this.picture.destroyRecursively() }
    this.picture = new ImageRenderable(this.renderer, {
      id: "diagrams-picture", source: crop,
      width: Math.max(1, Math.min(this.viewport.width, Math.ceil(cropWidth * scale / cellWidth))),
      height: Math.max(1, Math.min(this.viewport.height, Math.ceil(cropHeight * scale / cellHeight))),
      protocol, fit: "fill", onError: () => this.fail("Terminal image load failed"),
    })
    crop.dispose()
    this.viewport.add(this.picture)
    this.note.content = `${Math.round(this.zoom * 100)}% fit · ${original.width}×${original.height}px · pan ${Math.round(this.panX * 100)}%,${Math.round(this.panY * 100)}%`
  }

  private fail(message: string): void {
    this.releaseImage()
    this.sourceMode = true
    this.note.content = `Mermaid · ${message.replace(/[\r\n\x00-\x1f]/g, " ").slice(0, 120)} · original source`
    this.showMode()
  }

  private async copy(): Promise<void> {
    const item = this.items[this.selected]
    if (!item) return
    const revision = this.revision
    try {
      if (!this.renderer.copyToClipboardOSC52(item.source)) await copyWithSystemClipboard(item.source)
      if (revision === this.revision && this.visible) this.note.content = "Source copied"
    } catch {
      if (revision === this.revision && this.visible) this.note.content = "Copy unavailable · source remains selectable"
    }
  }

  private releaseImage(): void {
    this.request?.abort()
    this.request = null
    if (this.picture) { this.viewport.remove(this.picture); this.picture.destroyRecursively(); this.picture = null }
    this.original?.dispose()
    this.original = null
    if (this.pixels) this.owner.release(this.pixels)
    this.pixels = 0
  }
}
