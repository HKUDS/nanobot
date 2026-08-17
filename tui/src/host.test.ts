import { describe, expect, test } from "bun:test"

import { createTuiHost, currentGitBranch } from "./host"

async function settle(): Promise<void> {
  await Bun.sleep(40)
  await Bun.sleep(0)
}

describe("TUI host integration", () => {
  test("reads the current workspace branch without leaking git errors", () => {
    expect(currentGitBranch(process.cwd())).not.toBe("")
    expect(currentGitBranch("/definitely/not/a/repository")).toBe("")
  })

  test("standalone terminals remain a no-op", async () => {
    const commands: string[][] = []
    const host = createTuiHost({}, async (command) => { commands.push([...command]) })

    host.reportState("working", "task")
    host.reportSession("chat")
    host.reportMetadata({ model: "gpt", task: "task" })
    host.release()
    await settle()

    expect(host.hosted).toBe(false)
    expect(commands).toEqual([])
  })

  test("reports semantic lifecycle, session identity, metadata, and release", async () => {
    const commands: string[][] = []
    const host = createTuiHost(
      { HERDR_ENV: "1", HERDR_PANE_ID: "w1:p2", HERDR_BIN_PATH: "/bin/herdr" },
      async (command) => { commands.push([...command]) },
    )

    host.reportMetadata({
      model: "openai/gpt",
      branch: "feat/host",
      workspace: "/repo",
      task: "  Fix\nHerdr  integration ",
      action: "Testing",
    })
    host.reportSession("chat-1")
    host.reportState("working", "Fix Herdr integration")
    host.reportState("working", "Fix Herdr integration")
    host.reportState("blocked", "Approval required")
    host.release()
    await settle()

    expect(host.hosted).toBe(true)
    expect(commands).toHaveLength(6)
    expect(commands[0]).toContain("pane")
    expect(commands[0]).toContain("report-metadata")
    expect(commands[0]).toContain("task=Fix Herdr integration")
    expect(commands[1]).toContain("report-agent-session")
    expect(commands[1]).toContain("chat-1")
    expect(commands[2]).toContain("working")
    expect(commands[2]).toContain("--agent-session-id")
    expect(commands[3]).toContain("blocked")
    expect(commands[4]).toContain("--clear-token")
    expect(commands[5]).toContain("release-agent")
  })

  test("metadata patches only changed tokens", async () => {
    const commands: string[][] = []
    const host = createTuiHost(
      { HERDR_ENV: "1", HERDR_PANE_ID: "w1:p2" },
      async (command) => { commands.push([...command]) },
    )

    host.reportMetadata({ model: "gpt", branch: "main" })
    host.reportMetadata({ model: "gpt", branch: "main" })
    host.reportMetadata({ model: "gpt", branch: "" })
    await settle()

    expect(commands).toHaveLength(1)
    expect(commands[0]).toContain("model=gpt")
    expect(commands[0]).toContain("--clear-token")
    expect(commands[0]).toContain("branch")
  })
})
