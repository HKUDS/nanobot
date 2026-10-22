import { DiagramImageError } from "./svg-image";
import type { DiagramInput } from "./types";

// Pele's public TextMeasurer contract; the engine import stays in the Worker entry.
export function canvasTextMeasurer(fonts: DiagramInput["fonts"]): {
  width(text: string, size: number, style: number): number;
} {
  let context: OffscreenCanvasRenderingContext2D | null = null;
  try {
    if (typeof OffscreenCanvas !== "undefined") context = new OffscreenCanvas(1, 1).getContext("2d");
  } catch { /* Capability failure, never Pele's approximate metrics fallback. */ }
  if (!context) throw new DiagramImageError("capability");
  const canvas = context;
  return {
    width(text, size, style) {
      if (!Number.isFinite(size) || size <= 0 || size > 200 || (style & ~7) !== 0) {
        throw new DiagramImageError("unsupported");
      }
      const font = `${style & 2 ? "italic " : ""}${style & 1 ? "bold " : ""}${size}px ${style & 4 ? fonts.mono : fonts.sans}`;
      // Reset first so an invalid canvas font cannot reuse the preceding measurement.
      canvas.font = "1px serif";
      canvas.font = font;
      if (canvas.font === "1px serif") throw new DiagramImageError("capability");
      const width = canvas.measureText(text).width;
      if (!Number.isFinite(width) || width < 0) throw new DiagramImageError("capability");
      return width;
    },
  };
}
