export const SOURCE_LIMIT = 50_000
export const OUTPUT_LIMIT = 2_000_000
export const MAX_PIXELS = 8_000_000
export const MAX_DIMENSION = 8192
export const DIAGRAM_FONT_SIZE = 16

export interface DiagramFont {
  path: string
  postscriptName: string
}

export interface DiagramInput {
  source: string
  width: number
  scale: number
  viewport?: { height: number; cellWidth: number; cellHeight: number }
  fonts?: { regular: DiagramFont; bold: DiagramFont; mono: DiagramFont }
  colors: { foreground: string; muted: string; surface: string; border: string; accent: string }
}

export interface DiagramImage {
  png: Uint8Array
  width: number
  height: number
}

export interface DiagramLayout {
  svg: string
  width: number
  height: number
}

export interface DiagramFrame {
  width: number
  height: number
  x: number
  y: number
  viewWidth: number
  viewHeight: number
}

export interface DiagramAsset extends DiagramImage {
  layout: DiagramLayout
}

export type DiagramWork = { kind: "render"; input: DiagramInput }
  | { kind: "raster"; layout: DiagramLayout; frame: DiagramFrame }
