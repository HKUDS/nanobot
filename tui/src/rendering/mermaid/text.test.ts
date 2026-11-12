import { describe, expect, test } from "bun:test"
import { existsSync, readFileSync } from "node:fs"
import { create, type Font } from "fontkit"
import { DOMParser, XMLSerializer } from "@xmldom/xmldom"
import { Resvg } from "@resvg/resvg-js"
import { render } from "pele/lazy"
import { renderDiagram } from "./render"
import { rasterDiagram } from "./raster"
import { shapeDiagramText } from "./text"
import { resolveDiagramSvg } from "./svg"
import { DIAGRAM_FONT_SIZE, type DiagramInput } from "./types"

const paths = process.platform === "win32"
  ? ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/consola.ttf"]
  : process.platform === "darwin"
    ? ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Courier New.ttf"]
    : ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
const open = (path: string): Font => {
  const loaded = create(readFileSync(path))
  return "fonts" in loaded ? loaded.fonts[0]! : loaded
}
const fixture = paths.every(existsSync) ? paths.map(path => ({ path, font: open(path) })) : undefined
const select = (index: number) => ({ path: fixture![index]!.path, postscriptName: fixture![index]!.font.postscriptName })
const input = (): DiagramInput => ({
  source: "", width: 800, scale: 1,
  fonts: { regular: select(0), bold: select(1), mono: select(2) },
  colors: { foreground: "#202020", muted: "#666666", surface: "#eeeeee", border: "#888888", accent: "#3366cc" },
})
const document = (svg: string) => new DOMParser().parseFromString(svg, "image/svg+xml")
const glyphs = (svg: string) => Array.from(document(svg).getElementsByTagName("path")).flatMap(path => {
  const match = /^translate\(([^ ]+) ([^)]+)\) matrix\(([^ ]+) 0 ([^ ]+) ([^ ]+) 0 0\)/.exec(path.getAttribute("transform") || "")
  return match ? [{ path, x: Number(match[1]), y: Number(match[2]), scale: Number(match[3]), shear: Number(match[4]) }] : []
})
const source = (label: string) => `flowchart LR\n A["${label}"]`

