import { NanobotTui, type AppOptions } from "./app"
import { currentGitBranch } from "./host"

function required(name: string): string {
  const value = process.env[name]?.trim()
  if (!value) throw new Error(`${name} is required`)
  return value
}

function themePreference(): AppOptions["theme"] {
  const value = process.env.NANOBOT_TUI_THEME?.trim() || "auto"
  if (value === "auto" || value === "dark" || value === "light") return value
  throw new Error("NANOBOT_TUI_THEME must be auto, dark, or light")
}

const workspace = process.env.NANOBOT_TUI_WORKSPACE?.trim() || ""
const hostWorkspace = process.cwd()
const options: AppOptions = {
  wsUrl: required("NANOBOT_TUI_WS_URL"),
  apiUrl: process.env.NANOBOT_TUI_API_URL?.trim() || "",
  apiToken: process.env.NANOBOT_TUI_API_TOKEN?.trim() || "",
  chatId: process.env.NANOBOT_TUI_CHAT_ID?.trim() || undefined,
  model: process.env.NANOBOT_TUI_MODEL?.trim() || "unknown model",
  modelPreset: process.env.NANOBOT_TUI_MODEL_PRESET?.trim() || "default",
  workspace,
  hostWorkspace,
  branch: currentGitBranch(hostWorkspace),
  version: process.env.NANOBOT_TUI_VERSION?.trim() || "dev",
  access: process.env.NANOBOT_TUI_ACCESS?.trim() || "workspace access",
  theme: themePreference(),
  statePath: process.env.NANOBOT_TUI_STATE_PATH?.trim() || undefined,
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
else await app.start()
