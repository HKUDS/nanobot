import { describe, expect, test } from "bun:test"
import type { ServerWebSocket } from "bun"
import type { TextareaRenderable } from "@opentui/core"
import { createTestRenderer, MockTreeSitterClient } from "@opentui/core/testing"

import { NanobotTui } from "./app"
import type { InboundEvent, NanobotClient } from "./protocol"

async function waitUntil(predicate: () => boolean): Promise<void> {
  const deadline = Date.now() + 2_000
  while (!predicate() && Date.now() < deadline) await Bun.sleep(5)
  expect(predicate()).toBe(true)
}

async function fixture() {
  let socket: ServerWebSocket<undefined> | undefined
  const sent: string[] = []
  const server = Bun.serve<undefined>({
    hostname: "127.0.0.1",
    port: 0,
    fetch: (request, server) => server.upgrade(request) ? undefined : new Response(null),
    websocket: {
      open(ws) {
        socket = ws
        ws.send(JSON.stringify({ event: "attached", chat_id: "chat" }))
        ws.send(JSON.stringify({ event: "goal_status", chat_id: "chat", status: "running" }))
      },
      message(_ws, message) {
        const frame = JSON.parse(String(message))
        if (frame.type === "message") sent.push(frame.content)
      },
    },
  })
  const setup = await createTestRenderer({ width: 72, height: 20 })
  const app = NanobotTui.mount(setup.renderer, {
    wsUrl: `ws://127.0.0.1:${server.port}`,
    apiUrl: "",
    apiToken: "",
    model: "test/model",
    modelPreset: "default",
    workspace: "/tmp/nanobot-workspace",
    version: "test",
    access: "workspace access",
    theme: "dark",
  }, undefined, new MockTreeSitterClient({ autoResolveTimeout: 0 }))
  const ui = app as unknown as {
    composer: TextareaRenderable
    client: NanobotClient
    ready: boolean
    activeTurn: boolean
    status: { plainText: string }
  }
  ui.client.connect()
  await waitUntil(() => ui.ready && ui.activeTurn)
  return {
    app, ui, setup, sent,
    send(events: InboundEvent[]) {
      for (const event of events) socket!.send(JSON.stringify(event))
    },
    async close() {
      app.stop()
      await server.stop(true)
    },
  }
}

const deltas = (count: number): InboundEvent[] => Array.from({ length: count }, (_, index) => ({
  event: "delta", chat_id: "chat", text: `${index} `,
}))

