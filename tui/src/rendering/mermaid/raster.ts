import { Resvg } from "@resvg/resvg-js"
import { validateDiagramFrame } from "./geometry"
import { frameDiagramSvg } from "./frame"
import { OUTPUT_LIMIT, type DiagramFrame, type DiagramImage, type DiagramLayout } from "./types"

/** Initial and interactive frames rasterize the same measured glyph outlines, without font loading. */
export function rasterDiagram(layout: DiagramLayout, frame: DiagramFrame): DiagramImage {
  validateDiagramFrame(layout, frame)
  const raster = new Resvg(frameDiagramSvg(layout.svg, frame), { font: { loadSystemFonts: false } }).render()
  const png = raster.asPng()
  if (png.byteLength > OUTPUT_LIMIT) throw new Error("Diagram image limit")
  return { png, width: raster.width, height: raster.height }
}
