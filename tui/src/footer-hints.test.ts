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

  test("shows measured throughput, cache ratio, token counts, and TTFT", () => {
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
      .toBe("50 tok/s · cache 75% · ↑1.2k ↓80 · TTFT 250ms")
    expect(result.chunks[0]?.fg?.toInts().slice(0, 3)).toEqual([239, 142, 48])
  })

  test("degrades telemetry instead of guessing missing provider metrics", () => {
    const compact = footerTelemetry({
      prompt_tokens: 1000,
      completion_tokens: 20,
      cached_tokens: 0,
    }, 60, theme)
    const unsupported = footerTelemetry({ prompt_tokens: 1000, completion_tokens: 20 }, 60, theme)

    expect(compact.chunks.map(({ text }) => text).join("")).toBe("cache 0%")
    expect(unsupported.chunks).toHaveLength(0)
  })
})
