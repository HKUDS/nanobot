import { afterEach, describe, expect, test } from "bun:test"
import { CliRenderEvents, TextareaRenderable, TextRenderable } from "@opentui/core"
import { MockTreeSitterClient, createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"
import { NanobotTui } from "./app"
import type { RecoveryState, SlashCommand, WorkspaceScopePayload } from "../client"
import { options, client, mount, waitUntil, occurrences } from "./test-support"

describe("NanobotTui session navigation", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  const createRenderer = (rendererOptions: Parameters<typeof createTestRenderer>[0]) => (
    createTestRenderer(rendererOptions)
  )
  test("switches and creates gateway chats without replacing core slash commands", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    globalThis.fetch = (() => Promise.resolve(new Response(JSON.stringify({
      sessions: [
        {
          key: "websocket:chat",
          title: "Current chat",
          preview: "Current work",
          updated_at: "2026-08-13T10:00:00Z",
        },
        {
          key: "websocket:other",
          title: "Release checklist",
          preview: "Prepare stable release",
          updated_at: "2026-08-12T10:00:00Z",
          model_preset: "Deep Research",
        },
      ],
    })))) as unknown as typeof fetch
    const attached: string[] = []
    const newChats: string[] = []
    const transport = client([], attached, newChats)
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
      runtimeControls: { modelText: { plainText: string } }
    }

    try {
      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionMenu.visible)
      expect(ui.composer.placeholder).toBe("Search sessions")

      ui.composer.setText("release")
      ui.composer.submit()
      await waitUntil(() => attached.length === 1)
      expect(attached).toEqual(["other"])
      expect(ui.runtimeControls.modelText.plainText).toBe("Deep Research ▾")
      expect(ui.runtimeControls.modelText.plainText).not.toContain("test/model")

      app.accept({ event: "attached", chat_id: "other" })
      await Bun.sleep(1)
      ui.composer.setText("/new-chat")
      ui.composer.submit()
      await waitUntil(() => newChats.length === 1)
      expect(newChats).toEqual(["new"])
      expect(ui.runtimeControls.modelText.plainText).toBe("default ▾")
    } finally {
      globalThis.fetch = original
    }
  })

  test("switches away from a running session without losing its queued follow-ups", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/sessions")) {
        return Promise.resolve(new Response(JSON.stringify({
          sessions: [
            { key: "websocket:chat", title: "Running chat", run_started_at: 1_700_000_000 },
            { key: "websocket:other", title: "Other chat" },
          ],
        })))
      }
      if (url.endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return Promise.resolve(new Response(JSON.stringify({
        schemaVersion: 3, projection: "events",
        events: url.includes("websocket%3Aother") ? [
          { event: "user_message", chat_id: "other", starts_turn: true, text: "saved question" },
          { event: "stream_end", chat_id: "other", text: "saved answer" },
          { event: "turn_end", chat_id: "other" },
        ] : [],
        page: { has_more_before: false },
      })))
    }) as typeof fetch
    const sent: string[] = []
    const attached: string[] = []
    let activeChatId = "chat"
    const base = client(sent, attached)
    const transport = {
      ...base,
      get activeChatId() { return activeChatId },
      attach(chatId: string) {
        attached.push(chatId)
        activeChatId = chatId
      },
    }
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      transport,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as {
      ready: boolean
      activeTurn: boolean
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
      queuePreview: { root: { visible: boolean } }
      status: { plainText: string }
    }

    try {
      app.accept({ event: "attached", chat_id: "chat" })
      await waitUntil(() => ui.ready)
      app.accept({ event: "goal_status", chat_id: "chat", status: "running", turn_id: "turn" })
      ui.composer.setText("follow up in chat")
      setup.mockInput.pressTab()
      await waitUntil(() => ui.composer.plainText === "")
      expect(ui.queuePreview.root.visible).toBe(true)

      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionMenu.visible)
      await Bun.sleep(120)
      expect(ui.status.plainText).toContain("2 sessions")

      ui.composer.setText("other")
      ui.composer.submit()
      await waitUntil(() => attached.at(-1) === "other")
      app.accept({ event: "attached", chat_id: "other" })
      await waitUntil(() => ui.ready)
      expect(ui.activeTurn).toBe(false)
      expect(ui.queuePreview.root.visible).toBe(false)
      await setup.flush()
      expect(setup.captureCharFrame()).toContain("saved question")
      expect(setup.captureCharFrame()).toContain("saved answer")

      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionMenu.visible)
      ui.composer.setText("running")
      ui.composer.submit()
      await waitUntil(() => attached.at(-1) === "chat")
      app.accept({ event: "attached", chat_id: "chat" })
      app.accept({ event: "goal_status", chat_id: "chat", status: "running", turn_id: "turn" })
      await waitUntil(() => ui.ready && ui.activeTurn)
      expect(ui.queuePreview.root.visible).toBe(true)
      expect(sent).toEqual([])

      app.accept({ event: "turn_end", chat_id: "chat", turn_id: "turn" })
      await waitUntil(() => sent.length === 1)
      expect(sent).toEqual(["follow up in chat"])
    } finally {
      globalThis.fetch = original
    }
  })

  test("refreshes expired API credentials before opening sessions", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let bootstrapRequests = 0
    const sessionAuthorizations: Array<string | null> = []
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const authorization = new Headers(init?.headers).get("Authorization")
      if (url.endsWith("/webui/bootstrap")) {
        bootstrapRequests += 1
        return new Response(JSON.stringify({
          ws_url: "ws://nanobot.test/ws",
          token: "fresh-websocket-token",
          api_token: "fresh-api-token",
        }))
      }
      if (authorization === "Bearer expired-api-token") {
        return new Response("Unauthorized", { status: 401 })
      }
      if (url.endsWith("/api/sessions")) {
        sessionAuthorizations.push(authorization)
        return new Response(JSON.stringify({
          sessions: [{ key: "websocket:chat", title: "Current chat" }],
        }))
      }
      return new Response("{}")
    }) as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      {
        ...options,
        bootstrapUrl: "http://nanobot.test/webui/bootstrap",
        bootstrapSecret: "bootstrap-secret",
        apiUrl: "http://nanobot.test",
        apiToken: "expired-api-token",
      },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      ready: boolean
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
      status: { plainText: string }
    }

    try {
      await waitUntil(() => ui.ready)
      ui.composer.setText("/sessions")
      ui.composer.submit()

      await waitUntil(() => bootstrapRequests >= 1)
      await waitUntil(() => ui.sessionMenu.visible)
      expect(bootstrapRequests).toBe(1)
      expect(sessionAuthorizations.at(-1)).toBe("Bearer fresh-api-token")
      expect(ui.status.plainText).not.toContain("HTTP 401")
    } finally {
      globalThis.fetch = original
    }
  })

  test("tracks canonical presets without overwriting a session override", async () => {
    setup = await createRenderer({ width: 96, height: 20, screenMode: "alternate-screen" })
    const app = mount(setup)
    const ui = app as unknown as { runtimeControls: { modelText: { plainText: string } } }

    app.accept({ event: "attached", chat_id: "chat", model_preset: "Codex" })
    app.accept({
      event: "turn_model_updated",
      chat_id: "chat",
      model_name: "openai/gpt-5.6",
      model_preset: "Codex",
    })
    await setup.flush()
    expect(ui.runtimeControls.modelText.plainText).toBe("Codex ▾")
    expect(ui.runtimeControls.modelText.plainText).not.toContain("openai/gpt-5.6")

    app.accept({
      event: "runtime_model_updated",
      model_name: "deepseek/deepseek-chat",
      model_preset: "DeepSeek",
    })
    await setup.flush()
    expect(ui.runtimeControls.modelText.plainText).toBe("Codex ▾")
    expect(ui.runtimeControls.modelText.plainText).not.toContain("DeepSeek")
  })

  test("returns a default-following chat to the canonical default preset", async () => {
    setup = await createRenderer({ width: 96, height: 20, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, model: "openai/gpt-5.6", modelPreset: "Codex" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as { runtimeControls: { modelText: { plainText: string } } }

    app.accept({ event: "attached", chat_id: "chat", model_preset: null })
    app.accept({
      event: "runtime_model_updated",
      model_name: "deepseek/deepseek-chat",
      model_preset: null,
    })
    await setup.flush()

    expect(ui.runtimeControls.modelText.plainText).toBe("default ▾")
    expect(ui.runtimeControls.modelText.plainText).not.toContain("deepseek/deepseek-chat")
  })

  test("refreshes the canonical preset after the model command completes", async () => {
    setup = await createRenderer({ width: 96, height: 20, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      if (String(input).endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return Promise.resolve(new Response(JSON.stringify({
        sessions: [{ key: "websocket:chat", model_preset: "Deep Research" }],
      })))
    }) as typeof fetch
    const sent: string[] = []
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(sent),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    const ui = app as unknown as {
      composer: TextareaRenderable
      commandMenu: { setCommands(commands: SlashCommand[]): void }
      runtimeControls: { modelText: { plainText: string } }
    }

    try {
      app.accept({ event: "attached", chat_id: "chat", model_preset: null })
      ui.commandMenu.setCommands([{
        command: "/model",
        title: "Model",
        description: "Show or switch model presets",
        argHint: "[preset]",
        lifecycle: "side_channel",
        acceptsArgs: true,
      }])
      ui.composer.setText("/model deep research")
      ui.composer.submit()
      await waitUntil(() => sent.length === 1)
      app.accept({
        event: "message",
        chat_id: "chat",
        text: "Switched model preset to Deep Research.",
        turn_id: "turn",
      })
      await waitUntil(() => ui.runtimeControls.modelText.plainText.includes("Deep Research"))

      expect(sent).toEqual(["/model deep research"])
    } finally {
      globalThis.fetch = original
    }
  })

  test("opens composer runtime controls by mouse and applies canonical choices", async () => {
    const original = globalThis.fetch
    const sent: string[] = []
    const scopes: WorkspaceScopePayload[] = []
    let settingsRequests = 0
    let workspaceRequests = 0
    globalThis.fetch = (async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/settings")) {
        settingsRequests += 1
        return new Response(JSON.stringify({
          model_presets: [
            { name: "default", model: "test/model" },
            { name: "fast", model: "fast/model" },
          ],
        }))
      }
      if (url.endsWith("/api/workspaces")) {
        workspaceRequests += 1
        return new Response(JSON.stringify({
          controls: { can_use_full_access: true },
        }))
      }
      return new Response(JSON.stringify({ sessions: [] }))
    }) as typeof fetch
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(sent, [], [], [], [], scopes),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      runtimeControls: {
        modelText: TextRenderable
        accessText: TextRenderable
        contextText: TextRenderable
        visible: boolean
        menuRoot: { getChildren(): unknown[] }
      }
      composer: TextareaRenderable
      status: TextRenderable
      meta: TextRenderable
    }

    try {
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
      await setup.renderOnce()
      expect(setup.renderer.getCursorState()).toMatchObject({
        style: "line",
        blinking: false,
      })
      expect(ui.runtimeControls.modelText.selectable).toBe(false)
      expect(ui.runtimeControls.accessText.selectable).toBe(false)
      expect(ui.runtimeControls.contextText.selectable).toBe(false)
      expect(ui.status.selectable).toBe(false)
      expect(ui.meta.selectable).toBe(false)
      app.accept({ event: "goal_status", chat_id: "chat", status: "running" })
      await setup.flush()
      await setup.mockMouse.click(
        ui.runtimeControls.modelText.x + 2,
        ui.runtimeControls.modelText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      await setup.flush()
      const modelRows = ui.runtimeControls.menuRoot.getChildren() as TextRenderable[]
      expect(modelRows.every((row) => !row.selectable)).toBe(true)
      const fast = modelRows.find((row) => row.plainText.includes("fast"))
      if (!fast) throw new Error("fast model row was not rendered")
      ui.composer.blur()
      expect(ui.composer.focused).toBe(false)
      await setup.mockMouse.click(fast.x + 2, fast.y)
      await waitUntil(() => sent.includes("/model fast"))
      expect(ui.composer.focused).toBe(true)

      await setup.mockMouse.click(
        ui.runtimeControls.accessText.x + 2,
        ui.runtimeControls.accessText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      await setup.flush()
      const accessRows = ui.runtimeControls.menuRoot.getChildren() as TextRenderable[]
      const full = accessRows.find((row) => row.plainText.includes("Full access"))
      if (!full) throw new Error("full access row was not rendered")
      ui.composer.blur()
      expect(ui.composer.focused).toBe(false)
      await setup.mockMouse.click(full.x + 2, full.y)
      expect(ui.composer.focused).toBe(true)

      expect(scopes).toEqual([{
        project_path: "/tmp/nanobot-workspace",
        access_mode: "full",
        restrict_to_workspace: false,
      }])

      await setup.mockMouse.click(
        ui.runtimeControls.modelText.x + 2,
        ui.runtimeControls.modelText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      ui.composer.blur()
      await setup.mockMouse.click(ui.status.x, ui.status.y)
      expect(ui.runtimeControls.visible).toBe(false)
      expect(ui.composer.focused).toBe(true)

      await setup.mockMouse.click(
        ui.runtimeControls.accessText.x + 2,
        ui.runtimeControls.accessText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      ui.composer.blur()
      await setup.mockMouse.click(ui.status.x, ui.status.y)
      expect(ui.runtimeControls.visible).toBe(false)
      expect(ui.composer.focused).toBe(true)
      expect(settingsRequests).toBe(1)
      expect(workspaceRequests).toBe(1)

      expect((app as unknown as { activeTurn: boolean }).activeTurn).toBe(true)
      app.accept({ event: "goal_status", chat_id: "chat", status: "idle" })
    } finally {
      globalThis.fetch = original
    }
  })

  test("selects model presets beyond the runtime menu's visible limit", async () => {
    const original = globalThis.fetch
    const sent: string[] = []
    globalThis.fetch = (async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/settings")) {
        return new Response(JSON.stringify({
          model_presets: [
            { name: "default", model: "test/model" },
            ...Array.from({ length: 10 }, (_, index) => ({
              name: `preset-${index}`,
              model: `test/model-${index}`,
            })),
          ],
        }))
      }
      if (url.endsWith("/api/workspaces")) {
        return new Response(JSON.stringify({ controls: { can_use_full_access: true } }))
      }
      return new Response(JSON.stringify({ sessions: [] }))
    }) as typeof fetch
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(sent),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      ready: boolean
      runtimeControls: {
        modelText: TextRenderable
        visible: boolean
        menuRoot: { getChildren(): unknown[] }
      }
    }

    try {
      await waitUntil(() => ui.ready)
      await setup.renderOnce()
      await setup.mockMouse.click(
        ui.runtimeControls.modelText.x + 2,
        ui.runtimeControls.modelText.y,
      )
      await waitUntil(() => ui.runtimeControls.visible)
      await setup.flush()
      expect(ui.runtimeControls.menuRoot.getChildren()).toHaveLength(9)
      expect(setup.captureCharFrame()).toContain("1–8 of 11 ↓")
      expect(setup.captureCharFrame()).not.toContain("preset-8")

      for (let index = 0; index < 9; index += 1) setup.mockInput.pressArrow("down")
      await setup.flush()
      expect(setup.captureCharFrame()).toContain("›   preset-8")
      expect(setup.captureCharFrame()).toContain("3–10 of 11 ↑↓")

      setup.mockInput.pressEnter()
      await waitUntil(() => sent.includes("/model preset-8"))
      expect(ui.runtimeControls.visible).toBe(false)
    } finally {
      globalThis.fetch = original
    }
  })

  test("switches sessions only through the sessions command", async () => {
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return Promise.resolve(new Response(JSON.stringify({
        sessions: [
          { key: "websocket:chat", title: "Current chat", preview: "Current work" },
          { key: "websocket:other", title: "Release checklist", preview: "Ship it" },
        ],
      })))
    }) as typeof fetch
    const attached: string[] = []
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client([], attached),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      composer: TextareaRenderable
      sessionMenu: { visible: boolean; root: { getChildren(): unknown[] } }
      title: { getChildren(): unknown[] }
    }

    try {
      await waitUntil(() => (app as unknown as { ready: boolean }).ready)
      await setup.renderOnce()
      const titleItems = ui.title.getChildren() as TextRenderable[]
      expect(titleItems.some((item) => item.id === "nanobot-tui-title-text")).toBe(false)
      expect(ui.sessionMenu.visible).toBe(false)

      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionMenu.visible)
      await setup.flush()
      expect(ui.composer.placeholder).toBe("Search sessions")

      const rows = ui.sessionMenu.root.getChildren() as TextRenderable[]
      const other = rows.find((row) => row.plainText.includes("Release checklist"))
      if (!other) throw new Error("other session row was not rendered")
      ui.composer.blur()
      await setup.mockMouse.click(other.x + 2, other.y)
      await waitUntil(() => attached.length === 1)
      expect(attached).toEqual(["other"])
      expect(ui.sessionMenu.visible).toBe(false)
      expect(ui.composer.focused).toBe(true)
    } finally {
      globalThis.fetch = original
    }
  })

  test("offers clickable recovery actions without letting a late response revive stale state", async () => {
    setup = await createRenderer({ width: 96, height: 24, screenMode: "alternate-screen" })
    const calls: Array<{ action: string; chatId: string; recoveryId: string }> = []
    let deferredResolve: ((state: RecoveryState) => void) | undefined
    const recoveryClient = client()
    recoveryClient.updateRecovery = (action, chatId, recoveryId) => {
      calls.push({ action, chatId, recoveryId })
      if (recoveryId === "recovery-1") {
        return Promise.resolve({ status: "resuming", recovery_id: recoveryId })
      }
      if (action === "dismiss") {
        return Promise.resolve({ status: "recovered", recovery_id: recoveryId })
      }
      return new Promise((resolve) => { deferredResolve = resolve })
    }
    const app = NanobotTui.mount(
      setup.renderer,
      options,
      recoveryClient,
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({
      event: "attached",
      chat_id: "chat",
      recovery_state: {
        status: "awaiting_user",
        recovery_id: "recovery-1",
        reason: "tool execution interrupted",
      },
    })
    const ui = app as unknown as {
      activeTurn: boolean
      composer: TextareaRenderable
      recoveryNotice: {
        visible: boolean
        dismiss: TextRenderable
        resume: TextRenderable
      }
      status: TextRenderable
    }

    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("⚠ Task interrupted")
    expect(setup.captureCharFrame()).toContain("Tools will not replay automatically")
    expect(ui.status.plainText).toContain("continue or dismiss")
    expect(ui.activeTurn).toBe(false)
    expect(ui.composer.focused).toBe(true)

    await setup.mockMouse.click(ui.recoveryNotice.resume.x + 1, ui.recoveryNotice.resume.y)
    await waitUntil(() => calls.length === 1 && ui.activeTurn)
    expect(calls[0]).toEqual({
      action: "continue",
      chatId: "chat",
      recoveryId: "recovery-1",
    })
    expect(ui.recoveryNotice.visible).toBe(false)
    expect(ui.status.plainText).toContain("Continuing")

    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "awaiting_user",
      recovery_id: "recovery-2",
    })
    await setup.renderOnce()
    await setup.mockMouse.click(ui.recoveryNotice.resume.x + 1, ui.recoveryNotice.resume.y)
    await waitUntil(() => calls.length === 2)
    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "recovered",
      recovery_id: "recovery-2",
    })
    deferredResolve?.({ status: "resuming", recovery_id: "recovery-2" })
    await Bun.sleep(1)

    expect(ui.recoveryNotice.visible).toBe(false)
    expect(ui.activeTurn).toBe(false)
    expect(ui.composer.focused).toBe(true)

    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "awaiting_user",
      recovery_id: "recovery-unavailable",
      can_continue: false,
    })
    await setup.renderOnce()
    const unavailableFrame = setup.captureCharFrame()
    expect(unavailableFrame).toContain("can’t be resumed safely")
    expect(unavailableFrame).not.toContain("Continue")
    expect(ui.status.plainText).toContain("dismiss to start a new message")

    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "awaiting_user",
      recovery_id: "recovery-3",
    })
    await setup.renderOnce()
    await setup.mockMouse.click(ui.recoveryNotice.dismiss.x + 1, ui.recoveryNotice.dismiss.y)
    await waitUntil(() => calls.length === 3 && !ui.recoveryNotice.visible)
    expect(calls[2]).toEqual({
      action: "dismiss",
      chatId: "chat",
      recoveryId: "recovery-3",
    })

    app.accept({
      event: "recovery_state",
      chat_id: "chat",
      status: "awaiting_user",
      recovery_id: "recovery-4",
      can_continue: false,
    })
    await setup.renderOnce()
    expect(ui.recoveryNotice.resume.visible).toBe(false)
    expect(ui.recoveryNotice.dismiss.visible).toBe(true)
  })

  test("preserves gateway slash lifecycle while local navigation stays in the same menu", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const sent: string[] = []
    const app = mount(setup, sent)
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      commandMenu: {
        setCommands(commands: SlashCommand[]): void
      }
      activeTurn: boolean
    }
    ui.commandMenu.setCommands([{
      command: "/new",
      title: "New chat",
      description: "Reset this chat",
      argHint: "",
      lifecycle: "finalize_active_turn",
      acceptsArgs: false,
    }, {
      command: "/status",
      title: "Status",
      description: "Show status",
      argHint: "",
      lifecycle: "side_channel",
      acceptsArgs: false,
    }])

    app.accept({ event: "goal_status", chat_id: "chat", status: "running" })
    ui.composer.setText("/status")
    ui.composer.submit()
    await waitUntil(() => sent.includes("/status"))
    expect(ui.activeTurn).toBe(true)
    app.accept({
      event: "message",
      chat_id: "chat",
      text: "Runtime healthy",
      turn_id: "turn",
    })
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("Runtime healthy")

    ui.composer.setText("/new")
    ui.composer.submit()
    await waitUntil(() => sent.includes("/new"))
    expect(ui.activeTurn).toBe(false)
    expect(sent).toEqual(["/status", "/new"])
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("/new")
  })

  test("blocks sends and ignores late session results after closing the picker", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let resolveFetch: ((response: Response) => void) | undefined
    globalThis.fetch = ((input: string | URL | Request) => {
      if (String(input).endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return new Promise<Response>((resolve) => {
        resolveFetch = resolve
      })
    }) as typeof fetch
    const sent: string[] = []
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(sent),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
      sessionLoading: boolean
    }

    try {
      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => ui.sessionLoading)
      ui.composer.setText("do not send")
      ui.composer.submit()
      await Bun.sleep(10)
      expect(sent).toEqual([])

      setup.mockInput.pressEscape()
      await Bun.sleep(10)
      resolveFetch?.(new Response(JSON.stringify({ sessions: [] })))
      await Bun.sleep(10)
      expect(ui.sessionMenu.visible).toBe(false)
      expect(ui.composer.plainText).toBe("")
    } finally {
      globalThis.fetch = original
    }
  })

  test("applies a query typed while sessions are still loading", async () => {
    setup = await createRenderer({ width: 80, height: 24, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    let resolveFetch: ((response: Response) => void) | undefined
    globalThis.fetch = ((input: string | URL | Request) => {
      if (String(input).endsWith("/api/webui/sidebar-state")) {
        return Promise.resolve(new Response(JSON.stringify({})))
      }
      return new Promise<Response>((resolve) => {
        resolveFetch = resolve
      })
    }) as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    await Bun.sleep(1)
    const ui = app as unknown as {
      composer: TextareaRenderable
      sessionMenu: { visible: boolean }
    }

    try {
      ui.composer.setText("/sessions")
      ui.composer.submit()
      await waitUntil(() => resolveFetch !== undefined)
      ui.composer.setText("release")
      resolveFetch!(new Response(JSON.stringify({
        sessions: [
          { key: "websocket:chat", title: "Current chat", preview: "Current work" },
          { key: "websocket:other", title: "Release checklist", preview: "Ship it" },
        ],
      })))
      await waitUntil(() => ui.sessionMenu.visible)
      await setup.flush()
      const frame = setup.captureCharFrame()
      expect(frame).toContain("Release checklist")
      expect(occurrences(frame, "Current chat")).toBe(0)
    } finally {
      globalThis.fetch = original
    }
  })

  test("shows compact session context without exposing private reasoning", async () => {
    setup = await createRenderer({ width: 96, height: 26, screenMode: "alternate-screen" })
    const original = globalThis.fetch
    globalThis.fetch = ((input: string | URL | Request) => {
      expect(String(input)).toContain("/api/sessions/websocket%3Achat/context")
      return Promise.resolve(new Response(JSON.stringify({
        total_messages: 24,
        archived_messages: 16,
        replay_messages: 10,
        estimated_replay_tokens: 2048,
        estimated_summary_tokens: 128,
        estimated_session_tokens: 2176,
        archived_summary: "The earlier turns agreed on a release plan.",
        archived_summary_at: "2026-08-13T10:00:00Z",
      })))
    }) as typeof fetch
    const app = NanobotTui.mount(
      setup.renderer,
      { ...options, apiUrl: "http://nanobot.test", apiToken: "secret" },
      client(),
      new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    )
    app.accept({ event: "attached", chat_id: "chat" })
    const ui = app as unknown as {
      composer: TextareaRenderable
      contextPanel: { visible: boolean }
      runtimeControls: { contextText: { plainText: string } }
    }

    try {
      ui.composer.setText("/context")
      ui.composer.submit()
      await waitUntil(() => ui.contextPanel.visible)
      await setup.flush()
      expect(ui.runtimeControls.contextText.plainText).toContain("~2.2k ctx")
      const frame = setup.captureCharFrame()

      expect(frame).toContain("~2.2k tokens · 10 replay · 16 archived")
      expect(frame).toContain("The earlier turns agreed on a release plan.")
      expect(frame).not.toContain("Agent context")
      expect(frame).not.toContain("summary active")
      expect(frame).not.toContain("memory, instructions, and skills are added separately")

      setup.resize(40, 10)
      await setup.renderOnce()
      const compact = setup.captureCharFrame()
      expect(occurrences(compact, "Agent context")).toBe(0)
      expect(occurrences(compact, "Ask nanobot anything")).toBe(1)

      setup.mockInput.pressEscape()
      await waitUntil(() => !ui.contextPanel.visible)
      expect(ui.contextPanel.visible).toBe(false)
    } finally {
      globalThis.fetch = original
    }
  })

  test("opens the latest turn diff as a full-screen, navigable view", async () => {
    setup = await createRenderer({ width: 96, height: 28, screenMode: "alternate-screen" })
    const app = mount(setup)
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => (app as unknown as { ready: boolean }).ready)
    app.accept({ event: "message_accepted", chat_id: "chat", turn_id: "edit-turn" })
    app.accept({
      event: "file_edit",
      chat_id: "chat",
      edits: [{
        call_id: "edit-1",
        tool: "edit_file",
        path: "src/first.ts",
        status: "done",
        added: 2,
        deleted: 1,
        diff: {
          format: "unified",
          truncated: true,
          text: [
            "--- a/src/first.ts",
            "+++ b/src/first.ts",
            "@@ -1 +1,2 @@",
            "-const oldValue = 1",
            "+const newValue = 2",
            "+export { newValue }",
          ].join("\n"),
        },
      }, {
        call_id: "edit-2",
        tool: "write_file",
        path: "src/second.py",
        status: "done",
        added: 1,
        deleted: 0,
        diff: {
          format: "unified",
          text: [
            "--- a/src/second.py",
            "+++ b/src/second.py",
            "@@ -0,0 +1 @@",
            "+print('hello')",
          ].join("\n"),
        },
      }],
    })
    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "edit-turn" })
    const ui = app as unknown as {
      composer: TextareaRenderable
      diffViewer: {
        visible: boolean
        scroll: { getChildren(): Array<{ addedBg?: { toInts(): number[] } }> }
      }
    }

    ui.composer.setText("/diff")
    ui.composer.submit()
    await waitUntil(() => ui.diffViewer.visible)
    await setup.flush()
    let frame = setup.captureCharFrame()
    expect(frame).toContain("Diff · Last turn · 2 changes · +3 -1")
    expect(frame).toContain("1/2 · src/first.ts · +2 -1")
    expect(frame).toContain("const newValue = 2")
    expect(frame).toContain("Diff truncated by the gateway")
    expect(frame).not.toContain("Ask nanobot anything")

    setup.mockInput.pressArrow("right")
    await setup.flush()
    frame = setup.captureCharFrame()
    expect(frame).toContain("2/2 · src/second.py · +1 -0")
    expect(frame).toContain("print('hello')")

    setup.renderer.emit(CliRenderEvents.THEME_MODE, "light")
    await setup.flush()
    expect(ui.diffViewer.scroll.getChildren()[0]?.addedBg?.toInts().slice(0, 3)).toEqual([231, 246, 236])
    expect(setup.captureCharFrame()).toContain("print('hello')")

    setup.resize(52, 18)
    await setup.renderOnce()
    expect(setup.captureCharFrame()).toContain("←/→ file · pgup/pgdn · esc")

    setup.mockInput.pressEscape()
    await waitUntil(() => !ui.diffViewer.visible)
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("Ask nanobot anything")
  })
})
