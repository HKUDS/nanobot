import { CodeRenderable, type CliRenderer, type ScrollBoxRenderable } from "@opentui/core"
import { MermaidBlock, type DiagramOwner } from "./block"
import { DiagramJobs } from "./jobs"
import type { DiagramInput } from "./types"
import { DiagramViewer } from "./viewer"

const RETAINED_PIXEL_LIMIT = 16_000_000

/** One transcript owns all render jobs and native images, including its overlay. */
export class TranscriptDiagrams implements DiagramOwner {
  readonly jobs = new DiagramJobs()
  readonly viewer: DiagramViewer
  onOpen?: () => void
  private readonly blocks = new Set<MermaidBlock>()
  private retainedPixels = 0

  constructor(
    private readonly renderer: CliRenderer,
    private readonly viewport: ScrollBoxRenderable,
    private palette: DiagramInput["colors"],
  ) {
    this.viewer = new DiagramViewer(renderer, this)
  }

  colors(): DiagramInput["colors"] { return this.palette }

  create(source: string, code: CodeRenderable, state: { settled: boolean }, id: string): MermaidBlock {
    const block = new MermaidBlock(this.renderer, this, source, code, state, id)
    this.blocks.add(block)
    return block
  }

  inViewport(block: MermaidBlock): boolean {
    const view = this.viewport.viewport
    return !this.viewer.visible && block.width > 0 && view.height > 0
      && block.screenY < view.screenY + view.height && block.screenY + block.height > view.screenY
  }

  reserve(pixels: number): boolean {
    if (pixels + this.retainedPixels > RETAINED_PIXEL_LIMIT) return false
    this.retainedPixels += pixels
    return true
  }

  release(pixels: number): void { this.retainedPixels -= pixels }
  removed(block: MermaidBlock): void { this.blocks.delete(block) }

  open(block?: MermaidBlock): void {
    const blocks = [...this.blocks].filter(item => !item.isDestroyed).sort((a, b) => a.screenY - b.screenY)
    const selected = block ? blocks.indexOf(block) : blocks.indexOf(blocks.filter(item => this.inViewport(item)).at(-1)!)
    // Release preview resources before the viewer reserves its original/crop pair.
    for (const item of blocks) item.suspend()
    this.viewer.show(blocks, selected >= 0 ? selected : Math.max(0, blocks.length - 1))
    this.onOpen?.()
  }

  setTheme(colors: DiagramInput["colors"]): void {
    this.palette = colors
    for (const block of this.blocks) block.invalidate()
    this.viewer.setTheme()
  }

  reset(): void {
    this.viewer.hide()
    for (const block of this.blocks) block.suspend()
  }

  destroy(): void {
    this.reset()
    this.jobs.dispose()
    if (!this.viewer.root.isDestroyed) this.viewer.root.destroyRecursively()
  }
}
