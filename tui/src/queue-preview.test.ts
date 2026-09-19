import { afterEach, describe, expect, test } from "bun:test"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { QueuePreview } from "./queue-preview"

describe("QueuePreview", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  test("shows the latest follow-ups without becoming another card", async () => {
    setup = await createTestRenderer({ width: 64, height: 12, screenMode: "alternate-screen" })
    const preview = new QueuePreview(setup.renderer, {
      accent: "#EF8E30",
      muted: "#A1A1AA",
      faint: "#71717A",
    }, "darwin")
    setup.renderer.root.add(preview.root)

    preview.update(["first\nline", "second", "third", "fourth"])
    await setup.renderOnce()
    const frame = setup.captureCharFrame()

    expect(frame).toContain("Queued next  4")
    expect(frame).toContain("⌥↑ edit last")
    expect(frame).not.toContain("first line")
    expect(frame).toContain("↳ second")
    expect(frame).toContain("↳ fourth")

    preview.update([])
    await setup.renderOnce()
    expect(setup.captureCharFrame()).not.toContain("Queued next")
  })
})
