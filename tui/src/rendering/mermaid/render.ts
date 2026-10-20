import { existsSync } from "node:fs"
import { join } from "node:path"
import { openSync, type Font } from "fontkit"
import { Resvg } from "@resvg/resvg-js"
import { render } from "pele"
import { resolveDiagramSvg } from "./svg"
import { MAX_DIMENSION, MAX_PIXELS, OUTPUT_LIMIT, SOURCE_LIMIT, type DiagramFont, type DiagramImage, type DiagramInput } from "./types"

function loadFont(face: DiagramFont): Font {
  const loaded = openSync(face.path)
  const font = "fonts" in loaded ? loaded.fonts.find(font => font.postscriptName === face.postscriptName) : loaded
  if (!font || font.postscriptName !== face.postscriptName) throw new Error("Diagram font unavailable")
  return font
}

function systemFonts(): NonNullable<DiagramInput["fonts"]> {
  const windows = join(process.env.SystemRoot || "C:/Windows", "Fonts")
  const candidates = process.platform === "win32"
    ? [[join(windows, "msyh.ttc"), join(windows, "msyhbd.ttc")]]
    : process.platform === "darwin"
      ? [["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"]]
      : [["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]]
  for (const [regularPath, boldPath] of candidates) {
    if (!regularPath || !boldPath || !existsSync(regularPath) || !existsSync(boldPath)) continue
    const select = (path: string, bold: boolean): DiagramFont => {
      const opened = openSync(path)
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

// Called only in the native child process; no font parsing or raster work on the UI thread.
export function renderDiagram(input: DiagramInput): DiagramImage {
  if (Buffer.byteLength(input.source) > SOURCE_LIMIT || !Number.isFinite(input.width)
    || input.width < 1 || input.width > MAX_DIMENSION || !Number.isFinite(input.scale)
    || input.scale < 1 || input.scale > 2) throw new Error("Diagram input limit")
  const selected = input.fonts ?? systemFonts()
  const fonts = { regular: loadFont(selected.regular), bold: loadFont(selected.bold), mono: loadFont(selected.mono) }
  const result = render(input.source, {
    fontFamily: fonts.regular.familyName, fontFamilyMono: fonts.mono.familyName, fontSize: 18,
    maxWidth: input.width, responsive: false, links: false, images: false,
    limit: SOURCE_LIMIT, outputLimit: OUTPUT_LIMIT, maxEdges: 500,
    measurer: { width(text, size, style) {
      if (!Number.isFinite(size) || size <= 0 || size > 200 || (style & ~7) || (style & 2)) throw new Error("Unsupported diagram font style")
      const face = style & 1 ? fonts.bold : style & 4 ? fonts.mono : fonts.regular
      for (const char of text) {
        if (!face.hasGlyphForCodePoint(char.codePointAt(0)!)) throw new Error("Diagram font missing glyph")
      }
      return face.layout(text).positions.reduce((width, position) => width + position.xAdvance, 0) * size / face.unitsPerEm
    } },
  })
  const width = Math.ceil(result.width * input.scale)
  const height = Math.ceil(result.height * input.scale)
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 1 || height < 1
    || width > MAX_DIMENSION || height > MAX_DIMENSION || width * height > MAX_PIXELS) throw new Error("Diagram pixel limit")
  const svg = resolveDiagramSvg(result.svg, input, fonts.regular.familyName, fonts.mono.familyName)
  const raster = new Resvg(svg, {
    font: { loadSystemFonts: false, fontFiles: [...new Set(Object.values(selected).map(face => face.path))], defaultFontFamily: fonts.regular.familyName },
    fitTo: { mode: "zoom", value: input.scale },
  }).render()
  const png = raster.asPng()
  if (png.byteLength > OUTPUT_LIMIT) throw new Error("Diagram image limit")
  return { png: new Uint8Array(png), width: raster.width, height: raster.height }
}
