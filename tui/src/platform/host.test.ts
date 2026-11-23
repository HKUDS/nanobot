import { describe, expect, test } from "bun:test"

import {
  configureOpenTuiEnvironment,
  createTuiHost,
} from "./host"

async function settle(): Promise<void> {
  await Bun.sleep(0)
  await Bun.sleep(0)
}

describe("TUI host integration", () => {
  test("disables the explicit-width probe on Windows", () => {
    const environment: Record<string, string | undefined> = {}

    configureOpenTuiEnvironment(environment, "win32")

    expect(environment.OPENTUI_FORCE_EXPLICIT_WIDTH).toBe("false")
  })

  test("preserves explicit probe choices and leaves other platforms unchanged", () => {
    const overridden = {
      OPENTUI_FORCE_EXPLICIT_WIDTH: "true",
    }
    const nonWindows: Record<string, string | undefined> = {}

    configureOpenTuiEnvironment(overridden, "win32")
    configureOpenTuiEnvironment(nonWindows, "linux")

    expect(overridden.OPENTUI_FORCE_EXPLICIT_WIDTH).toBe("true")
    expect(nonWindows.OPENTUI_FORCE_EXPLICIT_WIDTH).toBeUndefined()
  })

  test("standalone and partially configured terminals never report or clear pane metadata", async () => {
    const commands: string[][] = []
    const run = async (command: readonly string[]) => { commands.push([...command]) }

    for (const environment of [{}, { HERDR_ENV: "1" }, { HERDR_PANE_ID: "w1:p2" }]) {
      const host = createTuiHost(environment, run)
      host.reportTitle("task")
      host.release()
    }
    await settle()

    expect(commands).toEqual([])
  })

  test("reports only normalized pane title changes and clears the title on release", async () => {
    const commands: string[][] = []
    const host = createTuiHost(
      { HERDR_ENV: "1", HERDR_PANE_ID: "w1:p2", HERDR_BIN_PATH: "/bin/herdr" },
      async (command) => { commands.push([...command]) },
    )

    host.reportTitle("  Fix\nHerdr  integration ")
    host.reportTitle("Fix Herdr integration")
    host.reportTitle("Review results")
    host.release()
    host.reportTitle("ignored after release")
    await settle()

    expect(commands).toEqual([
      [
        "/bin/herdr", "pane", "report-metadata", "w1:p2",
        "--source", "nanobot:tui:metadata", "--seq", "1",
        "--title", "Fix Herdr integration",
      ],
      [
        "/bin/herdr", "pane", "report-metadata", "w1:p2",
        "--source", "nanobot:tui:metadata", "--seq", "2",
        "--title", "Review results",
      ],
      [
        "/bin/herdr", "pane", "report-metadata", "w1:p2",
        "--source", "nanobot:tui:metadata", "--seq", "3", "--clear-title",
      ],
    ])
  })
})
