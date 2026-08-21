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

  test("shows the latest measured request instead of aggregate turn usage", () => {
    const result = footerTelemetry({
      prompt_tokens: 1_400_000,
      completion_tokens: 3200,
      cached_tokens: 1_330_000,
      generation_ms: 49_000,
      measured_completion_tokens: 3200,
      last_request_prompt_tokens: 148_000,
      last_request_completion_tokens: 400,
      last_request_cached_tokens: 140_600,
      last_request_provider_tokens: 148_400,
      last_request_generation_ms: 6154,
      last_request_measured_completion_tokens: 400,
      last_request_context_window_tokens: 300_000,
    }, 120, theme)

    expect(result.chunks.map(({ text }) => text).join(""))
      .toBe("65 tok/s · 148K/300K ctx (95% cached) · 400 out")
    expect(result.chunks[0]?.fg?.toInts().slice(0, 3)).toEqual([239, 142, 48])
  })

  test("keeps real context visible while compacting secondary metrics", () => {
    const usage = {
      last_request_prompt_tokens: 148_000,
      last_request_completion_tokens: 400,
      last_request_cached_tokens: 140_600,
      last_request_provider_tokens: 148_400,
      last_request_generation_ms: 6154,
      last_request_measured_completion_tokens: 400,
      last_request_context_window_tokens: 300_000,
    }

    const result = footerTelemetry(usage, 60, theme)

    expect(result.chunks.map(({ text }) => text).join(""))
      .toBe("65 tok/s · 148K/300K ctx")
  })

  test("does not present aggregate or estimated usage as real context", () => {
    const aggregate = footerTelemetry({
      prompt_tokens: 1_400_000,
      completion_tokens: 3200,
      cached_tokens: 1_330_000,
    }, 120, theme)
    const estimated = footerTelemetry({
      last_request_prompt_tokens: 148_000,
      estimated_tokens: 148_400,
      last_request_context_window_tokens: 300_000,
    }, 120, theme)

    expect(aggregate.chunks).toHaveLength(0)
    expect(estimated.chunks).toHaveLength(0)
  })
})
