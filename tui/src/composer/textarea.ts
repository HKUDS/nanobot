import { TextareaRenderable, type OptimizedBuffer } from "@opentui/core"

export class ComposerTextarea extends TextareaRenderable {
  override renderCursor(buffer: OptimizedBuffer): void {
    if (this.focused && this.showCursor) {
      const { visualCol, visualRow } = this.visualCursor
      const x = this.x + visualCol
      const y = this.y + visualRow
      if (x >= 0 && x < buffer.width && y >= 0 && y < buffer.height) {
        const index = y * buffer.width + x
        const { char, fg } = buffer.buffers
        // OpenTUI clears unused editor cells with a white foreground. Hosts
        // that draw a cursor by reversing the cell use that color as its fill.
        if (char[index] === 32) fg.set(this.textColor.buffer, index * 4)
      }
    }
    super.renderCursor(buffer)
  }
}
