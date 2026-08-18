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
    })
    setup.renderer.root.add(menu.root)
    menu.open(sessions, "one", 6)
    await setup.renderOnce()

    expect(setup.captureCharFrame()).toContain("› ● API migration")
    expect(menu.choose()?.chatId).toBe("one")

    menu.update("release stable", 6)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("Release checklist")
    expect(menu.choose()?.chatId).toBe("two")
  })

  test("keeps generated multi-line titles on one terminal row", () => {
    expect(sessionLabel({ ...sessions[0]!, title: "Release\n  checklist" })).toBe(
      "Release checklist",
    )
  })

  test("shows compact workspace names only when they distinguish sessions", async () => {
    setup = await createTestRenderer({ width: 100, height: 18, screenMode: "alternate-screen" })
    const menu = new SessionMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
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
})
