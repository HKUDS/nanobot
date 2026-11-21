import { renderCommandResult } from "../../../packages/client-events/command-result"

/** POSIX message locale precedence; Windows may expose only the system locale. */
export function terminalLocale(): string {
  const raw = process.env.LC_ALL || process.env.LC_MESSAGES || process.env.LANG || Intl.DateTimeFormat().resolvedOptions().locale
  const tag = raw.toLowerCase().split(/[.@]/u)[0]?.replaceAll("_", "-") || "en"
  const language = tag.split("-")[0]
  if (language === "zh") return /-(tw|hk|mo|hant)(-|$)/u.test(tag) ? "zh-TW" : "zh-CN"
  if (language === "pt") return "pt-BR"
  return language || "en"
}

export function terminalMessageText(event: { text: string; command_result?: unknown }): string {
  return event.command_result === undefined ? event.text : renderCommandResult(event.command_result, terminalLocale()) ?? event.text
}
