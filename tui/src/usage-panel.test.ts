import { afterEach, describe, expect, test } from "bun:test"
import { RGBA, type TextRenderable } from "@opentui/core"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { UsagePanel, type UsagePanelTheme } from "./usage-panel"
import type { SessionUsageSnapshot } from "./protocol"

const theme: UsagePanelTheme = {
  text: "#ECEDEE", muted: "#A1A1AA", border: "#3F3F46", accent: "#EF8E30",
  cached: "#1795A2", warning: "#F5C451", error: "#F87171",
}
const snapshot: SessionUsageSnapshot = {
  context: { tokens: 9_000, windowTokens: 262_144 },
  rounds: [
    { prompt_tokens: 3_000, completion_tokens: 200 },
    { prompt_tokens: 6_000, completion_tokens: 400, cached_tokens: 0 },
    { prompt_tokens: 9_000, completion_tokens: 800, cached_tokens: 6_000, generation_ms: 1500, estimated_tokens: 20 },
  ],
}

describe("UsagePanel", () => {
  let setup: TestRendererSetup | undefined
  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  test("renders context occupancy and selects logical-round details without inventing cache data", async () => {
    setup = await createTestRenderer({ width: 80, height: 30, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    panel.resize(80, 30)
    panel.show(snapshot)
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("Context 9k / 262k")
    expect(frame).toContain("3%")
    expect(frame).toContain("Input tokens · max 9k")
    expect(frame).toContain("Round 3/3 · In 9,000 · Out 800")
    expect(frame).toContain("Cache 67% · 1.5s · includes estimated usage")
    expect(frame).toContain("Uncached")
    expect(frame).toContain("Unknown cache")
    expect(frame).toContain("███")
    const rows = frame.split("\n")
    const detailsIndex = rows.findIndex((row) => row.includes("Round 3/3"))
    expect(rows[detailsIndex - 1]).toContain("███")
    panel.move(-1)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Cache 0%")
    panel.move(-1)
    panel.move(-1)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Round 1/3 · In 3,000 · Out 200")
    expect(setup.captureCharFrame()).toContain("Cache ?")
  })

  test("splits cached foreground and uncached background at eighth-row precision without color bleed", async () => {
    setup = await createTestRenderer({ width: 80, height: 30, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    panel.show({ context: null, rounds: [{ prompt_tokens: 1000, cached_tokens: 800 }] })
    const barSpans = () => setup!.captureSpans().lines.flatMap((line) =>
      line.spans.filter((span) => /[▁▂▃▄▅▆▇█]/u.test(span.text)))

    for (const palette of [theme, { ...theme, accent: "#B94D0B", cached: "#0F766E" }]) {
      panel.setTheme(palette)
      for (const [height, glyphs] of [[30, ["███", "▆▆▆", "███", "███", "███", "███"]], [18, ["▆▆▆"]]] as const) {
        setup.resize(80, height)
        panel.resize(80, height)
        await setup.renderOnce()
        const bars = barSpans()
        expect(bars.map((span) => span.text.trim())).toEqual([...glyphs])
        const cachedColor = RGBA.fromHex(palette.cached)
        const uncachedColor = RGBA.fromHex(palette.accent)
        const split = bars.find((span) => span.text.includes("▆"))!
        expect(split.fg.equals(cachedColor)).toBe(true)
        expect(split.bg.equals(uncachedColor)).toBe(true)
        // Every solid cell below the split is cached; the cell above is uncached.
        expect(bars.filter((span) => span.fg.equals(cachedColor)).length).toBe(height === 30 ? 5 : 1)
        expect(setup.captureSpans().lines.flatMap((line) => line.spans)
          .filter((span) => span.bg.equals(uncachedColor)).map((span) => span.text)).toEqual(["▆▆▆"])
      }
    }
  })

  test("quantizes the cache boundary from raw tokens rather than the rounded total height", async () => {
    setup = await createTestRenderer({ width: 80, height: 30, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    panel.resize(80, 30)
    panel.show({ context: null, rounds: [
      { prompt_tokens: 480 },
      { prompt_tokens: 254, cached_tokens: 215 },
    ] })
    await setup.renderOnce()
    const bars = setup.captureSpans().lines.flatMap((line) =>
      line.spans.filter((span) => /[▁▂▃▄▅▆▇█]/u.test(span.text)))
    const cached = bars.filter((span) => span.fg.equals(RGBA.fromHex(theme.cached)))
    // Total: round(25.4) = 25 eighths; cache: round(21.5) = 22, not round(25 * 215/254) = 21.
    expect(cached.map((span) => span.text.trim())).toEqual(["▆▆▆", "███", "███"])
    expect(bars.some((span) => span.text.includes("▁") && span.fg.equals(RGBA.fromHex(theme.accent)))).toBe(true)
  })

  test("preserves a partial top's empty space when cached and uncached input share it", async () => {
    setup = await createTestRenderer({ width: 80, height: 30, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    panel.resize(80, 30)
    for (const [input, cachedTokens, glyph, color] of [
      [300, 240, "▆", theme.cached], [300, 180, "▆", theme.accent],
      [100, 80, "▅", theme.cached], [1, 0, "▁", theme.accent],
    ] as const) {
      panel.show({ context: null, rounds: [
        { prompt_tokens: 1000 }, { prompt_tokens: input, cached_tokens: cachedTokens },
      ] })
      await setup.renderOnce()
      const spans = setup.captureSpans().lines.flatMap((line) => line.spans)
      const top = spans.find((span) => span.text.includes(glyph))!
      expect(top.text.trim()).toBe(glyph.repeat(3))
      expect(top.fg.equals(RGBA.fromHex(color))).toBe(true)
      expect(top.bg.equals(RGBA.fromHex(theme.accent))).toBe(false)
      expect(top.bg.equals(RGBA.fromHex(theme.cached))).toBe(false)
      expect(setup.captureCharFrame()).toContain(`Cache ${Math.round(cachedTokens / input * 100)}%`)
    }
  })

  test("keeps unknown, zero, and fully cached bars unblended", async () => {
    setup = await createTestRenderer({ width: 80, height: 30, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    panel.resize(80, 30)
    for (const [cachedTokens, color] of [[undefined, theme.muted], [0, theme.accent], [1000, theme.cached], [2000, theme.cached]] as const) {
      panel.show({ context: null, rounds: [{ prompt_tokens: 1000, cached_tokens: cachedTokens }] })
      await setup.renderOnce()
      const bars = setup.captureSpans().lines.flatMap((line) =>
        line.spans.filter((span) => span.text.includes("█")))
      expect(bars.length).toBe(6)
      for (const bar of bars) {
        expect(bar.text.trim()).toBe("███")
        expect(bar.fg.equals(RGBA.fromHex(color))).toBe(true)
        expect(bar.bg.equals(RGBA.fromHex(theme.accent))).toBe(false)
        expect(bar.bg.equals(RGBA.fromHex(theme.cached))).toBe(false)
      }
    }
  })

  test("keeps zero context distinct from unknown capacity and missing usage", async () => {
    setup = await createTestRenderer({ width: 80, height: 26, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    panel.show({ context: { tokens: 0, windowTokens: 1000 }, rounds: [] })
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Context 0 / 1k")
    expect(setup.captureCharFrame()).toContain("0%")
    panel.show({ context: { tokens: 9000 }, rounds: [] })
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Context 9k / ?")
    expect(setup.captureCharFrame()).not.toContain("0%")
    panel.show({ context: null, rounds: [] })
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Context unavailable")
    expect(setup.captureCharFrame()).toContain("No model-call usage available yet")
  })

  test("clamps context and cached portions without losing the actual input count", async () => {
    setup = await createTestRenderer({ width: 80, height: 26, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    panel.show({
      context: { tokens: 2000, windowTokens: 1000 },
      rounds: [{ prompt_tokens: 2000, cached_tokens: 3000 }],
    })
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("Context 2k / 1k")
    expect(frame).toContain("100%")
    expect(frame).toContain("In 2,000 · Out ?")
    expect(frame).toContain("Cache 100%")
  })

  test("does not rebuild hidden content and uses the latest dimensions and theme when reopened", async () => {
    setup = await createTestRenderer({ width: 80, height: 30, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    const body = panel.root.getChildren()[0] as TextRenderable
    const empty = body.content
    panel.resize(80, 30)
    panel.setTheme(theme)
    expect(body.content).toBe(empty)
    panel.show(snapshot)
    const content = body.content
    panel.hide()
    setup.resize(56, 18)
    panel.resize(56, 18)
    panel.setTheme({ ...theme, text: "#18181B", accent: "#B94D0B", cached: "#0F766E" })
    expect(body.content).toBe(content)
    panel.show(snapshot)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Context 9k / 262k")
    expect(panel.root.height).toBeLessThanOrEqual(6)
    const bars = setup.captureSpans().lines.flatMap((line) => line.spans)
      .filter((span) => /[▁▂▃▄▅▆▇█]/u.test(span.text))
    expect(bars.some((span) => span.fg.equals(RGBA.fromHex("#0F766E")))).toBe(true)
  })

  test("collapses vertically in short terminals and retains data across resize and theme changes", async () => {
    setup = await createTestRenderer({ width: 80, height: 30, screenMode: "alternate-screen" })
    const panel = new UsagePanel(setup.renderer, theme)
    setup.renderer.root.add(panel.root)
    panel.show(snapshot)
    for (const [width, height, maxPanelHeight] of [[80, 30, 17], [56, 18, 6], [40, 10, 4]] as const) {
      setup.resize(width, height)
      panel.resize(width, height)
      await setup.renderOnce()
      expect(panel.root.height).toBeLessThanOrEqual(maxPanelHeight)
      expect(setup.captureCharFrame()).toContain("Context 9k / 262k")
      expect(setup.captureCharFrame()).toContain("3%")
    }
    setup.resize(80, 30)
    panel.resize(80, 30)
    panel.setTheme({ ...theme, text: "#18181B", border: "#D4D4D8" })
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Round 3/3 · In 9,000 · Out 800")
    panel.hide()
    await setup.renderOnce()
    expect(setup.captureCharFrame()).not.toContain("Context")
  })
})
