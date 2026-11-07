import { MAX_DIMENSION, MAX_PIXELS, OUTPUT_LIMIT, type DiagramFrame, type DiagramLayout } from "./types"

export function validateDiagramFrame(layout: DiagramLayout, frame: DiagramFrame): void {
  if (![frame.width, frame.height].every(value => Number.isSafeInteger(value) && value > 0 && value <= MAX_DIMENSION)
    || frame.width * frame.height > MAX_PIXELS || ![frame.x, frame.y, frame.viewWidth, frame.viewHeight].every(Number.isFinite)
    || frame.viewWidth <= 0 || frame.viewHeight <= 0 || Buffer.byteLength(layout.svg) > OUTPUT_LIMIT) throw new Error("Diagram pixel limit")
}

/** Rasterize the final cell footprint; padding never stretches the diagram itself. */
export function diagramFrame(
  natural: { width: number; height: number },
  viewport: { width: number; height: number; cellWidth: number; cellHeight: number },
  zoom = 1, panX = 0, panY = 0,
): DiagramFrame {
  const { width, height, cellWidth, cellHeight } = viewport
  if (![width, height, cellWidth, cellHeight, zoom].every(value => Number.isFinite(value) && value > 0)) throw new Error("Diagram viewport limit")
  const scale = Math.min(1, width / natural.width, height / natural.height) * zoom
  const pixelsWide = Math.round(Math.min(Math.round(width / cellWidth), Math.ceil(natural.width * scale / cellWidth)) * cellWidth)
  const pixelsHigh = Math.round(Math.min(Math.round(height / cellHeight), Math.ceil(natural.height * scale / cellHeight)) * cellHeight)
  const viewWidth = pixelsWide / scale, viewHeight = pixelsHigh / scale
  return {
    width: pixelsWide, height: pixelsHigh, viewWidth, viewHeight,
    x: viewWidth >= natural.width ? -(viewWidth - natural.width) / 2 : (natural.width - viewWidth) * panX,
    y: viewHeight >= natural.height ? -(viewHeight - natural.height) / 2 : (natural.height - viewHeight) * panY,
  }
}
