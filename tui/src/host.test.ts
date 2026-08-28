import { describe, expect, test } from "bun:test"

import { createTuiHost } from "./host"

async function settle(): Promise<void> {
  await Bun.sleep(0)
  await Bun.sleep(0)
}

describe("TUI host integration", () => {
  test("standalone terminals remain a no-op", async () => {
    const commands: string[][] = []
    const host = createTuiHost({}, async (command) => { commands.push([...command]) })

    host.reportTitle("task")
    host.release()
    await settle()

    expect(commands).toEqual([])
  })

  test("requires both Herdr environment markers", async () => {
    const commands: string[][] = []
    const run = async (command: readonly string[]) => { commands.push([...command]) }

    createTuiHost({ HERDR_ENV: "1" }, run).reportTitle("missing pane")
    createTuiHost({ HERDR_PANE_ID: "w1:p2" }, run).reportTitle("missing host")
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
    expect(commands.flat()).not.toContain("report-agent")
    expect(commands.flat()).not.toContain("report-agent-session")
    expect(commands.flat()).not.toContain("--token")
  })
})
