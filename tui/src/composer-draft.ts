import type { OutboundMedia } from "./protocol"

const LARGE_PASTE_CHARS = 1_000
const LARGE_PASTE_LINES = 10
export const MAX_DRAFT_IMAGES = 4

export interface PasteInsertion {
  text: string
  compacted: boolean
  description: string
}

export interface DraftEditReconciliation {
  value: string
  cursor: number
  removedImages: string[]
}

const IMAGE_EXTENSIONS = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
} as const

interface DraftImage {
  dataUrl: string
  mimeType: keyof typeof IMAGE_EXTENSIONS
}

/** Keeps large pasted text and image payloads out of the editable composer surface. */
export class ComposerDraft {
  private readonly pastes = new Map<string, string>()
  private readonly images = new Map<string, OutboundMedia>()

  get imageCount(): number {
    return this.images.size
  }

  paste(value: string): PasteInsertion {
    const text = value.replace(/\r\n/gu, "\n").replace(/\r/gu, "\n")
    const lines = text.split("\n").length
    if (text.length < LARGE_PASTE_CHARS && lines < LARGE_PASTE_LINES) {
      return { text, compacted: false, description: "" }
    }

    const description = lines > 1 ? `${lines} lines` : `${text.length} characters`
    const base = `[Pasted ${description}]`
    let label = base
    for (let index = 2; this.pastes.has(label); index += 1) label = `${base.slice(0, -1)} #${index}]`
    this.pastes.set(label, text)
    return { text: `${label} `, compacted: true, description }
  }

  private imageLabelInUse(label: string, visible: string): boolean {
    if (this.images.has(label) || visible.includes(label)) return true
    for (const content of this.pastes.values()) {
      if (content.includes(label)) return true
    }
    return false
  }

  private nextImageIndex(visible: string): number {
    let index = 1
    while (this.imageLabelInUse(`[Image #${index}]`, visible)) index += 1
    return index
  }

  image(image: DraftImage, visible = ""): PasteInsertion | null {
    if (this.images.size >= MAX_DRAFT_IMAGES) return null
    const index = this.nextImageIndex(visible)
    const label = `[Image #${index}]`
    this.images.set(label, {
      data_url: image.dataUrl,
      name: `clipboard-image-${index}.${IMAGE_EXTENSIONS[image.mimeType]}`,
    })
    return { text: `${label} `, compacted: true, description: label.slice(1, -1) }
  }

  private expandPastes(visible: string): string {
    let expanded = visible
    for (const [label, content] of this.pastes) expanded = expanded.split(label).join(content)
    return expanded
  }

  private labelOccurrences(content: string, label: string): number {
    return content.split(label).length - 1
  }

  imagePlaceholderRanges(visible: string): Array<{ start: number; end: number }> {
    const ranges: Array<{ start: number; end: number }> = []
    for (const label of this.images.keys()) {
      let start = visible.indexOf(label)
      while (start >= 0) {
        ranges.push({ start, end: start + label.length })
        start = visible.indexOf(label, start + label.length)
      }
    }
    return ranges.sort((left, right) => left.start - right.start)
  }

  snapImageCursor(visible: string, cursor: number, previousCursor: number): number {
    const range = this.imagePlaceholderRanges(visible)
      .find(({ start, end }) => cursor > start && cursor < end)
    if (!range) return cursor
    if (previousCursor <= range.start) return range.end
    if (previousCursor >= range.end) return range.start
    return cursor - range.start < range.end - cursor ? range.start : range.end
  }

  moveImageCursor(visible: string, cursor: number, direction: -1 | 1): number | null {
    const range = this.imagePlaceholderRanges(visible).find(({ start, end }) => (
      direction < 0
        ? cursor > start && cursor <= end
        : cursor >= start && cursor < end
    ))
    if (!range) return null
    return direction < 0 ? range.start : range.end
  }

  reconcileImageEdit(
    previous: string,
    value: string,
    cursor: number,
  ): DraftEditReconciliation {
    let oldStart = 0
    const sharedLength = Math.min(previous.length, value.length)
    while (oldStart < sharedLength && previous[oldStart] === value[oldStart]) oldStart += 1

    let oldEnd = previous.length
    let newEnd = value.length
    while (
      oldEnd > oldStart
      && newEnd > oldStart
      && previous[oldEnd - 1] === value[newEnd - 1]
    ) {
      oldEnd -= 1
      newEnd -= 1
    }

    const ranges = this.imagePlaceholderRanges(previous).filter(({ start, end }) => (
      oldStart === oldEnd
        ? oldStart > start && oldStart < end
        : oldStart < end && oldEnd > start
    ))
    if (!ranges.length) return { value, cursor, removedImages: [] }

    const replaceStart = Math.min(oldStart, ...ranges.map((range) => range.start))
    const replaceEnd = Math.max(oldEnd, ...ranges.map((range) => range.end))
    const inserted = value.slice(oldStart, newEnd)
    const reconciled = previous.slice(0, replaceStart) + inserted + previous.slice(replaceEnd)
    const missing = [...this.images.keys()].filter((label) => !reconciled.includes(label))
    for (const label of missing) this.images.delete(label)
    return {
      value: reconciled,
      cursor: replaceStart + inserted.length,
      removedImages: missing.map((label) => label.slice(1, -1)),
    }
  }

  hasImageLabelConflict(visible: string): boolean {
    const expanded = this.expandPastes(visible)
    return [...this.images.keys()]
      .some((label) => this.labelOccurrences(expanded, label) !== 1)
  }

  expand(visible: string): string {
    let expanded = this.expandPastes(visible)
    for (const label of this.images.keys()) {
      if (this.labelOccurrences(expanded, label) === 1) expanded = expanded.replace(label, "")
    }
    return expanded
  }

  display(visible: string): string {
    return this.expandPastes(visible)
  }

  media(visible: string): OutboundMedia[] {
    return [...this.images]
      .filter(([label]) => visible.includes(label))
      .sort(([left], [right]) => visible.indexOf(left) - visible.indexOf(right))
      .map(([, media]) => media)
  }

  prune(visible: string): void {
    for (const label of this.pastes.keys()) {
      if (!visible.includes(label)) this.pastes.delete(label)
    }
    for (const label of this.images.keys()) {
      if (!visible.includes(label)) this.images.delete(label)
    }
  }

  clear(): void {
    this.pastes.clear()
    this.images.clear()
  }
}
