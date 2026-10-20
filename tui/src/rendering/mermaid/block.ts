import {
  BoxRenderable, CodeRenderable, ImageRenderable, NativeImage, TextRenderable,
  resolveImageRenderProtocol, type CliRenderer,
} from "@opentui/core"
import type { DiagramJobs } from "./jobs"
import type { DiagramInput } from "./types"

export interface DiagramOwner {
  jobs: DiagramJobs
  colors(): DiagramInput["colors"]
  inViewport(block: MermaidBlock): boolean
  reserve(pixels: number): boolean
  release(pixels: number): void
  open(block: MermaidBlock): void
  removed(block: MermaidBlock): void
}

export function diagramProtocol(renderer: CliRenderer): "kitty" | "sixel" | null {
  const protocol = resolveImageRenderProtocol("auto", renderer.capabilities, renderer.resolution !== null)
  return protocol === "blocks" ? null : protocol
}

/** Source remains authoritative; the native image exists only while this block is on screen. */
export class MermaidBlock extends BoxRenderable {
  private readonly label: TextRenderable
  private readonly sourceCode: CodeRenderable
  private picture: ImageRenderable | null = null
  private native: NativeImage | null = null
  private request: AbortController | null = null
  private pixels = 0
  private failure = ""
  private renderedWidth = 0
  private aspect = 0
  private previewHeight = 0
  private wanted = false

  constructor(
    private readonly renderer: CliRenderer,
    private readonly owner: DiagramOwner,
    readonly source: string,
    code: CodeRenderable,
    private readonly state: { settled: boolean },
    id: string,
  ) {
    super(renderer, { id, width: "100%", minWidth: 0, flexDirection: "column", flexShrink: 0 })
    this.sourceCode = code
    this.label = new TextRenderable(renderer, {
      id: `${id}-label`, content: "Mermaid · source while replying", fg: owner.colors().muted,
      width: "100%", minHeight: 1, flexShrink: 0,
      onMouseDown: () => owner.open(this),
    })
    this.add(this.label)
    this.add(code)
    this.onLifecyclePass = () => this.sync()
  }

  get settled(): boolean { return this.state.settled }

  suspend(): void { this.releaseImage() }

  invalidate(): void {
    this.failure = ""
    this.releaseImage()
    this.label.fg = this.owner.colors().muted
    this.sourceCode.visible = true
    this.requestRender()
  }

  private sync(): void {
    if (!this.state.settled) return
    const wanted = this.owner.inViewport(this)
    const protocol = diagramProtocol(this.renderer)
    const width = Math.max(1, Math.floor(this.width))
    if (this.renderedWidth && this.renderedWidth !== width) {
      this.failure = ""
      this.releaseImage()
    }
    this.wanted = wanted
    if (!protocol) {
      this.releaseImage()
      this.sourceCode.visible = true
      this.label.content = "Mermaid · no image protocol · Ctrl+G source"
      return
    }
    if (!wanted) { this.releaseImage(); return }
    if (this.native) {
      this.resizePicture()
      return
    }
    if (this.request || this.failure) return
    this.renderedWidth = width
    const request = new AbortController()
    this.request = request
    this.label.content = "Mermaid · rendering… · Ctrl+G view / cancel"
    void this.owner.jobs.render({ source: this.source, width: Math.min(1600, width * 10), scale: 2, colors: this.owner.colors() }, request.signal)
      .then(image => {
        if (this.isDestroyed || this.request !== request || !this.wanted) return
        const pixels = image.width * image.height
        if (!this.owner.reserve(pixels)) throw new Error("Visible image memory limit")
        this.pixels = pixels
        try { this.native = NativeImage.decode(image.png) }
        catch (error) { this.owner.release(this.pixels); this.pixels = 0; throw error }
        this.aspect = image.height / image.width
        this.picture = new ImageRenderable(this.renderer, {
          id: `${this.id}-image`, source: this.native, width: "100%", height: 1,
          fit: "fit", protocol,
          onError: () => this.fail("Terminal image load failed"),
        })
        this.add(this.picture)
        this.sourceCode.visible = false
        this.minHeight = 0
        this.resizePicture()
        this.label.content = "Mermaid · Ctrl+G view / source / copy"
      })
      .catch(error => {
        if (this.isDestroyed || this.request !== request || request.signal.aborted) return
        this.fail(error instanceof Error ? error.message : "Rendering failed")
      })
      .finally(() => {
        if (this.request === request) this.request = null
        if (!this.isDestroyed) this.requestRender()
      })
  }

  private resizePicture(): void {
    if (!this.picture) return
    this.picture.height = Math.max(2, Math.min(24, Math.ceil(this.width * this.aspect / this.picture.cellAspectRatio)))
  }

  private fail(message: string): void {
    this.failure = message
    this.releaseImage()
    this.sourceCode.visible = true
    // Only controlled renderer errors, not untrusted Mermaid source, enter the status line.
    this.label.content = `Mermaid · ${message.replace(/[\r\n\x00-\x1f]/g, " ").slice(0, 120)} · Ctrl+G source`
  }

  private releaseImage(): void {
    this.request?.abort()
    this.request = null
    if (this.picture) this.previewHeight = Math.max(this.height, this.picture.height + this.label.height)
    if (this.picture) {
      this.remove(this.picture)
      this.picture.destroyRecursively()
      this.picture = null
    }
    this.native?.dispose()
    this.native = null
    if (this.pixels) this.owner.release(this.pixels)
    this.pixels = 0
    // Keep the known preview footprint while culled; scrolling back does not jump.
    if (this.aspect && !this.sourceCode.visible) {
      this.minHeight = this.previewHeight
    }
  }

  protected override destroySelf(): void {
    this.releaseImage()
    this.owner.removed(this)
    super.destroySelf()
  }
}
