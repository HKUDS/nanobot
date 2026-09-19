import { afterEach, describe, expect, test } from "bun:test"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { ContextPanel } from "./context-panel"
import type { SessionContextSnapshot } from "./protocol"

const context: SessionContextSnapshot = {
  totalMessages: 8,
  archivedMessages: 0,
  replayMessages: 8,
  estimatedReplayTokens: 950,
  estimatedSummaryTokens: 0,
  estimatedSessionTokens: 950,
  archivedSummary: null,
  archivedSummaryAt: null,
  lastUsage: null,
}

describe("ContextPanel", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  test("omits explanatory copy when no compacted summary exists", async () => {
    setup = await createTestRenderer({ width: 80, height: 18, screenMode: "alternate-screen" })
    const panel = new ContextPanel(setup.renderer, {
      text: "#FFFFFF",
      border: "#555555",
      accent: "#EF8E30",
    })
    setup.renderer.root.add(panel.root)
    panel.show(context)
    await setup.renderOnce()

    const frame = setup.captureCharFrame()
    expect(frame).toContain("~950 tokens · 8 replay · 0 archived")
    expect(frame).not.toContain("Agent context")
    expect(frame).not.toContain("no compacted summary")
  })
})
