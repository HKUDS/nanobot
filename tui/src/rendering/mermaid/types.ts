export const SOURCE_LIMIT = 50_000
export const OUTPUT_LIMIT = 2_000_000
export const MAX_PIXELS = 8_000_000
export const MAX_DIMENSION = 8192

export interface DiagramFont {
  path: string
  postscriptName: string
}

export interface DiagramInput {
  source: string
  width: number
  scale: number
  fonts?: { regular: DiagramFont; bold: DiagramFont; mono: DiagramFont }
  colors: { foreground: string; muted: string; surface: string; border: string; accent: string }
}

export interface DiagramImage {
  png: Uint8Array
  width: number
  height: number
}
