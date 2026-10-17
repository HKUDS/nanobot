import { expect, test } from "bun:test"
import { TextareaRenderable } from "@opentui/core"
import { MockTreeSitterClient, createTestRenderer } from "@opentui/core/testing"
import { NanobotTui } from "./app"
import { client, options, waitUntil } from "./test-support"
import type { MessageOptions } from "../client"

test.each([false, true])("restores queued prompts when automatic sending fails (image draft: %s)", async (imageDraft) => {
  const setup = await createTestRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
  const sent: string[] = []
  const sentOptions: MessageOptions[] = []
  const transport = client(sent, [], [], sentOptions)
  const send = transport.send.bind(transport)
  let failSend = false
  transport.send = (content, messageOptions) => {
    if (failSend) throw new Error("gateway connection is not open")
    return send(content, messageOptions)
  }
  const app = NanobotTui.mount(
    setup.renderer,
    options,
    transport,
    new MockTreeSitterClient({ autoResolveTimeout: 0 }),
    undefined,
    {
      async read() { return { mimeType: "image/png", dataUrl: "data:image/png;base64,AAEC/w==" } },
      async dispose() {},
    },
  )
  const ui = app as unknown as { ready: boolean; composer: TextareaRenderable }
  try {
    app.accept({ event: "attached", chat_id: "chat" })
    await waitUntil(() => ui.ready)
    ui.composer.setText("first")
    ui.composer.submit()
    await waitUntil(() => sent.length === 1)
    for (const content of ["queued one", "queued two"]) {
      ui.composer.setText(content)
      setup.mockInput.pressTab()
      await waitUntil(() => ui.composer.plainText === "")
    }
    if (imageDraft) {
      setup.mockInput.pressKey("v", { ctrl: true })
      await waitUntil(() => ui.composer.plainText.includes("[Image #1]"))
    }

    failSend = true
    app.accept({ event: "turn_end", chat_id: "chat", turn_id: "turn" })
    expect(sent).toEqual(["first"])
    expect(ui.composer.plainText).toBe(`${imageDraft ? "[Image #1]\n\n" : ""}queued one\n\nqueued two`)

    failSend = false
    ui.composer.submit()
    await waitUntil(() => sent.length === 2)
    expect(sent[1]).toBe("queued one\n\nqueued two")
    expect(sentOptions[1]?.media ?? []).toHaveLength(imageDraft ? 1 : 0)
  } finally {
    setup.renderer.destroy()
  }
})
