import { describe, expect, test } from "bun:test"

import { contextualFooterHints, footerHints } from "./footer-hints"

const theme = {
  accent: "#EF8E30",
  danger: "#F87171",
  muted: "#A1A1AA",
  separator: "#71717A",
}

describe("footerHints", () => {
  test("separates normal and destructive shortcuts semantically", () => {
    const result = footerHints([
      { key: "enter", label: "steer" },
      { key: "ctrl+c", label: "stop", tone: "danger" },
    ], theme)

    expect(result.chunks.map(({ text }) => text).join("")).toBe("enter steer · ctrl+c stop")
    expect(result.chunks[0]?.fg?.toInts().slice(0, 3)).toEqual([239, 142, 48])
    expect(result.chunks[3]?.fg?.toInts().slice(0, 3)).toEqual([248, 113, 113])
  })

  test("adapts the active-turn vocabulary to available width", () => {
    const wide = contextualFooterHints("active", 100, theme, "linux")
    const compact = contextualFooterHints("active", 72, theme, "linux")

    expect(wide.chunks.map(({ text }) => text).join(""))
      .toBe("enter steer · tab queue · alt+↑ edit · ctrl+c stop")
    expect(compact.chunks.map(({ text }) => text).join(""))
      .toBe("enter steer · tab queue · ctrl+c stop")
  })

  test("uses the native Option symbol on macOS", () => {
    const result = contextualFooterHints("active", 100, theme, "darwin")

    expect(result.chunks.map(({ text }) => text).join(""))
      .toBe("enter steer · tab queue · ⌥↑ edit · ctrl+c stop")
  })

  test("advertises Shift+Enter when the terminal can distinguish it", () => {
    const enhanced = contextualFooterHints("ready", 80, theme, "darwin", true)
    const legacy = contextualFooterHints("ready", 80, theme, "darwin", false)

    expect(enhanced.chunks.map(({ text }) => text).join(""))
      .toBe("enter send · shift+enter newline · ctrl+c stop")
    expect(legacy.chunks.map(({ text }) => text).join(""))
      .toBe("enter send · ctrl+j newline · ctrl+c stop")
  })
})
