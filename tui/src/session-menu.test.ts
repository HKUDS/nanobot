import { afterEach, describe, expect, test } from "bun:test"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { SessionMenu, sessionLabel } from "./session-menu"
import type { SessionSummary } from "./protocol"

const sessions: SessionSummary[] = [
  {
    chatId: "one",
    title: "API migration",
    preview: "Move authentication to the new client",
    createdAt: "2026-08-12T10:00:00Z",
    updatedAt: "2026-08-13T10:00:00Z",
    runStartedAt: null,
    modelPreset: "Codex",
    pinned: true,
    archived: false,
  },
  {
    chatId: "two",
    title: "Release checklist",
    preview: "Prepare the stable release",
    createdAt: "2026-08-11T10:00:00Z",
    updatedAt: "2026-08-12T10:00:00Z",
    runStartedAt: null,
    modelPreset: null,
    recoveryState: {
      status: "awaiting_user",
      recovery_id: "recovery-two",
      reason: "tool execution interrupted",
    },
    pinned: false,
    archived: false,
  },
]

describe("SessionMenu", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  test("marks, filters, and chooses gateway sessions", async () => {
    setup = await createTestRenderer({ width: 80, height: 18, screenMode: "alternate-screen" })
    const menu = new SessionMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
      accent: "#FF8A33",
      warning: "#F5C451",
    })
    setup.renderer.root.add(menu.root)
    menu.open(sessions, "one", 6, "Codex")
    await setup.renderOnce()

    expect(setup.captureCharFrame()).toContain("› ● API migration")
    expect(setup.captureCharFrame()).not.toContain("Move authentication")
    expect(setup.captureCharFrame()).not.toContain("Codex")
    expect(menu.choose()?.chatId).toBe("one")

    menu.update("release stable", 6)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("⚠ Release checklist")
    expect(menu.choose()?.chatId).toBe("two")
  })

  test("keeps generated multi-line titles on one terminal row", () => {
    expect(sessionLabel({ ...sessions[0]!, title: "Release\n  checklist" })).toBe(
      "Release checklist",
    )
  })

  test("animates running sessions and marks completed background sessions unread", async () => {
    setup = await createTestRenderer({ width: 80, height: 18, screenMode: "alternate-screen" })
    const menu = new SessionMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
      accent: "#FF8A33",
      warning: "#F5C451",
    })
    setup.renderer.root.add(menu.root)
    const running = {
      ...sessions[0]!,
      chatId: "running",
      title: "Background task",
      runStartedAt: Date.now(),
      pinned: false,
    }

    menu.open([sessions[0]!, running], "one", 6)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toMatch(/[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] Background task/u)

    menu.replace([{ ...sessions[0]! }, { ...running, runStartedAt: null }], "one")
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("• Background task")

    menu.markRead("running")
    menu.replace([{ ...sessions[0]! }, { ...running, runStartedAt: null }], "running")
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("● Background task")
    menu.hide()
  })

  test("prioritizes actionable sessions without moving keyboard selection on refresh", async () => {
    setup = await createTestRenderer({ width: 80, height: 18, screenMode: "alternate-screen" })
    const menu = new SessionMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
      accent: "#FF8A33",
      warning: "#F5C451",
    })
    setup.renderer.root.add(menu.root)
    const running = {
      ...sessions[0]!,
      chatId: "running",
      title: "Background task",
      runStartedAt: Date.now(),
      pinned: false,
    }

    const idle = { ...sessions[1]!, recoveryState: null }
    menu.open([sessions[0]!, running, idle], "one", 6)
    expect(menu.choose()?.chatId).toBe("one")
    expect(menu.move(1)).toBe(true)
    expect(menu.choose()?.chatId).toBe("running")

    menu.replace([sessions[0]!, running, sessions[1]!], "one")
    await setup.renderOnce()

    expect(menu.choose()?.chatId).toBe("running")
    const frame = setup.captureCharFrame()
    expect(frame.indexOf("Release checklist")).toBeLessThan(frame.indexOf("Background task"))
    menu.hide()
  })

  test("keeps keyboard selection when the pointer stays over the previous row", async () => {
    setup = await createTestRenderer({ width: 80, height: 18, screenMode: "alternate-screen" })
    const menu = new SessionMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
      accent: "#FF8A33",
      warning: "#F5C451",
    })
    setup.renderer.root.add(menu.root)
    menu.open(sessions, "one", 6)
    await setup.renderOnce()

    const firstRow = menu.root.getChildren()[0]
    const secondRow = menu.root.getChildren()[1]
    if (!firstRow || !secondRow) throw new Error("session rows were not rendered")
    const firstPosition = { x: firstRow.x + 2, y: firstRow.y }
    await setup.mockMouse.moveTo(secondRow.x + 2, secondRow.y)
    await setup.flush()
    expect(menu.choose()?.chatId).toBe("two")

    await setup.mockMouse.moveTo(firstPosition.x, firstPosition.y)
    await setup.flush()
    expect(menu.choose()?.chatId).toBe("one")

    expect(menu.move(1)).toBe(true)
    await setup.flush()
    expect(menu.choose()?.chatId).toBe("two")
  })

  test("shows compact workspace names only when they distinguish sessions", async () => {
    setup = await createTestRenderer({ width: 100, height: 18, screenMode: "alternate-screen" })
    const menu = new SessionMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
      accent: "#FF8A33",
      warning: "#F5C451",
    })
    setup.renderer.root.add(menu.root)
    const scoped = sessions.map((session) => ({
      ...session,
      workspaceScope: {
        project_path: "/work/nanobot",
        project_name: "nanobot",
        access_mode: "restricted" as const,
      },
    }))

    menu.open(scoped, "one", 6)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).not.toContain("nanobot · Codex")

    menu.open([
      scoped[0]!,
      {
        ...scoped[1]!,
        workspaceScope: {
          project_path: "C:\\work\\desktop",
          project_name: "desktop",
          access_mode: "restricted",
        },
      },
    ], "one", 6)
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("nanobot · Codex")
    expect(frame).toContain("desktop")

    menu.update("desktop", 6)
    expect(menu.choose()?.chatId).toBe("two")

    menu.open([
      {
        ...scoped[0]!,
        workspaceScope: {
          project_path: "/work/frontend/nanobot",
          project_name: "nanobot",
          access_mode: "restricted",
        },
      },
      {
        ...scoped[1]!,
        workspaceScope: {
          project_path: "/work/backend/nanobot",
          project_name: "nanobot",
          access_mode: "restricted",
        },
      },
    ], "one", 6)
    await setup.renderOnce()
    const duplicates = setup.captureCharFrame()
    expect(duplicates).toContain("frontend/nanobot")
    expect(duplicates).toContain("backend/nanobot")
  })

  test("shows only model overrides and keeps previews searchable", async () => {
    setup = await createTestRenderer({ width: 80, height: 18, screenMode: "alternate-screen" })
    const menu = new SessionMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
      accent: "#FF8A33",
      warning: "#F5C451",
    })
    setup.renderer.root.add(menu.root)

    menu.open(sessions, "one", 6, "Codex")
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).not.toContain("Codex")
    expect(frame).not.toContain("Prepare the stable release")

    menu.update("prepare stable", 6)
    await setup.renderOnce()
    expect(menu.choose()?.chatId).toBe("two")

    menu.replace([{ ...sessions[1]!, modelPreset: "Deep Research" }], "one", "Codex")
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Deep Research")
    menu.hide()
  })
})
