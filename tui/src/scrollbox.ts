import type { ScrollBoxRenderable } from "@opentui/core"

/** Keep scrolling functional without drawing terminal-dependent block glyphs. */
export function hideScrollbars(scrollBox: ScrollBoxRenderable): void {
  for (const bar of [scrollBox.verticalScrollBar, scrollBox.horizontalScrollBar]) {
    // ScrollBar can make itself visible again when content starts overflowing.
    // Hiding its children as well keeps embedded terminals deterministic.
    bar.visible = false
    bar.showArrows = false
    bar.slider.visible = false
    bar.startArrow.visible = false
    bar.endArrow.visible = false
  }
}
