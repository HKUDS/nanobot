import { afterEach, describe, expect, test } from "bun:test"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { NanobotTui, type AppOptions } from "./app"

const options: AppOptions = {
  wsUrl: "ws://localhost.invalid/ws",
  apiUrl: "",
  apiToken: "",
  model: "test/model",
  workspace: "/tmp/nanobot-workspace",
  version: "test",
  access: "workspace access",
}

function occurrences(frame: string, value: string): number {
  return frame.split(value).length - 1
}

describe("NanobotTui layout", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => setup?.renderer.destroy())

  test("reflows a single retained layout across terminal resizes", async () => {
    setup = await createTestRenderer({
      width: 100,
      height: 30,
      screenMode: "alternate-screen",
      consoleMode: "disabled",
    })
    NanobotTui.mount(setup.renderer, options)

    for (const [width, height] of [[100, 30], [56, 18], [118, 36]] as const) {
      setup.resize(width, height)
      await setup.renderOnce()
      const frame = setup.captureCharFrame()

      expect(setup.renderer.width).toBe(width)
      expect(setup.renderer.height).toBe(height)
      expect(occurrences(frame, "Ask nanobot anything")).toBe(1)
      expect(occurrences(frame, "Ready")).toBe(0)
      expect(occurrences(frame, "Connecting…")).toBe(1)
      expect(occurrences(frame, "nanobot  ·  test/model")).toBe(1)
    }
  })
})
