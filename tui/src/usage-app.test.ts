import { afterEach, describe, expect, test } from "bun:test"
import { type TextareaRenderable } from "@opentui/core"
import { MockTreeSitterClient, createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { NanobotTui } from "./app"
import type { UsagePanel } from "./usage-panel"
import type { RecoveryState } from "./protocol"

const originalFetch = globalThis.fetch
const page = (input = 9000) => ({
  messages: [{
    id: "reply", turnId: "turn", role: "assistant", content: "Saved reply",
    usage: { prompt_tokens: 15000, context_tokens: 9000 }, contextWindowTokens: 262144,
    roundUsages: [
      { prompt_tokens: 3000, completion_tokens: 100, cached_tokens: 0 },
      { prompt_tokens: input, completion_tokens: 200, cached_tokens: 6000 },
    ],
  }],
})

async function waitUntil(predicate: () => boolean): Promise<void> {
  const deadline = Date.now() + 2000
  while (!predicate() && Date.now() < deadline) await Bun.sleep(5)
  expect(predicate()).toBe(true)
}

// The mounted app owns these retained renderables; assertions exercise keyboard input and frames.
interface MountedUI {
  composer: TextareaRenderable
  usagePanel: UsagePanel
  commandMenu: { visible: boolean }
  ready: boolean
}

describe("TUI /usage", () => {
  let setup: TestRendererSetup | undefined
  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
    globalThis.fetch = originalFetch
  })

  async function mount(history: () => Promise<Response> = async () => Response.json(page())) {
    const sent: string[] = []
    const client = {
      activeChatId: "chat", connect() {}, close() {},
      send(content: string) { sent.push(content); return "turn" },
      attach(chatId: string) { this.activeChatId = chatId },
      newChat() { this.activeChatId = "new-chat" },
      setWorkspaceScope() {},
      async updateRecovery(): Promise<RecoveryState> { return { status: "recovered", recovery_id: "r" } },
    }
    globalThis.fetch = (async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes("/webui-thread")) return history()
      return Response.json({ commands: [], sessions: [], skills: [], candidates: [] })
    }) as typeof fetch
    setup = await createTestRenderer({ width: 80, height: 30, screenMode: "alternate-screen", consoleMode: "disabled" })
    const app = NanobotTui.mount(setup.renderer, {
      wsUrl: "ws://localhost.invalid/ws", apiUrl: "http://nanobot.test", apiToken: "test-token",
      model: "test/model", modelPreset: "default", workspace: "/test", version: "test",
      access: "workspace access", theme: "dark",
    }, client, new MockTreeSitterClient({ autoResolveTimeout: 0 }))
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as MountedUI
    await waitUntil(() => ui.ready)
    return { app, ui, sent, client }
  }

  async function close(ui: MountedUI) {
    setup!.mockInput.pressEscape()
    await waitUntil(() => !ui.usagePanel.visible)
  }

  async function open(ui: MountedUI) {
    ui.composer.setText("/usage")
    setup!.mockInput.pressEnter()
    await waitUntil(() => ui.usagePanel.visible)
    await setup!.flush()
  }

  test("completes and opens locally, navigates rounds, resizes, and returns to the composer", async () => {
    const { ui, sent } = await mount()
    await setup!.mockInput.typeText("/us")
    setup!.mockInput.pressTab()
    expect(ui.composer.plainText).toBe("/usage")
    setup!.mockInput.pressEnter()
    await waitUntil(() => ui.usagePanel.visible)
    await setup!.flush()
    let frame = setup!.captureCharFrame()
    expect(frame).toContain("Context 9k / 262k")
    expect(frame).toContain("Round 2/2 · In 9,000 · Out 200")
    expect(frame).toContain("←→ round")
    expect(sent).toEqual([])
    setup!.mockInput.pressArrow("left")
    await setup!.renderOnce()
    expect(setup!.captureCharFrame()).toContain("Round 1/2 · In 3,000 · Out 100")
    expect(setup!.captureCharFrame()).toContain("Cache 0%")
    for (const [width, height] of [[56, 18], [40, 10], [80, 30]] as const) {
      setup!.resize(width, height)
      await setup!.renderOnce()
      frame = setup!.captureCharFrame()
      expect(frame).toContain("Context 9k / 262k")
      expect(frame).toContain("Ask nanobot anything")
    }
    await close(ui)
    await setup!.renderOnce()
    expect(ui.usagePanel.visible).toBe(false)
    await setup!.mockInput.typeText("next prompt")
    expect(ui.composer.plainText).toBe("next prompt")
    expect(sent).toEqual([])
  })

  test("does not queue a local usage command after dismissing completion during a turn", async () => {
    const { app, ui, sent } = await mount()
    app.accept({ event: "message_accepted", chat_id: "chat", turn_id: "active", starts_turn: true })
    await setup!.mockInput.typeText("/usage")
    setup!.mockInput.pressEscape()
    await waitUntil(() => !ui.commandMenu.visible)
    setup!.mockInput.pressTab()
    expect(ui.composer.plainText).toBe("/usage")
    expect(ui.usagePanel.visible).toBe(false)
    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "active" })
    expect(sent).toEqual([])
    setup!.mockInput.pressEnter()
    await waitUntil(() => ui.usagePanel.visible)
    await setup!.flush()
    expect(setup!.captureCharFrame()).toContain("Context 9k / 262k")
    expect(sent).toEqual([])
  })

  test("refreshes on turn completion without adding duplicate rounds", async () => {
    let input = 9000
    let requests = 0
    const { app, ui, sent } = await mount(async () => { requests++; return Response.json(page(input)) })
    await open(ui)
    input = 12000
    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "turn" })
    await waitUntil(() => requests === 2)
    await setup!.flush()
    const frame = setup!.captureCharFrame()
    expect(frame).toContain("Round 2/2 · In 12,000 · Out 200")
    expect(frame).not.toContain("Round 4/4")
    expect(sent).toEqual([])
  })

  test("ignores an in-flight response after Escape and a newer request supersedes it", async () => {
    const pending: Array<(response: Response) => void> = []
    const { ui } = await mount(() => new Promise((resolve) => pending.push(resolve)))
    await open(ui)
    expect(setup!.captureCharFrame()).toContain("Loading usage")
    await close(ui)
    await open(ui)
    pending[1]!(Response.json(page(12000)))
    await setup!.flush()
    pending[0]!(Response.json(page(9000)))
    await setup!.flush()
    expect(setup!.captureCharFrame()).toContain("In 12,000")
    await close(ui)
    expect(ui.usagePanel.visible).toBe(false)
  })

  test("does not resurrect the previous session's panel after attach", async () => {
    let finish: ((response: Response) => void) | undefined
    let requests = 0
    const { app, ui, client } = await mount(() => {
      requests++
      if (requests === 1) return new Promise((resolve) => { finish = resolve })
      return Promise.resolve(Response.json({ messages: [] }))
    })
    await open(ui)
    client.attach("other-chat")
    app.accept({ event: "attached", chat_id: "other-chat" })
    finish!(Response.json(page()))
    await setup!.flush()
    expect(ui.usagePanel.visible).toBe(false)
    expect(setup!.captureCharFrame()).not.toContain("Context 9k")
    await open(ui)
    expect(setup!.captureCharFrame()).toContain("No model-call usage available yet")
  })

  test("keeps empty sessions and failed requests usable without sending the command", async () => {
    let fail = false
    const { ui, sent } = await mount(async () => {
      if (fail) throw new Error("offline")
      return new Response(null, { status: 404 })
    })
    await open(ui)
    expect(setup!.captureCharFrame()).toContain("No model-call usage available yet")
    await close(ui)
    fail = true
    await open(ui)
    expect(setup!.captureCharFrame()).toContain("Usage unavailable · reopen /usage to retry")
    await setup!.mockInput.typeText("hello")
    expect(ui.usagePanel.visible).toBe(false)
    expect(ui.composer.plainText).toBe("hello")
    expect(sent).toEqual([])
  })
})
