import {
  createHostClipboard,
  type HostClipboardService,
} from "@opentui/core"

const IMAGE_MIME_TYPES = [
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
] as const
const MAX_IMAGE_BYTES = 6 * 1024 * 1024

export interface ClipboardImage {
  dataUrl: string
  mimeType: typeof IMAGE_MIME_TYPES[number]
}

export interface ClipboardImageReader {
  read(): Promise<ClipboardImage>
  dispose(): Promise<void>
}

type ClipboardFactory = () => HostClipboardService

function readFailure(status: string): Error {
  if (status === "empty") return new Error("No image in clipboard")
  if (status === "limit-exceeded") return new Error("Clipboard image is larger than 6 MB")
  if (status === "timed-out") return new Error("Clipboard image read timed out")
  return new Error("Clipboard image paste is unavailable")
}

/** Lazily owns OpenTUI's native host clipboard so ordinary TUI startup does no clipboard work. */
export function createClipboardImageReader(
  createClipboard: ClipboardFactory = () => createHostClipboard({ maxReadBytes: MAX_IMAGE_BYTES }),
): ClipboardImageReader {
  let clipboard: HostClipboardService | null = null
  let disposed = false

  return {
    async read(): Promise<ClipboardImage> {
      if (disposed) throw new Error("Clipboard image paste is unavailable")
      clipboard ||= createClipboard()
      const result = await clipboard.read({ preferredTypes: IMAGE_MIME_TYPES })
      if (result.status !== "read") throw readFailure(result.status)
      const normalizedMime = result.representation.mimeType.toLowerCase()
      const mimeType = IMAGE_MIME_TYPES.find((candidate) => candidate === normalizedMime)
      if (!mimeType) throw new Error("Clipboard does not contain a supported image")
      const bytes = result.representation.bytes
      if (!bytes.length) throw new Error("Clipboard image is empty")
      if (bytes.length > MAX_IMAGE_BYTES) throw new Error("Clipboard image is larger than 6 MB")
      return {
        mimeType,
        dataUrl: `data:${mimeType};base64,${Buffer.from(bytes).toString("base64")}`,
      }
    },
    async dispose(): Promise<void> {
      if (disposed) return
      disposed = true
      await clipboard?.dispose()
      clipboard = null
    },
  }
}
