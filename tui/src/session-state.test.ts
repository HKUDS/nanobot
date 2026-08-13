import { afterEach, describe, expect, test } from "bun:test"
import { mkdtemp, readFile, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { rememberChat } from "./session-state"

describe("TUI session state", () => {
  let directory = ""

  afterEach(async () => {
    if (directory) await rm(directory, { recursive: true, force: true })
    directory = ""
  })

  test("atomically remembers the last attached gateway chat", async () => {
    directory = await mkdtemp(join(tmpdir(), "nanobot-tui-state-"))
    const path = join(directory, "nested", "state.json")

    await rememberChat(path, "chat-123")

    expect(JSON.parse(await readFile(path, "utf8"))).toEqual({
      schema_version: 1,
      chat_id: "chat-123",
    })
  })
})
