import { describe, expect, test } from "bun:test"

import { contextualFooterHints, footerHints, footerTelemetry } from "./footer-hints"

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

  test("keeps passive composer modes free of permanent instructions", () => {
    const ready = contextualFooterHints("ready", 100, theme, "linux")
    const active = contextualFooterHints("active", 100, theme, "darwin")

    expect(ready.chunks).toHaveLength(0)
    expect(active.chunks).toHaveLength(0)
  })

  test("shows the measured request's context-window percentage", () => {
    const result = footerTelemetry(14_700, 128_000, theme)

    expect(result.chunks.map(({ text }) => text).join(""))
      .toBe("11% context")
    expect(result.chunks[0]?.fg?.toInts().slice(0, 3)).toEqual([239, 142, 48])
  })

  test("clamps usage above the configured window", () => {
    const result = footerTelemetry(220_000, 200_000, theme)

    expect(result.chunks.map(({ text }) => text).join(""))
      .toBe("100% context")
  })

  test("does not guess without measured context or a valid window", () => {
    const missingContext = footerTelemetry(null, 128_000, theme)
    const missingWindow = footerTelemetry(1000, null, theme)
    const invalidWindow = footerTelemetry(1000, 0, theme)

    expect(missingContext.chunks).toHaveLength(0)
    expect(missingWindow.chunks).toHaveLength(0)
    expect(invalidWindow.chunks).toHaveLength(0)
  })
})
