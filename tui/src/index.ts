import { NanobotTui, type AppOptions } from "./app"

function required(name: string): string {
  const value = process.env[name]?.trim()
  if (!value) throw new Error(`${name} is required`)
  return value
}

const options: AppOptions = {
  wsUrl: required("NANOBOT_TUI_WS_URL"),
  apiUrl: process.env.NANOBOT_TUI_API_URL?.trim() || "",
  apiToken: process.env.NANOBOT_TUI_API_TOKEN?.trim() || "",
  chatId: process.env.NANOBOT_TUI_CHAT_ID?.trim() || undefined,
  model: process.env.NANOBOT_TUI_MODEL?.trim() || "unknown model",
  workspace: process.env.NANOBOT_TUI_WORKSPACE?.trim() || "",
  version: process.env.NANOBOT_TUI_VERSION?.trim() || "dev",
  access: process.env.NANOBOT_TUI_ACCESS?.trim() || "workspace access",
}

let app: NanobotTui | undefined
let shuttingDown = false

const shutdown = (code = 0) => {
  if (shuttingDown) return
  shuttingDown = true
  app?.stop()
  process.exitCode = code
}

for (const signal of ["SIGHUP", "SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => shutdown())
}
process.once("exit", () => app?.stop())
process.once("uncaughtException", (error) => {
  shutdown(1)
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
})
process.once("unhandledRejection", (error) => {
  shutdown(1)
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
})

app = await NanobotTui.create(options)
if (shuttingDown) app.stop()
else app.start()
