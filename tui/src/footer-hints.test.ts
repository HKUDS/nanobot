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

  test("groups the cache ratio with input telemetry", () => {
    const result = footerTelemetry({
      prompt_tokens: 1200,
      completion_tokens: 80,
      cached_tokens: 900,
      generation_ms: 1600,
      measured_completion_tokens: 80,
      ttft_ms: 500,
      timed_requests: 2,
    }, 120, theme)

    expect(result.chunks.map(({ text }) => text).join(""))
      .toBe("50 tok/s · 1.2K in (75% cached) · 80 out")
    expect(result.chunks[0]?.fg?.toInts().slice(0, 3)).toEqual([239, 142, 48])
  })

  test("uses familiar compact units for large token counts", () => {
    const result = footerTelemetry({
      prompt_tokens: 4_500_000,
      completion_tokens: 19_000,
      cached_tokens: 3_600_000,
      generation_ms: 135_714,
      measured_completion_tokens: 19_000,
    }, 120, theme)

    expect(result.chunks.map(({ text }) => text).join(""))
      .toBe("140 tok/s · 4.5M in (80% cached) · 19K out")
  })

  test("degrades telemetry instead of guessing missing provider metrics", () => {
    const compact = footerTelemetry({
      prompt_tokens: 1000,
      completion_tokens: 20,
      cached_tokens: 0,
    }, 60, theme)
    const unsupported = footerTelemetry({ prompt_tokens: 1000, completion_tokens: 20 }, 60, theme)

    expect(compact.chunks.map(({ text }) => text).join("")).toBe("0% cached")
    expect(unsupported.chunks).toHaveLength(0)
  })
})
