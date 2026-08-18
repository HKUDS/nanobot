import { mkdir, rename, rm } from "node:fs/promises"
import { dirname } from "node:path"

export async function rememberChat(path: string | undefined, chatId: string): Promise<void> {
  if (!path || !chatId) return
  const temporary = `${path}.tmp-${process.pid}`
  try {
    await mkdir(dirname(path), { recursive: true })
    const content = `${JSON.stringify({ schema_version: 1, chat_id: chatId })}\n`
    await Bun.write(temporary, content)
    try {
      await rename(temporary, path)
    } catch {
      // Windows cannot always atomically replace an existing destination.
      await Bun.write(path, content)
      await rm(temporary, { force: true })
    }
  } catch {
    // Session navigation must keep working when this optional convenience file
    // is read-only, on a network volume, or removed during shutdown.
    await rm(temporary, { force: true }).catch(() => {})
  }
}
