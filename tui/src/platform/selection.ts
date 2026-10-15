import {
  EditBufferRenderable,
  TextBufferRenderable,
  TextTableRenderable,
  type RGBA,
  type Selection,
} from "@opentui/core"

export interface SelectionColors {
  background: RGBA
  foreground: RGBA
}

export function applySelectionColors(selection: Selection, colors: SelectionColors): void {
  for (const renderable of selection.selectedRenderables) {
    if (renderable.isDestroyed) continue
    if (renderable instanceof TextBufferRenderable || renderable instanceof EditBufferRenderable) {
      renderable.selectionBg = colors.background
      renderable.selectionFg = colors.foreground
    } else if (renderable instanceof TextTableRenderable) {
      // OpenTUI 0.5.11 exposes table selection colors only at construction.
      // Update its retained palette without replacing streaming table cells.
      const table = renderable as unknown as { _selectionBg?: RGBA; _selectionFg?: RGBA }
      if (table._selectionBg === colors.background && table._selectionFg === colors.foreground) continue
      table._selectionBg = colors.background
      table._selectionFg = colors.foreground
      renderable.onSelectionChanged(selection)
    }
  }
}
