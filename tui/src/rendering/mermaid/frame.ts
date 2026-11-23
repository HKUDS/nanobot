import { DOMParser, XMLSerializer } from "@xmldom/xmldom"
import type { DiagramFrame } from "./types"

/** Transform only the already validated image document; frame jobs need no CSS resolver. */
export function frameDiagramSvg(svg: string, frame: DiagramFrame): string {
  const document = new DOMParser().parseFromString(svg, "image/svg+xml")
  const root = document.documentElement
  root.setAttribute("width", String(frame.width))
  root.setAttribute("height", String(frame.height))
  root.setAttribute("viewBox", `${frame.x} ${frame.y} ${frame.viewWidth} ${frame.viewHeight}`)
  return new XMLSerializer().serializeToString(document)
}
