import { afterEach, describe, expect, test } from "bun:test"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { CommandMenu, resolveSlashCommandLifecycle } from "./command-menu"
import type { SlashCommand } from "./protocol"

const commands: SlashCommand[] = [
  {
    command: "/help",
    title: "Help",
    description: "Show available commands",
    argHint: "",
    lifecycle: "side_channel",
    acceptsArgs: false,
  },
  {
    command: "/history",
    title: "History",
    description: "Show recent messages",
    argHint: "[n]",
    lifecycle: "side_channel",
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

  test("keeps gateway commands authoritative over local actions", async () => {
    setup = await createTestRenderer({ width: 60, height: 12, screenMode: "alternate-screen" })
    const menu = new CommandMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
    })
    menu.setCommands(commands, [{
      command: "/help",
      title: "Local help",
      description: "Must not replace nanobot help",
      action: "sessions",
    }, {
      command: "/sessions",
      title: "Sessions",
      description: "Switch conversations",
      action: "sessions",
    }])

    expect(menu.resolve("/help")?.source).toBe("gateway")
    expect(menu.resolve("/sessions")).toMatchObject({
      source: "tui",
      command: { action: "sessions" },
    })
  })

  test("discovers and completes the local exit action", async () => {
    setup = await createTestRenderer({ width: 60, height: 12, screenMode: "alternate-screen" })
    const menu = new CommandMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
    })
    setup.renderer.root.add(menu.root)
    menu.setCommands([], [{
      command: "/exit",
      title: "Exit",
      description: "Close this terminal UI",
      action: "exit",
    }])

    menu.update("/ex")
    await setup.renderOnce()

    expect(setup.captureCharFrame()).toContain("/exit")
    expect(menu.completion("/ex")).toBe("/exit")
    expect(menu.resolve("/exit")).toMatchObject({
      source: "tui",
      command: { action: "exit" },
    })
  })

  test("resolves argument-sensitive command lifecycles", () => {
    const goal: SlashCommand = {
      command: "/goal",
      title: "Goal",
      description: "Start a long-running goal",
      argHint: "<goal>",
      lifecycle: "agent_turn_with_args",
      acceptsArgs: true,
    }

    expect(resolveSlashCommandLifecycle("/goal", goal)).toBe("side_channel")
    expect(resolveSlashCommandLifecycle("/goal ship it", goal)).toBe("agent_turn")
    expect(resolveSlashCommandLifecycle("/help extra", commands[0]!)).toBeNull()
  })
})
