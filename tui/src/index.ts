import { NanobotTui, sessionExitMessage, type AppOptions } from "./app"
import { currentGitBranch } from "./host"

function themePreference(): AppOptions["theme"] {
  const value = process.env.NANOBOT_TUI_THEME?.trim() || "auto"
  if (value === "auto" || value === "dark" || value === "light") return value
  throw new Error("NANOBOT_TUI_THEME must be auto, dark, or light")
}

const workspace = process.env.NANOBOT_TUI_WORKSPACE?.trim() || ""
const hostWorkspace = process.cwd()
const bootstrapUrl = process.env.NANOBOT_TUI_BOOTSTRAP_URL?.trim() || ""
const wsUrl = process.env.NANOBOT_TUI_WS_URL?.trim() || ""
if (!bootstrapUrl && !wsUrl) {
  throw new Error("NANOBOT_TUI_BOOTSTRAP_URL or NANOBOT_TUI_WS_URL is required")
}
const options: AppOptions = {
  ...(bootstrapUrl
    ? {
        bootstrapUrl,
        bootstrapSecret: process.env.NANOBOT_TUI_BOOTSTRAP_SECRET?.trim() || "",
      }
    : { wsUrl }),
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
  onExit: (chatId) => {
    process.stdout.write(sessionExitMessage(chatId))
  },
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
