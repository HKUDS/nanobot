import { describe, expect, test } from "bun:test"
import { join } from "node:path"
import { BoxRenderable, TextareaRenderable } from "@opentui/core"
import { MockTreeSitterClient, createTestRenderer } from "@opentui/core/testing"

import { NanobotTui, sessionExitMessage, terminalModelFailureLine } from "./app"
import type { TuiHost } from "../platform/host"
import { client, occurrences, options, waitUntil } from "./test-support"

test("formats a reusable session ID after exit", () => {
  expect(sessionExitMessage("resume-chat")).toBe(
    "Resume with: nanobot agent --session websocket:resume-chat\n",
  )
})

test("formats actionable terminal model failures without inventing retries", () => {
  expect(terminalModelFailureLine("billing")).toBe(
    "Model provider quota is unavailable. "
      + "Add credit or check billing for the provider account, then try again.",
  )
  expect(terminalModelFailureLine("unknown")).toBe(
    "Model provider request failed. "
      + "Check the provider configuration or service status, then try again.",
  )
})

describe("NanobotTui with a Herdr pane title reporter", () => {
  test("keeps the full terminal experience while reporting task titles", async () => {
    const setup = await createTestRenderer({ width: 80, height: 22, screenMode: "alternate-screen" })
    const titles: string[] = []
    let released = false
    const host: TuiHost = {
      reportTitle(title) { titles.push(title) },
      release() { released = true },
    }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
      host,
    )
    const ui = app as unknown as {
      composer: TextareaRenderable
      composerFrame: BoxRenderable
    }

    await setup.mockInput.typeText("/")
    await setup.flush()
    const commandFrame = setup.captureCharFrame()
    expect(commandFrame).toContain("/sessions")
    expect(commandFrame).toContain("/new-chat")
    expect(commandFrame).toContain("/branch")
    setup.mockInput.pressEscape()
    ui.composer.setText("")

    app.accept({ event: "attached", chat_id: "chat" })
    app.accept({
      event: "user_message",
      chat_id: "chat",
      text: "Ship the Herdr integration",
      turn_id: "turn-1",
      starts_turn: true,
    })
    app.accept({
      event: "message",
      chat_id: "chat",
      text: "",
      kind: "tool_hint",
      tool_events: [{ phase: "end", call_id: "read", name: "read_file", arguments: { path: "app.ts" } }],
    })
    await setup.flush()
    const activeFrame = setup.captureCharFrame()
    expect(activeFrame).toContain(">_  nanobot")
    expect(activeFrame).toContain("default ▾")
    expect(occurrences(activeFrame, "› Ship the Herdr integration")).toBe(1)
    expect(occurrences(activeFrame, "app.ts")).toBe(1)
    expect(ui.composer.placeholder).toBe("Enter send now  Tab send next")
    expect(ui.composerFrame.height).toBe(3)
    expect(titles).toEqual(["Ship the Herdr integration"])

    app.accept({
      event: "turn_end",
      chat_id: "chat",
      turn_id: "turn-1",
      goal_state: {
        active: false,
        status: "blocked",
        ui_summary: "Approval required",
      },
    })
    app.accept({
      event: "user_message",
      chat_id: "chat",
      text: "Approved",
      turn_id: "turn-2",
      starts_turn: true,
    })

    expect(titles).toEqual(["Ship the Herdr integration", "Approved"])

    app.stop()
    expect(released).toBe(true)
  })
})

if (process.platform !== "win32") {
  test("restores the terminal after SIGTERM", async () => {
    const child = Bun.spawn(["bun", "src/index.ts"], {
      cwd: join(import.meta.dir, "..", ".."),
      env: {
        ...process.env,
        NANOBOT_TUI_WS_URL: "ws://127.0.0.1:9/ws",
        NANOBOT_TUI_API_URL: "",
        NANOBOT_TUI_API_TOKEN: "",
        NANOBOT_TUI_CHAT_ID: "resume-chat",
        NANOBOT_TUI_MODEL: "test/model",
        NANOBOT_TUI_WORKSPACE: "/tmp/nanobot-test",
        NANOBOT_TUI_VERSION: "test",
        NANOBOT_TUI_ACCESS: "workspace access",
        NANOBOT_TUI_THEME: "dark",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const decoder = new TextDecoder()
    let output = ""
    const collectOutput = (async () => {
      const reader = child.stdout.getReader()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        output += decoder.decode(value, { stream: true })
      }
      output += decoder.decode()
    })()

    // Slow Intel runners can spend more than 250 ms importing OpenTUI. Wait
    // for terminal setup, which happens after the signal handlers are
    // registered, before exercising shutdown.
    await waitUntil(() => output.includes("\x1b[?1049h"), 5_000)
    child.kill("SIGTERM")
    const exitCode = await child.exited
    await collectOutput
    const error = await new Response(child.stderr).text()

    expect(exitCode).toBe(0)
    expect(error).toBe("")
    expect(output).toContain("\x1b[?1049h")
    expect(output).toContain("\x1b[?1049l")
    expect(output.indexOf("\x1b[?1049l")).toBeLessThan(output.indexOf("Resume with:"))
    expect(output).toContain(
      "Resume with: nanobot agent --session websocket:resume-chat\n",
    )
  })
}
