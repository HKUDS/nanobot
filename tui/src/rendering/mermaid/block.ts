import {
  BoxRenderable, CodeRenderable, ImageRenderable, NativeImage, TextRenderable,
  resolveImageRenderProtocol, type CliRenderer,
} from "@opentui/core"
import type { DiagramJobs } from "./jobs"
import { diagramLayoutKey, type DiagramLayoutLease, type DiagramLayouts } from "./cache"
import { diagramFrame } from "./geometry"
import type { DiagramFrame, DiagramInput, DiagramLayout } from "./types"

export interface DiagramOwner {
  jobs: DiagramJobs
  layouts: DiagramLayouts
  colors(): DiagramInput["colors"]
  inViewport(block: MermaidBlock): boolean
  readonly viewerOpen: boolean
  restorePreviews(): void
  reserve(pixels: number): boolean
  release(pixels: number): void
  open(block: MermaidBlock): void
  released(block: MermaidBlock): void
  removed(block: MermaidBlock): void
}

export function diagramProtocol(renderer: CliRenderer): "kitty" | "sixel" | null {
  const protocol = resolveImageRenderProtocol("auto", renderer.capabilities, renderer.resolution !== null)
  return protocol === "blocks" ? null : protocol
}

export function diagramCellSize(renderer: CliRenderer): { width: number; height: number } {
  return renderer.resolution
    ? { width: renderer.resolution.width / renderer.width, height: renderer.resolution.height / renderer.height }
    : { width: 10, height: 20 }
}

/** Source remains authoritative; the native image exists only while this block is on screen. */
export class MermaidBlock extends BoxRenderable {
  private readonly label: TextRenderable
  private readonly sourceCode: CodeRenderable
  private picture: ImageRenderable | null = null
  private native: NativeImage | null = null
  private request: AbortController | null = null
  private releaseWorker: (() => void) | null = null
  private pixels = 0
  private layoutLease: DiagramLayoutLease | null = null
  private frame: DiagramFrame | null = null
  private failure = ""
  private renderedGeometry = ""
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
  get renderedLayout(): DiagramLayout | null { return this.layoutLease?.layout ?? null }

  borrowImage(frame: DiagramFrame): NativeImage | null {
    return this.native && this.frame && Object.entries(this.frame).every(([key, value]) => frame[key as keyof DiagramFrame] === value)
      ? this.native.retain() : null
  }

  borrowLayout(): DiagramLayoutLease | null {
    return this.layoutLease ? this.owner.layouts.acquire(this.layoutLease.key) : null
  }

  private layoutFor(width: number): DiagramLayout | null {
    const key = diagramLayoutKey({ source: this.source, width, colors: this.owner.colors() })
    if (this.layoutLease?.key !== key) {
      this.layoutLease?.release()
      this.layoutLease = this.owner.layouts.acquire(key)
    }
    return this.renderedLayout
  }

  private keepLayout(layout: DiagramLayout, width: number): DiagramLayout {
    if (this.renderedLayout === layout) return layout
    this.layoutLease?.release()
    this.layoutLease = null
    this.layoutLease = this.owner.layouts.store(diagramLayoutKey({ source: this.source, width, colors: this.owner.colors() }), layout)
    return this.layoutLease.layout
  }

  suspend(): void { this.releaseImage() }

  hidePreview(): void {
    this.request?.abort()
    this.request = null
    this.setWorkerDemand(false)
    if (!this.picture?.visible) return
    this.previewHeight = this.height
    this.minHeight = this.previewHeight
    this.picture.visible = false
  }

  restorePreview(): void {
    if (!this.picture) return
    this.picture.visible = true
    this.minHeight = 0
    this.setWorkerDemand(this.owner.inViewport(this))
  }

  private setWorkerDemand(wanted: boolean): void {
    if (wanted) this.releaseWorker ??= this.owner.jobs.retainWorker()
    else { this.releaseWorker?.(); this.releaseWorker = null }
  }

  invalidate(): void {
    this.failure = ""
    this.releaseImage()
    this.label.fg = this.owner.colors().muted
    this.sourceCode.visible = true
    this.requestRender()
  }

  private sync(): void {
    if (!this.state.settled) return
    if (this.owner.viewerOpen) { this.hidePreview(); return }
    if (this.picture && !this.picture.visible) {
      this.picture.visible = true
      this.minHeight = 0
    }
    const wanted = this.owner.inViewport(this)
    const protocol = diagramProtocol(this.renderer)
    const cells = diagramCellSize(this.renderer)
    const width = Math.max(1, Math.floor(this.width)) * cells.width
    const geometry = `${width}:${cells.width}:${cells.height}`
    if (this.renderedGeometry && this.renderedGeometry !== geometry) {
      this.failure = ""
      this.releaseFrame()
    }
    this.wanted = wanted
    if (!protocol) {
      this.releaseImage()
      this.sourceCode.visible = true
      this.label.content = "Mermaid · no image protocol · Ctrl+G source"
      return
    }
    if (!wanted) { this.releaseImage(); return }
    if (this.native || this.request || this.failure) return
    this.renderedGeometry = geometry
    const request = new AbortController()
    this.request = request
    this.setWorkerDemand(true)
    this.label.content = "Mermaid · rendering… · Ctrl+G view / cancel"
    const viewport = { width, height: 24 * cells.height, cellWidth: cells.width, cellHeight: cells.height }
    const layout = this.layoutFor(width)
    const work = layout
      ? this.owner.jobs.raster(layout, diagramFrame(layout, viewport), request.signal).then(image => ({ ...image, layout }))
      : this.owner.jobs.render({ source: this.source, width, scale: 1, viewport, colors: this.owner.colors() }, request.signal)
    void work.then(image => {
        if (this.isDestroyed || this.request !== request || !this.wanted) return
        this.keepLayout(image.layout, width)
        const pixels = image.width * image.height
        if (!this.owner.reserve(pixels)) throw new Error("Visible image memory limit")
        this.pixels = pixels
        try { this.native = NativeImage.decode(image.png) }
        catch (error) { this.owner.release(this.pixels); this.pixels = 0; throw error }
        this.frame = diagramFrame(image.layout, viewport)
        this.picture = new ImageRenderable(this.renderer, {
          id: `${this.id}-image`, source: this.native,
          width: Math.round(image.width / cells.width), height: Math.round(image.height / cells.height),
          alignSelf: "center", fit: "fill", protocol,
          onError: () => this.fail("Terminal image load failed"),
        })
        this.add(this.picture)
        this.sourceCode.visible = false
        this.minHeight = 0
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

  private fail(message: string): void {
    this.failure = message
    this.releaseImage()
    this.sourceCode.visible = true
    // Only controlled renderer errors, not untrusted Mermaid source, enter the status line.
    this.label.content = `Mermaid · ${message.replace(/[\r\n\x00-\x1f]/g, " ").slice(0, 120)} · Ctrl+G source`
  }

  private releaseImage(): void {
    this.setWorkerDemand(false)
    this.releaseFrame()
    this.layoutLease?.release()
    this.layoutLease = null
  }

  private releaseFrame(): void {
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
    this.frame = null
    if (this.pixels) this.owner.release(this.pixels)
    this.pixels = 0
    // Keep the known preview footprint while culled; scrolling back does not jump.
    if (this.previewHeight && !this.sourceCode.visible) {
      this.minHeight = this.previewHeight
    }
    this.owner.released(this)
  }

  protected override destroySelf(): void {
    this.releaseImage()
    this.owner.removed(this)
    super.destroySelf()
  }
}
