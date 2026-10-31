import { existsSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { create, type Font } from "fontkit"
import { detectType, load, render } from "pele/lazy"
import { diagramFrame } from "./geometry"
import { resolveDiagramSvg } from "./svg"
import { rasterDiagram } from "./raster"
import { outlineDiagramText, shapeDiagramText } from "./text"
import { macOSFonts } from "./macos-fonts"
import { DIAGRAM_FONT_SIZE, MAX_DIMENSION, MAX_PIXELS, OUTPUT_LIMIT, SOURCE_LIMIT, type DiagramAsset, type DiagramFont, type DiagramInput, type DiagramLayout } from "./types"

type FontFile = ReturnType<typeof create>
function systemFonts(file: (path: string) => FontFile): NonNullable<DiagramInput["fonts"]> {
  if (process.platform === "darwin") return macOSFonts()
  const windows = join(process.env.SystemRoot || "C:/Windows", "Fonts")
  const candidates = process.platform === "win32"
    ? [[join(windows, "msyh.ttc"), join(windows, "msyhbd.ttc")]]
    : [["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
      ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]]
  for (const [regularPath, boldPath] of candidates) {
    if (!regularPath || !boldPath || !existsSync(regularPath) || !existsSync(boldPath)) continue
    const select = (path: string, bold: boolean): DiagramFont => {
      const opened = file(path)
      const faces = "fonts" in opened ? opened.fonts : [opened]
      const font = faces.find(face => /(?:YaHei$|CJKsc-Regular$|SC-Regular$|DejaVuSans$)/i.test(face.postscriptName) && !bold)
        ?? faces.find(face => bold && /(?:YaHei-Bold$|CJKsc-Bold$|SC-Semibold$|DejaVuSans-Bold$)/i.test(face.postscriptName))
        ?? faces[0]!
      return { path, postscriptName: font.postscriptName }
    }
    const regular = select(regularPath, false)
    // Use the same CJK-capable family for monospace labels rather than let resvg
    // silently pick a different system font for glyphs fontkit did not measure.
    return { regular, bold: select(boldPath, true), mono: regular }
  }
  throw new Error("Diagram font unavailable (install Noto Sans CJK)")
}

type FontSet = { selected: NonNullable<DiagramInput["fonts"]>; regular: Font; bold: Font; mono: Font; system: boolean }
let activeFonts: FontSet | undefined
function getFonts(selected?: DiagramInput["fonts"]): FontSet {
  if (activeFonts && (selected ? JSON.stringify(selected) === JSON.stringify(activeFonts.selected) : activeFonts.system)) return activeFonts
  const files = new Map<string, FontFile>()
  const file = (path: string) => {
    if (!files.has(path)) files.set(path, create(readFileSync(path)))
    return files.get(path)!
  }
  const faces = selected ?? systemFonts(file)
  const font = (face: DiagramFont): Font => {
    const loaded = file(face.path)
    const available = "fonts" in loaded ? loaded.fonts : [loaded]
    // Fontkit returns an ASCII Buffer for some legacy macOS name-table records.
    const result = available.find(font => String(font.postscriptName) === face.postscriptName)
    if (!result) throw new Error(`Diagram font unavailable: ${face.postscriptName}`)
    return result
  }
  activeFonts = { selected: faces, regular: font(faces.regular), bold: font(faces.bold), mono: font(faces.mono), system: !selected }
  return activeFonts
}

// Only the isolated child imports this module. Measurement and outlines share one font set.
export async function renderDiagram(input: DiagramInput): Promise<DiagramAsset> {
  if (Buffer.byteLength(input.source) > SOURCE_LIMIT || !Number.isFinite(input.width)
    || input.width < 1 || input.width > MAX_DIMENSION || !Number.isFinite(input.scale)
    || input.scale < 1 || input.scale > 2) throw new Error("Diagram input limit")
  if (!await load(detectType(input.source))) throw new Error("Unsupported Mermaid diagram")
  const fonts = getFonts(input.fonts)
  const result = render(input.source, {
    fontFamily: fonts.regular.familyName, fontFamilyMono: fonts.mono.familyName, fontSize: DIAGRAM_FONT_SIZE,
    maxWidth: input.width, responsive: false, links: false, images: false,
    limit: SOURCE_LIMIT, outputLimit: OUTPUT_LIMIT, maxEdges: 500,
    measurer: { width: (text, size, style) => shapeDiagramText(fonts, text, size, style).width },
  })
  if (!Number.isFinite(result.width) || !Number.isFinite(result.height) || result.width < 1 || result.height < 1
    || result.width > MAX_DIMENSION || result.height > MAX_DIMENSION || result.width * result.height > MAX_PIXELS) throw new Error("Diagram pixel limit")
  const resolved = resolveDiagramSvg(result.svg, input, fonts.regular.familyName, fonts.mono.familyName)
  const layout: DiagramLayout = { svg: outlineDiagramText(resolved, fonts), width: result.width, height: result.height }
  const frame = input.viewport ? diagramFrame(layout, { width: input.width, ...input.viewport }) : {
    width: Math.ceil(result.width * input.scale), height: Math.ceil(result.height * input.scale),
    x: 0, y: 0, viewWidth: result.width, viewHeight: result.height,
  }
  return { ...rasterDiagram(layout, frame), layout }
}