describe.skipIf(!fixture)("Pele rich-text outlines with explicit local fonts", () => {
  test("subscript and superscript use measured smaller glyphs, shifted baselines and centered advances", async () => {
    const asset = await renderDiagram({ ...input(), source: source("H<sub>H</sub>H<sup>H</sup>H") })
    const regular = fixture![0]!.font
    const runs = glyphs(asset.layout.svg)
    expect(runs).toHaveLength(5)
    const [first, sub, middle, sup, last] = runs
    const scale = DIAGRAM_FONT_SIZE / regular.unitsPerEm
    const smaller = scale / 1.2
    const advance = regular.layout("H").positions[0]!.xAdvance
    for (const run of [first!, middle!, last!]) {
      expect(run.scale).toBeCloseTo(scale, 10)
      expect(run.y).toBeCloseTo(first!.y, 10)
    }
    for (const run of [sub!, sup!]) expect(run.scale).toBeCloseTo(smaller, 10)
    expect(sub!.y - first!.y).toBeCloseTo(regular["OS/2"].ySubscriptYOffset * smaller, 10)
    expect(sup!.y - first!.y).toBeCloseTo(-regular["OS/2"].ySuperscriptYOffset * smaller, 10)
    expect(sub!.y).toBeGreaterThan(first!.y)
    expect(sup!.y).toBeLessThan(first!.y)
    for (let i = 1; i < runs.length; i++) expect(runs[i]!.x - runs[i - 1]!.x).toBeCloseTo(advance * runs[i - 1]!.scale, 10)
    // Pele centers each node's label in its translated local group.
    expect((first!.x + last!.x + advance * scale) / 2).toBeCloseTo(0, 10)
    expect(asset.layout.svg).not.toContain("<text")
    expect(asset.layout.svg).not.toContain("NaN")
    expect(Array.from(asset.png.subarray(0, 8))).toEqual([137, 80, 78, 71, 13, 10, 26, 10])
  })

  test("underline becomes rasterized geometry while bold, mono, italic and scripted runs retain their fonts", async () => {
    const label = "<b>H<sub>H</sub></b><code>H</code><i>H</i>"
    const plain = await renderDiagram({ ...input(), source: source(label) })
    const underlined = await renderDiagram({ ...input(), source: source(`<u>${label}</u>`) })
    expect([underlined.width, underlined.height]).toEqual([plain.width, plain.height])
    expect(underlined.png).not.toEqual(plain.png)
    const runs = glyphs(underlined.layout.svg)
    expect(runs).toHaveLength(4)
    const regular = fixture![0]!.font, bold = fixture![1]!.font, mono = fixture![2]!.font
    const faces = [bold, bold, mono, regular]
    for (const [i, face] of faces.entries()) {
      expect(runs[i]!.path.getAttribute("d")).toBe(face.glyphForCodePoint(72).path.toSVG())
      expect(runs[i]!.scale).toBeCloseTo(DIAGRAM_FONT_SIZE / face.unitsPerEm / (i === 1 ? 1.2 : 1), 10)
    }
    expect(runs[3]!.shear / runs[3]!.scale).toBeCloseTo(Math.tan(14 * Math.PI / 180), 10)
    expect(runs[0]!.shear).toBe(0)
    const outlined = document(underlined.layout.svg)
    const decorations = Array.from(outlined.getElementsByTagName("g"))
      .filter(group => group.getAttribute("text-decoration") === "underline")
      .flatMap(group => Array.from(group.getElementsByTagName("path")).filter(path => !path.hasAttribute("transform")))
    expect(decorations).toHaveLength(4)
    for (const [i, decoration] of decorations.entries()) {
      const face = faces[i]!, run = runs[i]!
      const bounds = new Resvg(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200">${new XMLSerializer().serializeToString(decoration)}</svg>`, { font: { loadSystemFonts: false } }).getBBox()!
      const thickness = face.underlineThickness * run.scale
      expect(bounds.x).toBeCloseTo(run.x, 4)
      expect(bounds.y).toBeCloseTo(run.y - face.underlinePosition * run.scale - thickness / 2, 4)
      expect(bounds.width).toBeCloseTo(face.layout("H").positions[0]!.xAdvance * run.scale, 4)
      expect(bounds.height).toBeCloseTo(thickness, 4)
      decoration.parentNode!.removeChild(decoration)
    }
    const without = rasterDiagram({ ...underlined.layout, svg: new XMLSerializer().serializeToString(outlined) }, {
      width: underlined.width, height: underlined.height, x: 0, y: 0,
      viewWidth: underlined.layout.width, viewHeight: underlined.layout.height,
    })
    expect(without.png).toEqual(plain.png)
  })

  test("scripted and underlined outline pixels match Pele's native text with the same isolated font files", async () => {
    for (const label of ["H<sub>H</sub>H<sup>H</sup>H", "<u>g<sub>g</sub>g<sup>g</sup>g</u>"]) {
      const request = { ...input(), source: source(label) }
      const asset = await renderDiagram(request)
      const fonts = { regular: fixture![0]!.font, bold: fixture![1]!.font, mono: fixture![2]!.font }
      const result = render(request.source, {
        fontFamily: fonts.regular.familyName, fontFamilyMono: fonts.mono.familyName, fontSize: DIAGRAM_FONT_SIZE,
        maxWidth: request.width, responsive: false, links: false, images: false,
        measurer: { width: (text, size, style) => shapeDiagramText(fonts, text, size, style).width },
      })
      const native = new Resvg(resolveDiagramSvg(result.svg, request, fonts.regular.familyName, fonts.mono.familyName), {
        font: { loadSystemFonts: false, fontFiles: paths },
      }).render()
      const outlined = new Resvg(asset.layout.svg, { font: { loadSystemFonts: false } }).render()
      expect([outlined.width, outlined.height]).toEqual([native.width, native.height])
      const expected = native.pixels, actual = outlined.pixels
      let maxDelta = 0
      for (let i = 0; i < actual.length; i++) maxDelta = Math.max(maxDelta, Math.abs(actual[i]! - expected[i]!))
      expect(maxDelta).toBeLessThanOrEqual(1)
    }
  })
})
