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

const app = await NanobotTui.create(options)
app.start()
