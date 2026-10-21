import { DOMParser, XMLSerializer } from "@xmldom/xmldom"
import type { Font } from "fontkit"
import { OUTPUT_LIMIT } from "./types"

export interface DiagramFonts { regular: Font; bold: Font; mono: Font }

export function shapeDiagramText(fonts: DiagramFonts, text: string, size: number, style: number) {
  if (!Number.isFinite(size) || size <= 0 || size > 200 || (style & ~7)) throw new Error("Unsupported diagram font style")
  const face = style & 1 ? fonts.bold : style & 4 ? fonts.mono : fonts.regular
  for (const char of text) {
    if (!face.hasGlyphForCodePoint(char.codePointAt(0)!)) throw new Error("Diagram font missing glyph")
  }
  const run = face.layout(text)
  const scale = size / face.unitsPerEm
  return { run, scale, width: run.positions.reduce((width, position) => width + position.xAdvance, 0) * scale }
}

/** Use the measured glyphs for every label, including synthetic CJK italics.
 * Rasterizers then receive paths only and never reinterpret the font files. */
export function outlineDiagramText(svg: string, fonts: DiagramFonts): string {
  const document = new DOMParser().parseFromString(svg, "image/svg+xml")
  const property = (element: Element, name: string, fallback = ""): string => {
    let current: Node | null = element
    while (current?.nodeType === 1) {
      const owner = current as Element
      // The image policy has already parsed and serialized these declarations.
      const inline = (owner.getAttribute("style") || "").split(";").find(value => value.startsWith(`${name}:`))
      if (inline) return inline.slice(name.length + 1)
      if (owner.hasAttribute(name)) return owner.getAttribute(name)!
      current = owner.parentNode
    }
    return fallback
  }
  const style = (element: Element) => {
    const weight = property(element, "font-weight")
    const family = property(element, "font-family").replace(/^["']|["']$/g, "")
    return (/^(?:bold|bolder)$/.test(weight) || Number(weight) >= 600 ? 1 : 0)
      | (/^(?:italic|oblique)$/.test(property(element, "font-style")) ? 2 : 0)
      | (family === fonts.mono.familyName ? 4 : 0)
  }
  const coordinate = (element: Element, name: string, fallback: number) => element.hasAttribute(name) ? Number(element.getAttribute(name)) : fallback
  const group = (element: Element) => {
    const result = document.createElementNS("http://www.w3.org/2000/svg", "g")
    for (const attribute of Array.from(element.attributes)) {
      if (!["x", "y", "text-anchor"].includes(attribute.name)) result.setAttribute(attribute.name, attribute.value)
    }
    return result
  }
  type Run = ReturnType<typeof shapeDiagramText> & { owner: Element; italic: boolean }
  type Chunk = { x: number; y: number; anchor: string; runs: Run[] }
  let bytes = 0
  for (const text of Array.from(document.getElementsByTagName("text"))) {
    const chunks: Chunk[] = []
    let chunk: Chunk = { x: coordinate(text, "x", 0), y: coordinate(text, "y", 0), anchor: property(text, "text-anchor", "start"), runs: [] }
    const collect = (owner: Element) => {
      if (owner !== text && (owner.hasAttribute("x") || owner.hasAttribute("y"))) {
        if (chunk.runs.length) chunks.push(chunk)
        chunk = { x: coordinate(owner, "x", chunk.x), y: coordinate(owner, "y", chunk.y), anchor: property(owner, "text-anchor", "start"), runs: [] }
      }
      for (const child of Array.from(owner.childNodes)) {
        if (child.nodeType === 1) collect(child as Element)
        else if (child.nodeType === 3 || child.nodeType === 4) {
          const flags = style(owner)
          const size = Number.parseFloat(property(owner, "font-size", "16"))
          chunk.runs.push({ ...shapeDiagramText(fonts, child.textContent || "", size, flags), owner, italic: !!(flags & 2) })
        }
      }
    }
    collect(text)
    if (chunk.runs.length) chunks.push(chunk)
    const outlined = group(text)
    for (const chunk of chunks) {
      const width = chunk.runs.reduce((sum, run) => sum + run.width, 0)
      let x = chunk.x - (chunk.anchor === "middle" ? width / 2 : chunk.anchor === "end" ? width : 0)
      for (const run of chunk.runs) {
        let parent = outlined
        const ancestors: Element[] = []
        for (let owner = run.owner; owner !== text; owner = owner.parentNode as Element) ancestors.unshift(owner)
        for (const owner of ancestors) {
          const nested = group(owner)
          parent.appendChild(nested)
          parent = nested
        }
        let advanceX = 0, advanceY = 0
        for (let i = 0; i < run.run.glyphs.length; i++) {
          const glyph = run.run.glyphs[i]!, position = run.run.positions[i]!
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path")
          const data = glyph.path.toSVG()
          bytes += Buffer.byteLength(data) + 200
          if (bytes > OUTPUT_LIMIT) throw new Error("Diagram vector limit")
          path.setAttribute("d", data)
          const shear = run.italic ? Math.tan(14 * Math.PI / 180) : 0
          path.setAttribute("transform", `translate(${x} ${chunk.y}) matrix(${run.scale} 0 ${shear * run.scale} ${-run.scale} 0 0) translate(${advanceX + position.xOffset} ${advanceY + position.yOffset})`)
          path.setAttribute("vector-effect", "non-scaling-stroke")
          parent.appendChild(path)
          advanceX += position.xAdvance
          advanceY += position.yAdvance
        }
        x += run.width
      }
    }
    text.parentNode!.replaceChild(outlined, text)
  }
  const result = new XMLSerializer().serializeToString(document)
  if (Buffer.byteLength(result) > OUTPUT_LIMIT) throw new Error("Diagram vector limit")
  return result
}
