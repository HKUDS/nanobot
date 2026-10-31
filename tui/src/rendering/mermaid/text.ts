import { DOMParser, XMLSerializer } from "@xmldom/xmldom"
import type { Font } from "fontkit"
import { DIAGRAM_FONT_SIZE, OUTPUT_LIMIT } from "./types"

const SMALLER_RATIO = 1.2

export interface DiagramFonts { regular: Font; bold: Font; mono: Font }

export function shapeDiagramText(fonts: DiagramFonts, text: string, size: number, style: number) {
  if (!Number.isFinite(size) || size <= 0 || size > 200 || (style & ~63)) throw new Error("Unsupported diagram font style")
  const face = style & 1 ? fonts.bold : style & 4 ? fonts.mono : fonts.regular
  for (const char of text) {
    if (!face.hasGlyphForCodePoint(char.codePointAt(0)!)) throw new Error("Diagram font missing glyph")
  }
  const run = face.layout(text)
  // Pele measures sub/sup at the CSS "smaller" ratio but passes the original size.
  const scale = (style & 24 ? size / SMALLER_RATIO : size) / face.unitsPerEm
  return { run, face, scale, width: run.positions.reduce((width, position) => width + position.xAdvance, 0) * scale }
}

/** Use the measured glyphs for every label, including synthetic CJK italics.
 * Rasterizers then receive paths only and never reinterpret the font files. */
export function outlineDiagramText(svg: string, fonts: DiagramFonts): string {
  const document = new DOMParser().parseFromString(svg, "image/svg+xml")
  const declaration = (owner: Element, name: string): string | undefined => {
    // The image policy has already parsed and serialized these declarations.
    const inline = (owner.getAttribute("style") || "").split(";").find(value => value.startsWith(`${name}:`))
    if (inline) return inline.slice(name.length + 1)
    return owner.hasAttribute(name) ? owner.getAttribute(name)! : undefined
  }
  const property = (element: Element, name: string, fallback = ""): string => {
    let current: Node | null = element
    while (current?.nodeType === 1) {
      const value = declaration(current as Element, name)
      if (value !== undefined) return value
      current = current.parentNode
    }
    return fallback
  }
  const sizes = new Map<Element, number>()
  const fontSize = (element: Element): number => {
    const cached = sizes.get(element)
    if (cached !== undefined) return cached
    const value = declaration(element, "font-size")
    const inherited = () => element.parentNode?.nodeType === 1 ? fontSize(element.parentNode as Element) : DIAGRAM_FONT_SIZE
    const size = value === undefined ? inherited() : value === "smaller" ? inherited() / SMALLER_RATIO : Number.parseFloat(value)
    sizes.set(element, size)
    return size
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
  type Run = ReturnType<typeof shapeDiagramText> & { owner: Element; italic: boolean; baseline: number; underline: boolean }
  type Chunk = { x: number; y: number; anchor: string; runs: Run[] }
  let bytes = 0
  const appendPath = (parent: Element, data: string, transform?: string) => {
    bytes += Buffer.byteLength(data) + 200
    if (bytes > OUTPUT_LIMIT) throw new Error("Diagram vector limit")
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path")
    path.setAttribute("d", data)
    if (transform) path.setAttribute("transform", transform)
    path.setAttribute("vector-effect", "non-scaling-stroke")
    parent.appendChild(path)
  }
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
          // SVG has already expressed the reduced size; do not apply the script flags twice.
          const shaped = shapeDiagramText(fonts, child.textContent || "", fontSize(owner), flags)
          const shift = property(owner, "baseline-shift")
          const metrics = shaped.face["OS/2"]
          const baseline = shift === "sub" ? (metrics?.ySubscriptYOffset ?? shaped.face.unitsPerEm * 0.2) * shaped.scale
            : shift === "super" ? -(metrics?.ySuperscriptYOffset ?? shaped.face.unitsPerEm * 0.4) * shaped.scale : 0
          chunk.runs.push({ ...shaped, owner, italic: !!(flags & 2), baseline, underline: property(owner, "text-decoration") === "underline" })
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
        const y = chunk.y + run.baseline
        if (run.underline && run.width > 0) {
          const thickness = run.face.underlineThickness * run.scale
          const top = y - run.face.underlinePosition * run.scale - thickness / 2
          appendPath(parent, `M${x} ${top}h${run.width}v${thickness}h${-run.width}Z`)
        }
        let advanceX = 0, advanceY = 0
        for (let i = 0; i < run.run.glyphs.length; i++) {
          const glyph = run.run.glyphs[i]!, position = run.run.positions[i]!
          const shear = run.italic ? Math.tan(14 * Math.PI / 180) : 0
          appendPath(parent, glyph.path.toSVG(), `translate(${x} ${y}) matrix(${run.scale} 0 ${shear * run.scale} ${-run.scale} 0 0) translate(${advanceX + position.xOffset} ${advanceY + position.yOffset})`)
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
