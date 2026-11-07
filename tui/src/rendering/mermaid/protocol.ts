import { OUTPUT_LIMIT, SOURCE_LIMIT } from "./types"

export const REQUEST_LIMIT = OUTPUT_LIMIT * 6 + SOURCE_LIMIT * 6 + 8192
export const REPLY_LIMIT = OUTPUT_LIMIT * 6 + Math.ceil(OUTPUT_LIMIT * 4 / 3) + 8192

/** Bounded records, including incomplete records and UTF-8 split across pipe reads. */
export async function* jsonLines(stream: ReadableStream<Uint8Array>, limit: number): AsyncGenerator<unknown> {
  const reader = stream.getReader()
  let parts: Uint8Array[] = [], size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      let start = 0
      while (start < value.length) {
        const end = value.indexOf(10, start)
        const part = value.subarray(start, end < 0 ? value.length : end)
        size += part.length
        if (size > limit) throw new Error("Diagram worker pipe limit")
        parts.push(part)
        if (end < 0) break
        yield JSON.parse(Buffer.concat(parts).toString("utf8"))
        parts = []; size = 0
        start = end + 1
      }
    }
    if (size) throw new Error("Incomplete diagram worker reply")
  } finally { reader.releaseLock() }
}
