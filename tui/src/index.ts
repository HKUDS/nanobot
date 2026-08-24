import { NanobotTui, sessionExitMessage, type AppOptions } from "./app"
import { currentGitBranch } from "./host"

// Keep in sync with _TUI_DETACH_EXIT_CODE in nanobot/cli/tui_launcher.py.
const TUI_DETACH_EXIT_CODE = 90

function themePreference(): AppOptions["theme"] {
  const value = process.env.NANOBOT_TUI_THEME?.trim() || "auto"
  if (value === "auto" || value === "dark" || value === "light") return value
  throw new Error("NANOBOT_TUI_THEME must be auto, dark, or light")
}

function initialView(): AppOptions["initialView"] {
  const value = process.env.NANOBOT_TUI_OPEN?.trim()
  if (!value) return undefined
  if (value === "config") return value
  throw new Error("NANOBOT_TUI_OPEN must be config")
}

const workspace = process.env.NANOBOT_TUI_WORKSPACE?.trim() || ""
const hostWorkspace = process.cwd()
const bootstrapUrl = process.env.NANOBOT_TUI_BOOTSTRAP_URL?.trim() || ""
const wsUrl = process.env.NANOBOT_TUI_WS_URL?.trim() || ""
const gatewayStopCommand = process.env.NANOBOT_TUI_GATEWAY_STOP_COMMAND?.trim()
  || "nanobot gateway stop"
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
  initialView: initialView(),
  onDetach: (chatId) => {
    process.exitCode = TUI_DETACH_EXIT_CODE
    process.stdout.write("Detached; the agent continues in the background.\n")
    if (chatId) process.stdout.write(sessionExitMessage(chatId))
    process.stdout.write(`Stop it with: ${gatewayStopCommand}\n`)
  },
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
