/** Fit a column by terminal cells, preserving complete grapheme clusters. */
function fitColumn(text: string, width: number): string {
  if (Bun.stringWidth(text) <= width) return text
  let result = ""
  for (const { segment } of new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(text)) {
    if (Bun.stringWidth(result + segment) > width - 1) break
    result += segment
  }
  return result + "…"
}

export function configColumns(label: string, value: string, width: number): string {
  const available = Math.max(8, width)
  const labelWidth = Math.min(24, Math.floor((available - 3) / 2))
  const fitted = fitColumn(label, labelWidth)
  return fitted + " ".repeat(labelWidth - Bun.stringWidth(fitted) + 3)
    + fitColumn(value, available - labelWidth - 3)
}
