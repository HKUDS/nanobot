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
  test("submits and repaints before costly queued output finishes", async () => {
    const f = await fixture()
    try {
      const animation = f.app as unknown as { shimmerTimer: ReturnType<typeof setInterval> | null }
      if (animation.shimmerTimer) clearInterval(animation.shimmerTimer)
      animation.shimmerTimer = null
      f.ui.composer.setText("你")
      await waitUntil(() => f.setup.captureCharFrame().includes("你"))

      const events = deltas(64)
      const applied: InboundEvent[] = []
      let appliedAtSend = -1
      let appliedAtPaint = -1
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
        Bun.sleepSync(5)
      }
      f.setup.renderer.on("frame", () => {
        if (appliedAtPaint >= 0 || f.ui.composer.plainText !== "") return
        const lines = f.setup.captureCharFrame().split("\n")
        const draft = lines.slice(f.ui.composer.screenY, f.ui.composer.screenY + f.ui.composer.height)
        if (lines.some((line) => /›\s*你好/u.test(line)) && draft.every((line) => !line.includes("你好"))) {
          appliedAtPaint = applied.length
        }
      })

      f.send(events)
      await waitUntil(() => f.sent.length === 1 && appliedAtPaint >= 0)
      expect(f.sent).toEqual(["你好"])
      expect(appliedAtSend).toBe(1)
      expect(appliedAtPaint).toBeLessThan(events.length)
      await waitUntil(() => applied.length === events.length)
      expect(applied).toEqual(events)
    } finally {
      await f.close()
    }
  })

  test("yields after a costly event before reaching the batch limit", async () => {
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
})
