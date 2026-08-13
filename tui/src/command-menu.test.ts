import { afterEach, describe, expect, test } from "bun:test"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { CommandMenu } from "./command-menu"
import type { SlashCommand } from "./protocol"

const commands: SlashCommand[] = [
  {
    command: "/help",
    title: "Help",
    description: "Show available commands",
    argHint: "",
    acceptsArgs: false,
  },
  {
    command: "/history",
    title: "History",
    description: "Show recent messages",
    argHint: "[n]",
    acceptsArgs: true,
  },
]

describe("CommandMenu", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  test("discovers, navigates, and completes backend commands", async () => {
    setup = await createTestRenderer({ width: 80, height: 18, screenMode: "alternate-screen" })
    const menu = new CommandMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
    })
    setup.renderer.root.add(menu.root)
    menu.setCommands(commands)
    menu.update("/h")
    await setup.renderOnce()

    const frame = setup.captureCharFrame()
    expect(frame).toContain("› /help")
    expect(frame).toContain("/history [n]")
    expect(menu.completion("/h")).toBe("/help")

    expect(menu.move(1)).toBe(true)
    expect(menu.complete()).toBe("/history ")
    expect(menu.visible).toBe(false)
  })

  test("hides outside the leading command token", async () => {
    setup = await createTestRenderer({ width: 60, height: 12, screenMode: "alternate-screen" })
    const menu = new CommandMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
    })
    menu.setCommands(commands)
    menu.update("explain /help")
    expect(menu.visible).toBe(false)
    menu.update("/history 5")
    expect(menu.visible).toBe(false)
  })
})
