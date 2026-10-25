import { createHash } from "node:crypto"
import { DIAGRAM_FONT_SIZE, type DiagramInput, type DiagramLayout } from "./types"

export function diagramLayoutKey(input: Pick<DiagramInput, "source" | "width" | "fonts" | "colors">): string {
  const { source, width, fonts, colors } = input
  return createHash("sha256").update(JSON.stringify([
    source, width, DIAGRAM_FONT_SIZE,
    fonts ? [fonts.regular.path, fonts.regular.postscriptName, fonts.bold.path, fonts.bold.postscriptName, fonts.mono.path, fonts.mono.postscriptName] : null,
    colors.foreground, colors.muted, colors.surface, colors.border, colors.accent,
  ])).digest("hex")
}

export interface DiagramLayoutLease {
  key: string
  layout: DiagramLayout
  release(): void
}

type Entry = { layout: DiagramLayout; bytes: number; users: number }

/** Visible pins and offscreen LRU entries share one transcript's vector budget. */
export class DiagramLayouts {
  private readonly entries = new Map<string, Entry>()
  private bytes = 0

  constructor(private readonly limit = 4_000_000) {}

  get retainedBytes(): number { return this.bytes }

  acquire(key: string): DiagramLayoutLease | null {
    const entry = this.entries.get(key)
    return entry ? this.pin(key, entry) : null
  }

  store(key: string, layout: DiagramLayout): DiagramLayoutLease {
    const existing = this.acquire(key)
    if (existing) return existing
    const bytes = Buffer.byteLength(layout.svg)
    if (bytes > this.limit) throw new Error("Visible diagram layout limit")
    for (const [oldKey, entry] of this.entries) {
      if (this.bytes + bytes <= this.limit) break
      if (entry.users) continue
      this.entries.delete(oldKey)
      this.bytes -= entry.bytes
    }
    if (this.bytes + bytes > this.limit) throw new Error("Visible diagram layout limit")
    const entry = { layout, bytes, users: 0 }
    this.entries.set(key, entry)
    this.bytes += bytes
    return this.pin(key, entry)
  }

  clear(): void { this.entries.clear(); this.bytes = 0 }

  private pin(key: string, entry: Entry): DiagramLayoutLease {
    this.entries.delete(key)
    this.entries.set(key, entry)
    entry.users++
    let released = false
    return { key, layout: entry.layout, release: () => {
      if (released) return
      released = true
      entry.users--
    } }
  }
}
