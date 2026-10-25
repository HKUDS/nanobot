import { describe, expect, test } from "bun:test"
import type { ClipboardReadResult, HostClipboardService } from "@opentui/core"

import { createClipboardImageReader } from "./clipboard-image"

function clipboard(result: ClipboardReadResult) {
  let disposed = false
  const service = {
    maxWriteBytes: 1,
    read: async () => result,
    writeText: async () => ({ status: "unsupported" as const }),
    clear: async () => ({ status: "unsupported" as const }),
    dispose: async () => { disposed = true },
  } satisfies HostClipboardService
  return { service, disposed: () => disposed }
}

describe("clipboard image reader", () => {
  test("encodes supported native clipboard bytes as a data URL", async () => {
    const fake = clipboard({
      status: "read",
      representation: { mimeType: "image/png", bytes: Uint8Array.from([0, 1, 2, 255]) },
    })
    const reader = createClipboardImageReader(() => fake.service)

    expect(await reader.read()).toEqual({
      mimeType: "image/png",
      dataUrl: "data:image/png;base64,AAEC/w==",
    })
    await reader.dispose()
    expect(fake.disposed()).toBeTrue()
  })

  test.each([
    ["empty", "No image in clipboard"],
    ["limit-exceeded", "Clipboard image is larger than 6 MB"],
    ["timed-out", "Clipboard image read timed out"],
    ["unsupported", "Clipboard image paste is unavailable"],
  ] as const)("reports %s without exposing native details", async (status, message) => {
    const fake = clipboard({ status })
    const reader = createClipboardImageReader(() => fake.service)

    await expect(reader.read()).rejects.toThrow(message)
    await reader.dispose()
  })
})
