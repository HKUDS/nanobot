import { expect, test } from "bun:test"
import { DiagramLayouts, diagramLayoutKey } from "./cache"
import type { DiagramInput, DiagramLayout } from "./types"

const input: DiagramInput = {
  source: "graph TD\n A[中文] --> B", width: 800, scale: 1,
  colors: { foreground: "#111", muted: "#666", surface: "#eee", border: "#888", accent: "#36c" },
}
const layout = (text: string): DiagramLayout => ({ svg: `<svg>${text}</svg>`, width: 100, height: 50 })

test("layout identity includes source, physical width, fonts and palette, not raster geometry", () => {
  const key = diagramLayoutKey(input)
  const zoomed: DiagramInput = { ...input, scale: 4, viewport: { height: 720, cellWidth: 9, cellHeight: 24 } }
  expect(diagramLayoutKey(zoomed)).toBe(key)
  expect(diagramLayoutKey({ ...input, source: "graph TD\n B --> C" })).not.toBe(key)
  expect(diagramLayoutKey({ ...input, width: 799 })).not.toBe(key)
  expect(diagramLayoutKey({ ...input, colors: { ...input.colors, foreground: "#eee" } })).not.toBe(key)
  const font = { path: "font.ttf", postscriptName: "Font" }
  const withFonts = { ...input, fonts: { regular: font, bold: font, mono: font } }
  expect(diagramLayoutKey(withFonts)).not.toBe(key)
  expect(diagramLayoutKey({ ...withFonts, fonts: { ...withFonts.fonts, bold: { ...font, postscriptName: "Bold" } } })).not.toBe(diagramLayoutKey(withFonts))
})

test("offscreen layouts reuse one bounded LRU while visible pins cannot be evicted", () => {
  const first = layout("first"), second = layout("second"), third = layout("third")
  const cache = new DiagramLayouts(Buffer.byteLength(first.svg) + Buffer.byteLength(second.svg))
  const a = cache.store("a", first), b = cache.store("b", second)
  expect(() => cache.store("c", third)).toThrow("Visible diagram layout limit")
  a.release()
  b.release()
  const returned = cache.acquire("a")!
  expect(returned.layout).toBe(first)
  returned.release()
  const c = cache.store("c", third)
  expect(cache.acquire("b")).toBeNull()
  const pinned = cache.acquire("a")!
  expect(pinned.layout).toBe(first)
  expect(cache.retainedBytes).toBe(Buffer.byteLength(first.svg) + Buffer.byteLength(third.svg))
  pinned.release()
  pinned.release()
  c.release()
})

test("reset removes old layouts and releases cannot resurrect the previous cache", () => {
  const cache = new DiagramLayouts()
  const old = cache.store("diagram", layout("old"))
  old.release()
  cache.clear()
  const current = cache.store("diagram", layout("new"))
  old.release()
  expect(cache.acquire("diagram")!.layout).toBe(current.layout)
  expect(cache.retainedBytes).toBe(Buffer.byteLength(current.layout.svg))
  current.release()
  cache.clear()
  expect(cache.retainedBytes).toBe(0)
  expect(cache.acquire("diagram")).toBeNull()
})