describe("gateway output scheduling", () => {
  test("repaints a submitted draft without another gateway event or status animation", async () => {
    const f = await fixture()
    try {
      const animation = f.app as unknown as { shimmerTimer: ReturnType<typeof setInterval> | null }
      if (animation.shimmerTimer) clearInterval(animation.shimmerTimer)
      animation.shimmerTimer = null
      f.ui.composer.setText("quiet gateway submit")
      await waitUntil(() => f.setup.captureCharFrame().includes("quiet gateway submit"))
      let painted = false
      let applied = 0
      const accept = f.app.accept.bind(f.app)
      f.app.accept = (event) => {
        applied += 1
        accept(event)
      }
      f.setup.renderer.on("frame", () => {
        if (f.ui.composer.plainText !== "") return
        const lines = f.setup.captureCharFrame().split("\n")
        const draft = lines.slice(f.ui.composer.screenY, f.ui.composer.screenY + f.ui.composer.height)
        painted = lines.some((line) => /›\s*quiet gateway submit/u.test(line))
          && draft.every((line) => !line.includes("quiet gateway submit"))
      })
      f.setup.mockInput.pressEnter()
      // Submit must paint without a manual render or a server reply.
      await waitUntil(() => f.sent.length === 1 && painted)

      expect(f.sent).toEqual(["quiet gateway submit"])
      expect(applied).toBe(0)
      expect(f.ui.composer.plainText).toBe("")
      expect(f.ui.activeTurn).toBe(true)
    } finally {
      await f.close()
    }
  })

  test("repaints the cleared draft while received output is still queued", async () => {
    const f = await fixture()
    try {
      f.ui.composer.setText("submit during output")
      await waitUntil(() => f.setup.captureCharFrame().includes("submit during output"))
      let applied = 0
      let appliedAtPaint = -1
      const events = deltas(64)
      const accept = f.app.accept.bind(f.app)
      f.app.accept = (event) => {
        accept(event)
        applied += 1
        if (applied === 1) f.setup.mockInput.pressEnter()
        Bun.sleepSync(5)
      }
      f.setup.renderer.on("frame", () => {
        if (appliedAtPaint >= 0 || applied === 0 || f.ui.composer.plainText !== "") return
        const lines = f.setup.captureCharFrame().split("\n")
        const draft = lines.slice(f.ui.composer.screenY, f.ui.composer.screenY + f.ui.composer.height)
        if (draft.every((line) => !line.includes("submit during output"))) appliedAtPaint = applied
      })
      f.send(events)
      await waitUntil(() => f.sent.length === 1 && appliedAtPaint >= 0)

      expect(f.sent).toEqual(["submit during output"])
      expect(appliedAtPaint).toBeLessThan(events.length)
      await waitUntil(() => applied === events.length)
    } finally {
      await f.close()
    }
  })

  test("sends the IME commit before draining a burst and preserves event order", async () => {
    const f = await fixture()
    try {
      const applied: InboundEvent[] = []
      const events: InboundEvent[] = [
        ...deltas(256),
        { event: "stream_end", chat_id: "chat" },
        { event: "turn_end", chat_id: "chat" },
      ]
      let appliedAtSend = -1
      const send = f.ui.client.send.bind(f.ui.client)
      f.ui.client.send = (...args) => {
        appliedAtSend = applied.length
        return send(...args)
      }
      const accept = f.app.accept.bind(f.app)
      f.app.accept = (event) => {
        accept(event)
        applied.push(event)
        if (applied.length === 1) {
          f.setup.mockInput.pressEnter()
          setTimeout(() => f.ui.composer.setText("你好"), 0)
        }
      }
      f.ui.composer.setText("你")
      f.send(events)
      await waitUntil(() => f.sent.length === 1 && applied.length === events.length)

      expect(f.sent).toEqual(["你好"])
      expect(appliedAtSend).toBe(1)
      expect(f.ui.composer.plainText).toBe("")
      expect(applied).toEqual(events)
      expect(f.ui.activeTurn).toBe(false)
    } finally {
      await f.close()
    }
  })

  test("yields to other callbacks between output batches", async () => {
    const f = await fixture()
    try {
      let applied = 0
      let appliedAtYield = 0
      const accept = f.app.accept.bind(f.app)
      f.app.accept = (event) => {
        accept(event)
        if (++applied === 1) setImmediate(() => { appliedAtYield = applied })
      }
      f.send(deltas(256))
      await waitUntil(() => applied === 256 && appliedAtYield > 0)

      expect(appliedAtYield).toBeLessThanOrEqual(64)
    } finally {
      await f.close()
    }
  })

  test("yields after a costly event even before reaching the batch limit", async () => {
    const f = await fixture()
    try {
      let applied = 0
      let appliedAtYield = 0
      const accept = f.app.accept.bind(f.app)
      f.app.accept = (event) => {
        accept(event)
        if (++applied === 1) {
          Bun.sleepSync(5)
          setImmediate(() => { appliedAtYield = applied })
        }
      }
      f.send(deltas(64))
      await waitUntil(() => applied === 64 && appliedAtYield > 0)

      expect(appliedAtYield).toBe(1)
    } finally {
      await f.close()
    }
  })

  test("discards queued output when another session attaches", async () => {
    const f = await fixture()
    try {
      const applied: InboundEvent[] = []
      const accept = f.app.accept.bind(f.app)
      f.app.accept = (event) => {
        applied.push(event)
        accept(event)
      }
      // Hold output behind an empty submit while both sessions' frames arrive.
      f.setup.mockInput.pressEnter()
      f.send([
        { event: "delta", chat_id: "chat", text: "old session" },
        { event: "attached", chat_id: "next" },
        { event: "delta", chat_id: "next", text: "new session" },
        { event: "stream_end", chat_id: "next" },
      ])
      await waitUntil(() => applied.some((event) => event.event === "stream_end"))

      expect(applied).toEqual([
        { event: "attached", chat_id: "next" },
        { event: "delta", chat_id: "next", text: "new session" },
        { event: "stream_end", chat_id: "next" },
      ])
    } finally {
      await f.close()
    }
  })

  test("stops a queued burst when the renderer is destroyed", async () => {
    const f = await fixture()
    try {
      let applied = 0
      const accept = f.app.accept.bind(f.app)
      f.app.accept = (event) => {
        accept(event)
        applied += 1
        f.setup.renderer.destroy()
      }
      f.send(deltas(256))
      await waitUntil(() => f.setup.renderer.isDestroyed)
      await Bun.sleep(30)

      expect(applied).toBe(1)
    } finally {
      await f.close()
    }
  })

  test("renders received output before reporting a disconnect without sending queued prompts", async () => {
    const f = await fixture()
    try {
      const applied: InboundEvent[] = []
      const accept = f.app.accept.bind(f.app)
      f.app.accept = (event) => {
        accept(event)
        applied.push(event)
        if (applied.length === 1) {
          f.ui.client.close()
          const transport = f.ui.client as unknown as {
            options: { onStatus(status: "closed"): void }
          }
          transport.options.onStatus("closed")
        }
      }
      f.ui.composer.setText("follow up")
      f.setup.mockInput.pressTab()
      f.setup.mockInput.pressEnter()
      const events: InboundEvent[] = [
        ...deltas(256),
        { event: "stream_end", chat_id: "chat" },
        { event: "turn_end", chat_id: "chat" },
      ]
      f.send(events)
      await waitUntil(() => applied.length === events.length && !f.ui.ready)

      expect(applied).toEqual(events)
      expect(f.sent).toEqual([])
      expect(f.ui.activeTurn).toBe(false)
      expect(f.ui.status.plainText).not.toStartWith("Ready")
    } finally {
      await f.close()
    }
  })

  test("keeps queued follow-ups waiting until the turn ends", async () => {
    const f = await fixture()
    try {
      f.ui.composer.setText("follow up")
      f.setup.mockInput.pressTab()
      expect(f.ui.composer.plainText).toBe("")
      f.send([{ event: "goal_status", chat_id: "chat", status: "idle" }])
      await waitUntil(() => !f.ui.activeTurn)
      expect(f.sent).toEqual([])

      f.send([{ event: "turn_end", chat_id: "chat" }])
      await waitUntil(() => f.sent.length === 1)
      expect(f.sent).toEqual(["follow up"])
    } finally {
      await f.close()
    }
  })
})
